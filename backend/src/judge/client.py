"""Claude API client for the LLM judge layer + SQLite logging."""

import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.state import load_universe_df
from src.judge.schema import (
    JudgeInput,
    JudgeOutput,
    EvaluationContext,
    ProposedTrade,
    SignalContext,
    FactorScores,
    ConstraintCheck,
    HistoricalContext,
    PastDecision,
    Verdict,
)
from src.judge.prompt import SYSTEM_PROMPT, JUDGE_PROMPT_TEMPLATE, STRATEGY_RULES_SUMMARY, HISTORICAL_CONTEXT_TEMPLATE, PORTFOLIO_REVIEW_PROMPT


def _get_user_notes_data() -> dict:
    """Get user notes data (text + images).

    After the multi-user migration, user_notes lives in a per-user Postgres
    table. The judge runs in the EOD pipeline (currently global), so it has
    no user_id to scope the lookup. Returns empty until the pipeline itself
    is refactored to be per-user — see the Part B follow-ups.
    """
    return {}


def _extract_json_from_llm(text: str):
    """Best-effort JSON extractor for LLM responses.

    The judge prompts explicitly request raw JSON, but Claude occasionally
    decorates the output with prose, markdown fences, or trailing commentary.
    We try progressively more aggressive recovery strategies before giving up:

    1. Direct parse of the stripped text (the happy path).
    2. Strip ``` fences (with or without language hint) regardless of
       whether they bracket the full message or just a portion of it.
    3. Locate the first ``{`` and find its bracket-balanced closing ``}``;
       parse just that slice. Handles "Here's my analysis: {...}" and
       trailing remarks. Also tries the first ``[`` for array-shaped
       responses.

    Raises ``json.JSONDecodeError`` from the last failed attempt so callers
    keep their existing exception handlers intact.
    """
    if text is None:
        raise json.JSONDecodeError("LLM returned None", "", 0)

    s = text.strip()
    if not s:
        raise json.JSONDecodeError("LLM returned empty string", "", 0)

    # Strategy 1: parse as-is.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip ``` fences if present anywhere.
    fence_match = re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", s, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: find first balanced { ... } or [ ... ] block.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(s)):
            c = s[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # try the other bracket type
                    break

    # Nothing worked — raise so the caller's except handler runs.
    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response (first 200 chars: {s[:200]!r})",
        s, 0,
    )


def _build_user_notes_section() -> str:
    """Build the text portion of user notes for the judge prompt."""
    notes = _get_user_notes_data()
    text = notes.get("text", "").strip()
    images = notes.get("images", [])
    if not text and not images:
        return ""
    preamble = (
        "\n\n## User-Provided Context\n"
        "The portfolio owner has provided the following notes/context for this pipeline run. "
        "Treat this as SUPPLEMENTARY information only. The user is a retail investor and their "
        "analysis may contain biases, incomplete information, or emotional reasoning.\n\n"
        "YOUR OBLIGATION: Evaluate these notes OBJECTIVELY. If the user's observations align with "
        "the quantitative data and news research, give them appropriate weight. If they contradict "
        "the data or appear to be driven by fear/greed/confirmation bias, note the disagreement "
        "and trust the quantitative signals instead. Never approve or reject a trade solely because "
        "the user wants it.\n\n"
    )
    parts = [preamble]
    if text:
        parts.append(f"User notes:\n{text}")
    if images:
        parts.append(f"\n[{len(images)} image(s) attached — see below]")
    return "".join(parts)


def _build_user_notes_image_blocks() -> list[dict]:
    """Build Claude API image content blocks from user-uploaded images.

    Returns list of dicts suitable for Claude's multimodal messages API:
    [{"type": "image", "source": {"type": "base64", ...}}, ...]
    """
    notes = _get_user_notes_data()
    images = notes.get("images", [])
    if not images:
        return []

    blocks = []
    for img in images[:5]:
        data = img.get("data", "")
        mime = img.get("mime", "image/png")
        if not data:
            continue
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": data,
            },
        })
    return blocks


def _backend() -> str:
    import os
    return (os.getenv("DB_BACKEND") or "duckdb").lower()


def _init_judge_log_db() -> None:
    """Create the judge log table.

    Postgres: table is provisioned by supabase/migrations/0003_judge_log.sql,
    so this is a no-op. SQLite: legacy DB at logs/judge_log.db.
    """
    if _backend() == "postgres":
        return  # provisioned by migration 0003

    db_path = settings.paths.judge_log_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS judge_log (
            log_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            input_payload TEXT NOT NULL,
            output_payload TEXT NOT NULL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL,
            model_used TEXT NOT NULL,
            input_hash TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def _log_judge_call(
    proposal_id: str,
    ticker: str,
    action: str,
    input_payload: str,
    output_payload: str,
    verdict: str,
    confidence: float,
    model_used: str,
    input_hash: str,
    user_id: str | None = None,
) -> None:
    """Persist a judge call to the audit log.

    Postgres path requires ``user_id`` because judge_log is per-user after the
    multi-user migration. Legacy SQLite path ignores user_id (single-user file).
    """
    _init_judge_log_db()

    log_id = str(uuid.uuid4())[:8]
    created_at = datetime.now().isoformat()

    if _backend() == "postgres":
        if not user_id:
            raise ValueError("user_id is required for judge_log inserts (per-user table)")
        from src.db.postgres import get_pg_connection
        # Postgres JSONB requires valid JSON. Some payloads (portfolio-review)
        # are plain text — wrap them as JSON strings so the column accepts them
        # while keeping the data round-trippable.
        def _to_jsonb(text):
            if text is None:
                return None
            try:
                json.loads(text)
                return text
            except (json.JSONDecodeError, TypeError):
                return json.dumps(text)

        conn = get_pg_connection(role="pooled")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO judge_log
                    (log_id, user_id, created_at, proposal_id, ticker, action,
                     input_payload, output_payload, verdict, confidence, model_used, input_hash)
                    VALUES (%s, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                """, (
                    log_id, user_id, created_at, proposal_id, ticker, action,
                    _to_jsonb(input_payload), _to_jsonb(output_payload),
                    verdict, confidence, model_used, input_hash,
                ))
            conn.commit()
        finally:
            conn.close()
        return

    con = sqlite3.connect(str(settings.paths.judge_log_path))
    con.execute("""
        INSERT INTO judge_log
        (log_id, created_at, proposal_id, ticker, action,
         input_payload, output_payload, verdict, confidence, model_used, input_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        log_id, created_at, proposal_id, ticker, action,
        input_payload, output_payload, verdict, confidence, model_used, input_hash,
    ])
    con.commit()
    con.close()


def build_judge_input(proposal: dict, portfolio_value: float, pnl: dict) -> JudgeInput:
    """Convert a trade proposal dict into a structured JudgeInput."""
    signal_data = proposal.get("signal_data", {})
    factor_data = signal_data.get("factors", {})

    cash_pct = pnl.get("cash", 0) / portfolio_value * 100 if portfolio_value > 0 else 0
    drawdown = pnl.get("total_return_pct", 0) * 100 if pnl.get("total_return_pct", 0) < 0 else 0

    return JudgeInput(
        evaluation_context=EvaluationContext(
            date=datetime.now().strftime("%Y-%m-%d"),
            portfolio_value_usd=portfolio_value,
            portfolio_drawdown_from_peak_pct=drawdown,
            cash_pct=cash_pct,
        ),
        proposed_trade=ProposedTrade(
            ticker=proposal["ticker"],
            action=proposal["action"],
            proposed_shares=proposal.get("shares", 0),
            current_weight_pct=proposal.get("current_weight", 0) * 100,
            proposed_weight_pct=proposal.get("target_weight", 0) * 100,
            estimated_cost_usd=proposal.get("estimated_value", 0),
        ),
        signal_context=SignalContext(
            composite_score=signal_data.get("composite_score", 0),
            score_decile=signal_data.get("decile", 5),
            prior_decile=proposal.get("prior_decile", 5),
            factor_scores=FactorScores(**{
                k: factor_data.get(k)
                for k in ["momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy",
                           "gross_margin_trend", "relative_valuation"]
            }),
            reason=proposal.get("reason", ""),
        ),
        constraint_check=ConstraintCheck(
            passes_all_constraints=proposal.get("constraint_check", {}).get("passed", True),
            violations=proposal.get("constraint_check", {}).get("violations", []),
        ),
        strategy_rules_summary=STRATEGY_RULES_SUMMARY,
    )


def _build_historical_section(proposal: dict) -> str:
    """Build the historical context section for the judge prompt."""
    try:
        from src.learning.pattern_detector import find_similar_decisions, get_patterns, get_alerts

        ticker = proposal["ticker"]
        signal_data = proposal.get("signal_data", {})
        score_decile = signal_data.get("decile", 5)

        # Load universe for sub_sector lookup
        import pandas as pd
        universe = load_universe_df()
        sub_sector_row = universe.loc[universe["ticker"] == ticker, "sub_sector"]
        sub_sector = sub_sector_row.iloc[0] if not sub_sector_row.empty else None

        similar = find_similar_decisions(ticker, score_decile, sub_sector, limit=5)
        patterns = get_patterns()
        alerts = get_alerts()

        if not similar and not patterns:
            return ""

        # Format similar decisions
        similar_lines = []
        for d in similar:
            outcome = d.get("outcome_1m", "pending")
            excess = d.get("excess_return_1m")
            excess_str = f"{excess:+.1%}" if excess is not None else "n/a"
            similar_lines.append(
                f"- {d['ticker']} {d['action']} on {d.get('decision_date', '?')}: "
                f"decile {d.get('score_decile', '?')}, outcome={outcome}, excess 1m={excess_str}"
            )

        # Find overall and sector win rates from patterns
        overall_wr = "n/a"
        sector_wr = "n/a"
        for p in patterns:
            if p["dimension"] == "overall":
                overall_wr = f"{p['win_rate']:.0%}" if p.get("win_rate") is not None else "n/a"
            if p["dimension"] == "sub_sector" and p["dimension_value"] == sub_sector:
                sector_wr = f"{p['win_rate']:.0%}" if p.get("win_rate") is not None else "n/a"

        alert_lines = [a.get("alert_message", "") for a in alerts if a.get("alert_message")]
        alerts_section = ""
        if alert_lines:
            alerts_section = "Pattern alerts:\n" + "\n".join(f"- {a}" for a in alert_lines)

        return HISTORICAL_CONTEXT_TEMPLATE.format(
            overall_win_rate=overall_wr,
            sector_name=sub_sector or "unknown",
            sector_win_rate=sector_wr,
            similar_decisions="\n".join(similar_lines) if similar_lines else "No similar past decisions found.",
            alerts_section=alerts_section,
        )
    except Exception:
        # Don't fail the judge evaluation if learning module has issues
        return ""


def evaluate_proposal(
    proposal: dict,
    portfolio_value: float,
    pnl: dict,
    news=None,
    sector_intel: dict | None = None,
    risk_level: int = 3,
    user_id: str | None = None,
) -> JudgeOutput:
    """Send a trade proposal to Claude for evaluation.

    Args:
        news: Optional NewsResearch object with recent news context.
        sector_intel: Optional competitive intelligence from competitive_intel.py.
        risk_level: Aggressiveness setting (1=conservative, 5=aggressive).
        user_id: Supabase UUID — required when DB_BACKEND=postgres because
                 judge_log is per-user.

    Returns a validated JudgeOutput.
    """
    judge_input = build_judge_input(proposal, portfolio_value, pnl)
    input_json = judge_input.model_dump_json(indent=2)
    input_hash = hashlib.sha256(input_json.encode()).hexdigest()[:16]

    # Build historical context section from self-learning data
    historical_section = _build_historical_section(proposal)

    # Build price & technical context
    price_section = ""
    try:
        from src.judge.market_context import get_price_context, format_price_section
        price_ctx = get_price_context(proposal["ticker"])
        if price_ctx:
            price_section = "\n\n## Price & Technical Context\n" + format_price_section(price_ctx)
    except Exception:
        pass

    # Build market regime section if available
    regime = proposal.get("market_regime", {})
    regime_section = ""
    if regime:
        vol = regime.get("vol_regime", "unknown")
        rvol = regime.get("realized_vol", 0)
        mom = regime.get("momentum_regime", "unknown")
        mom_21d = regime.get("momentum_21d", 0)
        regime_section = (
            f"\n\n## Market Regime\n"
            f"Volatility: {vol} (realized: {rvol:.1%})\n"
            f"Trend: {mom} (21d momentum: {mom_21d:.1%})\n"
            f"Consider: In HIGH volatility or BEAR trends, the bar for approving new trades should be higher. "
            f"Holding existing positions is often the safer choice in turbulent markets."
        )
    price_section += regime_section

    # Build news context section
    news_section = ""
    if news and news.ai_summary and news.confidence > 0:
        news_section = f"""

## Recent News Context
Ticker: {news.ticker}
Summary: {news.ai_summary}
Sentiment: {news.sentiment}
Risk factors: {', '.join(news.risk_factors) if news.risk_factors else 'None identified'}
Opportunities: {', '.join(news.opportunities) if news.opportunities else 'None identified'}
Binary events: {', '.join(e.description for e in news.binary_events) if news.binary_events else 'None upcoming'}

Consider this news context when evaluating. If a binary event (earnings, regulatory) is within 7 days, set binary_event_warning=true."""

    # Inject analyst guidance if one is marked to apply
    analyst_section = ""
    try:
        from src.analyst.review import get_pipeline_guidance
        guidance = get_pipeline_guidance()
        if guidance:
            analyst_section = f"\n\n{guidance}"
    except Exception:
        pass

    # Inject user notes (with objectivity framing)
    user_notes_section = _build_user_notes_section()

    # Build trade history section if available
    trade_history_section = ""
    recent_history = proposal.get("recent_trade_history", [])
    if recent_history:
        trade_history_section = (
            "\n\n## Recent Trade History (Anti-Whipsaw Context)\n"
            f"This ticker ({proposal['ticker']}) has been traded recently:\n"
            + "\n".join(f"- {h}" for h in recent_history)
            + "\nIMPORTANT: If this stock was bought recently and is now being proposed for sale, "
            "this is a whipsaw signal and should be REJECTED unless there is overwhelming evidence "
            "of a fundamental change (e.g., fraud, delisting, catastrophic earnings miss). "
            "Short-term score fluctuations are not sufficient reason to reverse a recent trade."
        )

    # Build sector intelligence section
    sector_intel_section = ""
    if sector_intel and sector_intel.get("competitive_dynamics"):
        si_parts = ["\n\n## Sector Intelligence"]
        si_parts.append(f"Sub-sector: {sector_intel.get('sub_sector', 'unknown')}")
        si_parts.append(f"Peers analyzed: {', '.join(sector_intel.get('peers_analyzed', []))}")
        si_parts.append(f"Sector sentiment: {sector_intel.get('sector_sentiment', 'unknown')}")
        si_parts.append(f"\nCompetitive dynamics: {sector_intel['competitive_dynamics']}")

        themes = sector_intel.get("key_themes", [])
        if themes:
            si_parts.append(f"Key themes: {', '.join(themes)}")

        spillover = sector_intel.get("earnings_spillover", [])
        if spillover:
            si_parts.append("\nRecent peer earnings:")
            for s in spillover[:5]:
                si_parts.append(f"  {s['peer_ticker']}: {s['event_type']} ({s['sentiment']}) — {s['summary']}")

        fc = sector_intel.get("fundamental_comparison", {})
        if fc:
            si_parts.append(f"\nFundamental positioning vs peers:")
            si_parts.append(f"  Margins: {fc.get('margin_vs_peers', 'unknown')}")
            si_parts.append(f"  Growth: {fc.get('growth_vs_peers', 'unknown')}")
            si_parts.append(f"  Valuation: {fc.get('valuation_vs_peers', 'unknown')}")

        si_parts.append(
            "\nConsider how sector trends, peer earnings, and competitive positioning "
            "affect the risk/reward profile of this trade."
        )
        sector_intel_section = "\n".join(si_parts)

    # Build earnings timing section
    earnings_timing_section = ""
    try:
        from src.ingest.earnings_calendar import get_upcoming_earnings
        upcoming = get_upcoming_earnings([proposal["ticker"]], days_ahead=14)
        if proposal["ticker"] in upcoming:
            e = upcoming[proposal["ticker"]]
            days_until = e["days_until"]
            event_date = e["event_date"]
            eps_est = e.get("eps_estimate")
            eps_str = f"${eps_est:.2f}" if eps_est else "unknown"
            earnings_timing_section = (
                f"\n\n## Earnings Timing Warning"
                f"\n{proposal['ticker']} reports earnings on {event_date} ({days_until} day(s) away)."
                f"\nConsensus EPS estimate: {eps_str}"
            )
            if days_until <= 2:
                earnings_timing_section += (
                    "\n\nCRITICAL: Earnings are IMMINENT. This is a binary event with high uncertainty. "
                    "Unless the quantitative case is overwhelming, set binary_event_warning=true "
                    "and consider whether pre-earnings risk justifies this trade."
                )
            elif days_until <= 7:
                earnings_timing_section += (
                    "\n\nNOTE: Earnings are within a week. Factor in the elevated uncertainty. "
                    "Set binary_event_warning=true if this event could significantly alter the thesis."
                )
    except Exception:
        pass

    # Build risk level instruction
    risk_instructions = {
        1: (
            "\n\n## Risk Posture: CONSERVATIVE (Level 1)"
            "\nBe very conservative. Reject trades with even moderate risk factors. "
            "Require overwhelming quantitative evidence for approval. Flag any uncertainty."
        ),
        2: (
            "\n\n## Risk Posture: CAUTIOUS (Level 2)"
            "\nFavor caution. Require strong quantitative support and manageable risk profile."
        ),
        4: (
            "\n\n## Risk Posture: GROWTH-ORIENTED (Level 4)"
            "\nAccept trades with moderate risk when supported by strong momentum or fundamentals. "
            "Tolerate higher concentration and near-term volatility."
        ),
        5: (
            "\n\n## Risk Posture: AGGRESSIVE (Level 5)"
            "\nTolerate higher risk for higher return potential. Accept higher concentration, "
            "momentum-driven trades, and trades near binary events if the setup is strong. "
            "Only reject when risk is extreme or the quantitative case is clearly negative."
        ),
    }
    risk_section = risk_instructions.get(risk_level, "")

    prompt = JUDGE_PROMPT_TEMPLATE.format(
        proposal_json=input_json,
        strategy_rules=STRATEGY_RULES_SUMMARY,
        historical_section=historical_section,
    ) + price_section + news_section + trade_history_section + sector_intel_section + earnings_timing_section + risk_section + analyst_section + user_notes_section

    # Build message content — multimodal if user uploaded images
    image_blocks = _build_user_notes_image_blocks()
    if image_blocks:
        message_content = [{"type": "text", "text": prompt}] + image_blocks
    else:
        message_content = prompt

    model = settings.judge.model
    client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)

    try:
        # max_tokens raised from 1024 to 4096 because the JudgeOutput schema
        # (verdict + reasons + violated_rules + risk_flags + follow_up_checks
        # + data_quality_concerns) routinely needs >1500 tokens of natural-
        # language reasoning. At 1024 Claude was getting cut off mid-string
        # and the response failed JSON parsing with "Unterminated string".
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=settings.judge.temperature,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message_content}],
        )

        raw_text = response.content[0].text.strip()
        # If Claude hit the token ceiling, surface that as the parse error
        # instead of letting the JSON decoder complain about a truncated
        # string — far easier to act on.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            raise json.JSONDecodeError(
                f"Judge response truncated at max_tokens=4096 (stop_reason=max_tokens). "
                f"Bump max_tokens or shorten prompts.",
                raw_text, len(raw_text),
            )

        result = _extract_json_from_llm(raw_text)

        output = JudgeOutput(
            verdict=result.get("verdict", "needs_review"),
            confidence=result.get("confidence", 0.5),
            reasons=result.get("reasons", []),
            violated_rules=result.get("violated_rules", []),
            risk_flags=result.get("risk_flags", []),
            follow_up_checks=result.get("follow_up_checks", []),
            binary_event_warning=result.get("binary_event_warning", False),
            data_quality_concerns=result.get("data_quality_concerns", []),
            judge_model=model,
            evaluation_timestamp=datetime.now().isoformat(),
            input_hash=input_hash,
        )

    except (json.JSONDecodeError, KeyError, Exception) as e:
        # Capture a snippet of the raw response so recurring parse failures
        # are debuggable instead of opaque.
        try:
            raw_snippet = raw_text[:300] if "raw_text" in locals() else "<no response captured>"
        except Exception:
            raw_snippet = "<no response captured>"
        output = JudgeOutput(
            verdict=Verdict.NEEDS_REVIEW,
            confidence=0.0,
            reasons=[f"Judge parse error: {str(e)}"],
            risk_flags=[f"LLM response was not valid JSON. First 300 chars: {raw_snippet}"],
            judge_model=model,
            evaluation_timestamp=datetime.now().isoformat(),
            input_hash=input_hash,
        )

    # Log to SQLite (immutable audit trail)
    _log_judge_call(
        proposal_id=proposal.get("proposal_id", "unknown"),
        ticker=proposal["ticker"],
        action=proposal["action"],
        input_payload=input_json,
        output_payload=output.model_dump_json(),
        verdict=output.verdict.value,
        confidence=output.confidence,
        model_used=model,
        input_hash=input_hash,
        user_id=user_id,
    )

    return output


def evaluate_all_proposals(
    proposals: list[dict],
    portfolio_value: float,
    pnl: dict,
    research_map: dict | None = None,
    recent_trades: list[dict] | None = None,
    sector_intel_map: dict | None = None,
    risk_level: int = 3,
    user_id: str | None = None,
) -> list[tuple[dict, JudgeOutput]]:
    """Evaluate all proposals through the LLM judge.

    Args:
        research_map: Optional dict of ticker -> NewsResearch objects.
        recent_trades: Recent executed trades for anti-whipsaw context.
        sector_intel_map: Optional dict of ticker -> sector intelligence.
        risk_level: Aggressiveness setting (1=conservative, 5=aggressive).

    Returns list of (proposal, judge_output) tuples.
    """
    research_map = research_map or {}
    recent_trades = recent_trades or []
    sector_intel_map = sector_intel_map or {}

    # Build per-ticker trade history summary for judge context
    _trade_history: dict[str, list[str]] = {}
    for t in recent_trades:
        ticker = t["ticker"]
        if ticker not in _trade_history:
            _trade_history[ticker] = []
        executed = t["executed_at"]
        if isinstance(executed, str):
            date_str = executed[:10]
        else:
            date_str = executed.strftime("%Y-%m-%d") if hasattr(executed, "strftime") else str(executed)[:10]
        _trade_history[ticker].append(f"{t['action']} {t['shares']} shares on {date_str}")

    # Pre-process: attach trade history and filter
    eligible = []
    for p in proposals:
        if not p.get("constraint_check", {}).get("passed", True):
            continue
        ticker_history = _trade_history.get(p["ticker"], [])
        if ticker_history:
            p["recent_trade_history"] = ticker_history
        eligible.append(p)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import logging
    _log = logging.getLogger("trademark")

    def _judge_one(p: dict) -> tuple[dict, JudgeOutput]:
        _log.info(f"  Evaluating: {p['action']} {p.get('shares', 0)} {p['ticker']}...")
        news = research_map.get(p["ticker"])
        intel = sector_intel_map.get(p["ticker"])
        output = evaluate_proposal(p, portfolio_value, pnl, news=news, sector_intel=intel, risk_level=risk_level, user_id=user_id)
        _log.info(f"    {p['ticker']}: {output.verdict.value} ({output.confidence:.0%})")

        p["judge_verdict"] = output.verdict.value
        p["judge_confidence"] = output.confidence
        p["judge_reasons"] = output.reasons
        p["judge_risk_flags"] = output.risk_flags

        if output.verdict == Verdict.APPROVE:
            p["status"] = "JUDGE_APPROVED"
        elif output.verdict == Verdict.REJECT:
            p["status"] = "JUDGE_REJECTED"
        else:
            p["status"] = "NEEDS_REVIEW"

        return (p, output)

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_judge_one, p): p for p in eligible}
        for future in as_completed(futures):
            results.append(future.result())

    return results


def evaluate_portfolio_review(
    portfolio: dict,
    scores_df,
    pnl: dict,
    portfolio_value: float,
    research_map: dict | None = None,
    regime: dict | None = None,
    user_id: str | None = None,
) -> dict:
    """Run a full portfolio review even when no trades are proposed.

    The judge evaluates all holdings, top-scoring stocks, and the overall
    portfolio to decide whether it agrees with the model's HOLD decision
    or thinks trades should be made.

    Returns the parsed judge response dict.
    """
    import pandas as pd

    research_map = research_map or {}

    # Build portfolio summary
    cash = portfolio.get("cash", 0)
    cash_pct = (cash / portfolio_value * 100) if portfolio_value > 0 else 0
    portfolio_summary = {
        "cash": cash,
        "cash_pct_of_portfolio": round(cash_pct, 1),
        "total_portfolio_value": round(portfolio_value, 2),
        "positions": [],
    }
    for pos in portfolio.get("positions", []):
        portfolio_summary["positions"].append({
            "ticker": pos["ticker"],
            "shares": pos["shares"],
            "cost_basis": pos.get("cost_basis_per_share", 0),
        })

    # Build scores summary: current holdings + top 10 by composite score
    scores_summary = []
    if scores_df is not None and not scores_df.empty:
        held_tickers = {pos["ticker"] for pos in portfolio.get("positions", [])}
        top10 = scores_df.head(10)
        held_scores = scores_df[scores_df["ticker"].isin(held_tickers)]
        combined = pd.concat([top10, held_scores]).drop_duplicates(subset="ticker")

        for _, row in combined.iterrows():
            entry = {
                "ticker": row.get("ticker", ""),
                "composite_score": round(row.get("composite_score", 0), 3),
                "decile": int(row.get("score_decile", 5)),
                "in_portfolio": row.get("ticker", "") in held_tickers,
            }
            # Add individual factors if available
            for col in ["momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy",
                        "gross_margin_trend", "relative_valuation"]:
                if col in row and pd.notna(row[col]):
                    entry[col] = round(float(row[col]), 3)
            scores_summary.append(entry)

    # Build news summary
    news_summary = []
    for ticker, research in research_map.items():
        if research and hasattr(research, "ai_summary") and research.ai_summary:
            news_summary.append({
                "ticker": ticker,
                "sentiment": research.sentiment,
                "summary": research.ai_summary[:300],
                "risk_factors": research.risk_factors[:3] if research.risk_factors else [],
            })

    # Build historical context
    historical_section = ""
    try:
        from src.learning.pattern_detector import get_patterns, get_alerts
        patterns = get_patterns()
        alerts = get_alerts()

        overall_wr = "n/a"
        for p in patterns:
            if p["dimension"] == "overall" and p.get("win_rate") is not None:
                overall_wr = f"{p['win_rate']:.0%}"

        alert_lines = [a.get("alert_message", "") for a in alerts if a.get("alert_message")]
        if overall_wr != "n/a" or alert_lines:
            historical_section = f"\n## Historical Context\nOverall win rate: {overall_wr}\n"
            if alert_lines:
                historical_section += "Alerts:\n" + "\n".join(f"- {a}" for a in alert_lines)
    except Exception:
        pass

    # Build price & technical context for all tickers
    price_section = ""
    try:
        from src.judge.market_context import get_batch_price_context, format_portfolio_price_section
        all_review_tickers = list(set(
            [pos["ticker"] for pos in portfolio.get("positions", [])]
            + [s["ticker"] for s in scores_summary[:10]]
        ))
        price_contexts = get_batch_price_context(all_review_tickers)
        if price_contexts:
            price_section = "\n" + format_portfolio_price_section(price_contexts)
    except Exception:
        pass

    # Inject analyst guidance if one is marked to apply
    analyst_section = ""
    try:
        from src.analyst.review import get_pipeline_guidance
        guidance = get_pipeline_guidance()
        if guidance:
            analyst_section = f"\n\n{guidance}"
    except Exception:
        pass

    # Inject user notes (with objectivity framing)
    user_notes_section = _build_user_notes_section()

    # Build the prompt
    prompt = PORTFOLIO_REVIEW_PROMPT.format(
        portfolio_json=json.dumps(portfolio_summary, indent=2),
        scores_json=json.dumps(scores_summary, indent=2),
        regime_json=json.dumps(regime or {}, indent=2),
        news_json=json.dumps(news_summary, indent=2),
        price_section=price_section,
        historical_section=historical_section,
        strategy_rules=STRATEGY_RULES_SUMMARY,
    )

    # Build message content — multimodal if user uploaded images
    review_prompt = prompt + analyst_section + user_notes_section
    image_blocks = _build_user_notes_image_blocks()
    if image_blocks:
        review_content = [{"type": "text", "text": review_prompt}] + image_blocks
    else:
        review_content = review_prompt

    model = settings.judge.model
    client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=settings.judge.temperature,
            system="You are a systematic trading portfolio reviewer. Evaluate the entire portfolio and provide actionable feedback. Be decisive — agree or disagree with clear reasoning.",
            messages=[{"role": "user", "content": review_content}],
        )

        raw_text = response.content[0].text.strip()
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            raise json.JSONDecodeError(
                f"Portfolio review truncated at max_tokens=4096 (stop_reason=max_tokens). "
                f"Consider bumping max_tokens for portfolios with many positions.",
                raw_text, len(raw_text),
            )
        result = _extract_json_from_llm(raw_text)

    except (json.JSONDecodeError, Exception) as e:
        # Log the raw response so we can debug recurring parse failures
        # rather than just losing the data behind a generic error message.
        try:
            raw_snippet = (raw_text[:300] if "raw_text" in locals() else "<no response captured>")
        except Exception:
            raw_snippet = "<no response captured>"
        result = {
            "overall_verdict": "agree",
            "confidence": 0.0,
            "market_assessment": f"Judge parse error: {e}",
            "holdings_review": [],
            "missed_opportunities": [],
            "risk_flags": [f"LLM response parsing failed. First 300 chars: {raw_snippet}"],
            "recommendations": [],
        }

    # Log to audit trail
    _log_judge_call(
        proposal_id="portfolio-review",
        ticker="PORTFOLIO",
        action="REVIEW",
        input_payload=prompt[:5000],
        output_payload=json.dumps(result, default=str),
        verdict=result.get("overall_verdict", "agree"),
        confidence=result.get("confidence", 0),
        model_used=model,
        input_hash=hashlib.sha256(prompt.encode()).hexdigest()[:16],
        user_id=user_id,
    )

    return result


def get_judge_log(limit: int = 50) -> list[dict]:
    """Retrieve recent judge log entries from Postgres or SQLite."""
    _init_judge_log_db()

    if _backend() == "postgres":
        from src.db.postgres import get_pg_connection
        conn = get_pg_connection(role="pooled")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT log_id, created_at, proposal_id, ticker, action, "
                    "input_payload, output_payload, verdict, confidence, model_used, input_hash "
                    "FROM judge_log ORDER BY created_at DESC LIMIT %s",
                    [limit],
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                return [
                    {
                        col: (
                            v.isoformat() if hasattr(v, "isoformat") else
                            json.dumps(v) if col in ("input_payload", "output_payload") and isinstance(v, dict) else
                            v
                        )
                        for col, v in zip(cols, row)
                    }
                    for row in rows
                ]
        finally:
            conn.close()

    con = sqlite3.connect(str(settings.paths.judge_log_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM judge_log ORDER BY created_at DESC LIMIT ?", [limit]
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
