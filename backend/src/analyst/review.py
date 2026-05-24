"""Quantitative Analyst: on-demand portfolio review by an LLM analyst.

Distinct from the pipeline judge (which evaluates individual trade proposals),
the analyst reviews the entire portfolio holistically — considering market
conditions, macro environment, position sizing, and risk — and produces
strategic guidance that can optionally be injected into the next pipeline run.

After the multi-user migration, reviews live in the per-user ``analyst_reviews``
table (one row per (user, review_id)). ``load_review`` returns the most recent
review for the given user; ``set_apply_to_pipeline`` flips the flag on that row.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

ANALYST_SYSTEM_PROMPT = """You are a senior quantitative portfolio analyst with deep expertise in equity markets, macro economics, and systematic trading strategies.

Your role is to provide a comprehensive, independent review of the user's portfolio — separate from the automated trading pipeline. You assess:
- The overall portfolio composition and risk profile
- Current macro and market conditions and how they affect the holdings
- Individual position quality and sizing
- Opportunities and threats not captured by the quant model

Be specific and data-driven. Avoid generic platitudes. Your review will optionally guide the pipeline's LLM judge on the next run, so your pipeline_guidance field should contain concrete, actionable instructions the judge can follow.

Do NOT recommend executing trades — only provide analysis and guidance."""


ANALYST_PROMPT = """Review the following portfolio and provide a comprehensive quantitative analyst assessment.

## Current Portfolio
{portfolio_json}

## Live P&L Snapshot
{pnl_json}

## Factor Scores (top holdings + universe leaders)
{scores_json}

## Recent News Context
{news_json}

## Market Regime
{regime_json}

Today's date: {date}

Return ONLY valid JSON matching this exact schema (no markdown, no code fences):
{{
  "overall_stance": "bullish" | "neutral" | "bearish",
  "summary": "<2-3 sentence executive summary of the portfolio review>",
  "market_context": "<assessment of current macro environment and how it affects these holdings>",
  "portfolio_health_score": <integer 0-100, where 100 is perfectly positioned>,
  "position_reviews": [
    {{
      "ticker": "<ticker>",
      "stance": "add" | "hold" | "trim" | "exit",
      "reasoning": "<one concise sentence>",
      "conviction": <float 0.0-1.0>
    }}
  ],
  "strengths": ["<portfolio strength>"],
  "concerns": ["<portfolio concern>"],
  "opportunities": ["<untapped opportunity in the universe>"],
  "risk_factors": ["<macro or idiosyncratic risk>"],
  "pipeline_guidance": ["<concrete instruction for the pipeline judge on next run, e.g. 'Prioritize trimming MSFT given -30% drawdown and weak momentum'>"]
}}"""


def run_analyst_review(
    portfolio: dict,
    pnl: dict,
    user_id: str,
    scores_df=None,
    news_map: dict | None = None,
    regime: dict | None = None,
) -> dict:
    """Run the quantitative analyst review and persist it for ``user_id``.

    Returns the full review dict.
    """
    if not user_id:
        raise ValueError("user_id is required for run_analyst_review")
    import pandas as pd

    news_map = news_map or {}
    regime = regime or {}

    # Build portfolio summary
    portfolio_value = pnl.get("total_portfolio_value", 0)
    cash_pct = (pnl.get("cash", 0) / portfolio_value * 100) if portfolio_value > 0 else 0

    portfolio_summary = {
        "total_value_usd": round(portfolio_value, 2),
        "cash": round(pnl.get("cash", 0), 2),
        "cash_pct": round(cash_pct, 1),
        "total_unrealized_pnl": round(pnl.get("total_unrealized_pnl", 0), 2),
        "total_return_pct": round(pnl.get("total_return_pct", 0) * 100, 2),
        "positions": [],
    }
    for pos in pnl.get("positions", []):
        portfolio_summary["positions"].append({
            "ticker": pos["ticker"],
            "shares": pos["shares"],
            "current_price": round(pos.get("current_price", 0), 2),
            "market_value": round(pos.get("market_value", 0), 2),
            "unrealized_pnl": round(pos.get("unrealized_pnl", 0), 2),
            "unrealized_pct": round(pos.get("unrealized_pct", 0) * 100, 2),
            "cost_basis": round(pos.get("cost_basis", 0), 2),
        })

    # Build scores summary
    scores_summary = []
    if scores_df is not None and not scores_df.empty:
        held = {pos["ticker"] for pos in portfolio.get("positions", [])}
        top = scores_df.head(15)
        held_df = scores_df[scores_df["ticker"].isin(held)]
        combined = pd.concat([top, held_df]).drop_duplicates(subset="ticker")
        for _, row in combined.iterrows():
            entry = {
                "ticker": row.get("ticker", ""),
                "composite_score": round(float(row.get("composite_score", 0)), 3),
                "decile": int(row.get("score_decile", 5)),
                "in_portfolio": row.get("ticker", "") in held,
            }
            for col in ["momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy",
                        "gross_margin_trend", "relative_valuation"]:
                if col in row and pd.notna(row[col]):
                    entry[col] = round(float(row[col]), 3)
            scores_summary.append(entry)

    # Build news summary
    news_summary = []
    for ticker, research in news_map.items():
        if research and hasattr(research, "ai_summary") and research.ai_summary:
            news_summary.append({
                "ticker": ticker,
                "sentiment": research.sentiment,
                "summary": research.ai_summary[:400],
                "risk_factors": (research.risk_factors or [])[:3],
            })

    prompt = ANALYST_PROMPT.format(
        portfolio_json=json.dumps(portfolio_summary, indent=2),
        pnl_json=json.dumps({
            "total_return_pct": portfolio_summary["total_return_pct"],
            "total_unrealized_pnl": portfolio_summary["total_unrealized_pnl"],
            "cash_pct": portfolio_summary["cash_pct"],
        }, indent=2),
        scores_json=json.dumps(scores_summary, indent=2),
        news_json=json.dumps(news_summary, indent=2),
        regime_json=json.dumps(regime, indent=2),
        date=datetime.now().strftime("%Y-%m-%d"),
    )

    client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.judge.model,
            max_tokens=4096,
            temperature=0.3,
            system=ANALYST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        # Extract just the JSON object in case there's surrounding text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        result = json.loads(raw)
    except Exception as e:
        result = {
            "overall_stance": "neutral",
            "summary": f"Analysis failed: {e}",
            "market_context": "",
            "portfolio_health_score": 50,
            "position_reviews": [],
            "strengths": [],
            "concerns": [str(e)],
            "opportunities": [],
            "risk_factors": [],
            "pipeline_guidance": [],
        }

    review = {
        "review_id": str(uuid.uuid4())[:8],
        "created_at": datetime.now().isoformat(),
        "portfolio_value": portfolio_value,
        "apply_to_pipeline": False,
        **result,
    }

    save_review(review, user_id=user_id)
    return review


# ============================================================================
# Persistence — per-user, backed by the analyst_reviews Postgres table.
# ============================================================================

_JSONB_FIELDS = (
    "position_reviews", "strengths", "concerns",
    "opportunities", "risk_factors", "pipeline_guidance",
)


def save_review(review: dict, user_id: str) -> None:
    """Insert a new analyst review row for the given user."""
    if not user_id:
        raise ValueError("user_id is required for save_review")
    con = get_connection()
    try:
        con.execute(
            """
            INSERT INTO analyst_reviews (
                review_id, user_id, created_at, portfolio_value,
                overall_stance, summary, market_context, portfolio_health_score,
                position_reviews, strengths, concerns, opportunities,
                risk_factors, pipeline_guidance, apply_to_pipeline
            )
            VALUES (
                $1, CAST($2 AS UUID), $3, $4,
                $5, $6, $7, $8,
                CAST($9 AS JSONB), CAST($10 AS JSONB), CAST($11 AS JSONB), CAST($12 AS JSONB),
                CAST($13 AS JSONB), CAST($14 AS JSONB), $15
            )
            """,
            [
                review["review_id"],
                user_id,
                review["created_at"],
                review.get("portfolio_value"),
                review.get("overall_stance"),
                review.get("summary"),
                review.get("market_context"),
                review.get("portfolio_health_score"),
                json.dumps(review.get("position_reviews", [])),
                json.dumps(review.get("strengths", [])),
                json.dumps(review.get("concerns", [])),
                json.dumps(review.get("opportunities", [])),
                json.dumps(review.get("risk_factors", [])),
                json.dumps(review.get("pipeline_guidance", [])),
                review.get("apply_to_pipeline", False),
            ],
        )
    finally:
        con.close()


def load_review(user_id: str) -> dict | None:
    """Return the user's most recent analyst review, or None if none exists."""
    if not user_id:
        raise ValueError("user_id is required for load_review")
    con = get_connection()
    try:
        row = con.execute(
            """
            SELECT review_id, created_at, portfolio_value, overall_stance,
                   summary, market_context, portfolio_health_score,
                   position_reviews, strengths, concerns, opportunities,
                   risk_factors, pipeline_guidance, apply_to_pipeline
            FROM analyst_reviews
            WHERE user_id = CAST($1 AS UUID)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [user_id],
        ).fetchone()
    finally:
        con.close()

    if not row:
        return None

    cols = (
        "review_id", "created_at", "portfolio_value", "overall_stance",
        "summary", "market_context", "portfolio_health_score",
        "position_reviews", "strengths", "concerns", "opportunities",
        "risk_factors", "pipeline_guidance", "apply_to_pipeline",
    )
    out: dict = {}
    for col, val in zip(cols, row):
        if col == "created_at" and hasattr(val, "isoformat"):
            out[col] = val.isoformat()
        elif col in _JSONB_FIELDS and isinstance(val, str):
            # psycopg2 returns JSONB as already-parsed dict/list in most modes,
            # but fall back if we ever get a raw string.
            try:
                out[col] = json.loads(val)
            except Exception:
                out[col] = val
        else:
            out[col] = val
    return out


def set_apply_to_pipeline(apply: bool, user_id: str) -> dict:
    """Flip the apply flag on the user's latest analyst review."""
    if not user_id:
        raise ValueError("user_id is required for set_apply_to_pipeline")
    review = load_review(user_id)
    if not review:
        raise ValueError("No analyst review found for this user")

    con = get_connection()
    try:
        con.execute(
            "UPDATE analyst_reviews SET apply_to_pipeline = $1 "
            "WHERE review_id = $2 AND user_id = CAST($3 AS UUID)",
            [apply, review["review_id"], user_id],
        )
    finally:
        con.close()

    review["apply_to_pipeline"] = apply
    return review


def get_pipeline_guidance(user_id: str) -> str | None:
    """Return pipeline guidance text if the user's latest review is applied."""
    if not user_id:
        return None
    review = load_review(user_id)
    if not review or not review.get("apply_to_pipeline"):
        return None
    guidance = review.get("pipeline_guidance", [])
    if not guidance:
        return None
    created = (review.get("created_at") or "")[:10]
    lines = "\n".join(f"- {g}" for g in guidance)
    stance = (review.get("overall_stance") or "neutral").upper()
    return (
        f"## Analyst Review Guidance (from {created}, stance: {stance})\n"
        f"A senior quantitative analyst reviewed the portfolio and provided the following guidance "
        f"for this pipeline run. Factor this into your evaluation:\n{lines}"
    )
