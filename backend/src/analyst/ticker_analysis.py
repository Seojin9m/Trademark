"""Single-ticker AI analysis: instant recommendation for ANY publicly traded ticker.

Supports both universe tickers (uses cached data) and out-of-universe tickers
(fetches data on demand). Combines factor scores, news, earnings timing,
competitive intelligence, and price context into a structured Claude analysis.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

logger = logging.getLogger("trademark.analyst")

TICKER_ANALYSIS_SYSTEM = """You are a senior equity research analyst. Given comprehensive data about a single stock — fundamentals, technicals, news, competitive positioning, and earnings timing — produce a structured investment recommendation.

Your analysis must be:
- Data-driven: cite specific numbers from the provided data
- Balanced: always present both bull and bear cases
- Honest about uncertainty: if data is thin, say so
- Risk-aware: the user has real money at stake

You must NOT:
- Guarantee returns or make price targets
- Ignore negative signals to paint a rosy picture
- Recommend based on hype or narrative alone

Return ONLY valid JSON (no markdown fences)."""

RISK_LEVEL_INSTRUCTIONS = {
    1: "The investor is VERY CONSERVATIVE. Only recommend BUY for stocks with exceptional fundamentals, minimal risk, and strong defensive qualities. Default to HOLD unless the case is overwhelming.",
    2: "The investor is CAUTIOUS. Require strong fundamentals and manageable risk for a BUY recommendation.",
    3: "The investor has a BALANCED risk appetite. Weigh risk and reward evenly. Standard analysis criteria.",
    4: "The investor is GROWTH-ORIENTED. Willing to accept moderate risk for higher return potential. Momentum and growth factors carry extra weight.",
    5: "The investor is AGGRESSIVE. Tolerant of significant risk for outsized returns. Momentum plays, pre-earnings bets, and higher concentration are acceptable if the setup is strong.",
}


def analyze_single_ticker(ticker: str, risk_level: int = 3) -> dict:
    """Run full AI analysis for a single ticker.

    Works for any publicly traded stock — uses cached data for universe tickers,
    fetches on demand for out-of-universe tickers.
    """
    ticker = ticker.upper()
    today = datetime.now().strftime("%Y-%m-%d")
    risk_level = max(1, min(5, risk_level))

    logger.info(f"Starting single-ticker analysis for {ticker} (risk_level={risk_level})")

    # 1. Resolve metadata
    metadata = _resolve_metadata(ticker)

    # 2. Get factor scores (cached or computed)
    scores = _get_scores(ticker)

    # 3. Fetch + cache news
    news_data = _get_news(ticker)

    # 4. Earnings timing
    earnings = _get_earnings(ticker)

    # 5. Competitive intelligence
    sector_intel = _get_sector_intel(ticker, metadata.get("sub_sector"))

    # 6. Price context
    price_ctx = _get_price_context(ticker)

    # 7. Build prompt and call Claude
    prompt = _build_analysis_prompt(
        ticker=ticker,
        metadata=metadata,
        scores=scores,
        news_data=news_data,
        earnings=earnings,
        sector_intel=sector_intel,
        price_ctx=price_ctx,
        risk_level=risk_level,
        today=today,
    )

    result = _call_claude(prompt, risk_level)

    result["ticker"] = ticker
    result["analysis_date"] = today
    result["risk_level"] = risk_level
    result["metadata"] = metadata

    logger.info(f"Analysis complete for {ticker}: {result.get('recommendation', 'N/A')} "
                f"(confidence: {result.get('confidence', 0):.0%})")

    return result


def _resolve_metadata(ticker: str) -> dict:
    """Check if ticker is in universe; if not, resolve via yfinance."""
    try:
        universe = pd.read_csv(settings.paths.universe_path)
        match = universe[universe["ticker"] == ticker]
        if not match.empty:
            row = match.iloc[0]
            return {
                "name": row.get("name", ""),
                "sub_sector": row.get("sub_sector", ""),
                "market_cap_tier": row.get("market_cap_tier", ""),
                "in_universe": True,
            }
    except Exception:
        pass

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return {
            "name": info.get("longName", info.get("shortName", ticker)),
            "sub_sector": info.get("industry", ""),
            "market_cap_tier": _classify_market_cap(info.get("marketCap", 0)),
            "in_universe": False,
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
        }
    except Exception:
        return {
            "name": ticker,
            "sub_sector": "",
            "market_cap_tier": "",
            "in_universe": False,
        }


def _classify_market_cap(market_cap: int) -> str:
    if market_cap >= 200_000_000_000:
        return "mega"
    elif market_cap >= 10_000_000_000:
        return "large"
    elif market_cap >= 2_000_000_000:
        return "mid"
    elif market_cap >= 300_000_000:
        return "small"
    return "micro"


def _get_scores(ticker: str) -> dict:
    """Get latest factor scores from DB, or return empty."""
    try:
        con = get_connection()
        row = con.execute("""
            SELECT composite_score, score_decile, is_good_stock,
                   momentum_12m1m, eps_growth_yoy, revenue_growth_yoy,
                   gross_margin_trend, relative_valuation,
                   quality_score, recent_price_change, price_dip_score
            FROM factor_scores
            WHERE ticker = $1
            ORDER BY date DESC
            LIMIT 1
        """, [ticker]).fetchone()
        con.close()

        if row:
            return {
                "composite_score": round(float(row[0]), 3) if row[0] is not None else None,
                "score_decile": int(row[1]) if row[1] is not None else None,
                "is_good_stock": bool(row[2]) if row[2] is not None else None,
                "momentum_12m1m": round(float(row[3]), 3) if row[3] is not None else None,
                "eps_growth_yoy": round(float(row[4]), 3) if row[4] is not None else None,
                "revenue_growth_yoy": round(float(row[5]), 3) if row[5] is not None else None,
                "gross_margin_trend": round(float(row[6]), 3) if row[6] is not None else None,
                "relative_valuation": round(float(row[7]), 3) if row[7] is not None else None,
                "quality_score": round(float(row[8]), 3) if row[8] is not None else None,
                "recent_price_change": round(float(row[9]), 3) if row[9] is not None else None,
                "price_dip_score": round(float(row[10]), 3) if row[10] is not None else None,
            }
    except Exception as e:
        logger.debug(f"Score lookup failed for {ticker}: {e}")

    return {}


def _get_news(ticker: str) -> dict:
    """Fetch live news + cached historical articles."""
    articles = []
    summary = None

    try:
        from src.research.news_agent import search_ticker_news, get_cached_news
        live = search_ticker_news(ticker, max_results=10)
        cached = get_cached_news(ticker, days=30)

        existing_urls = {a.get("url") for a in live}
        all_articles = list(live)
        for ca in cached:
            if ca.get("url") not in existing_urls:
                all_articles.append(ca)

        articles = all_articles[:15]
    except Exception as e:
        logger.debug(f"News fetch failed for {ticker}: {e}")

    try:
        con = get_connection()
        row = con.execute("""
            SELECT ai_summary, sentiment, risk_factors, opportunities, confidence
            FROM news_research
            WHERE ticker = $1
            ORDER BY research_date DESC
            LIMIT 1
        """, [ticker]).fetchone()
        con.close()

        if row:
            summary = {
                "ai_summary": row[0],
                "sentiment": row[1],
                "risk_factors": json.loads(row[2]) if row[2] else [],
                "opportunities": json.loads(row[3]) if row[3] else [],
                "confidence": float(row[4]) if row[4] is not None else 0,
            }
    except Exception:
        pass

    return {
        "articles": articles,
        "summary": summary,
    }


def _get_earnings(ticker: str) -> dict:
    """Get upcoming and recent earnings data."""
    result = {}
    try:
        from src.ingest.earnings_calendar import get_upcoming_earnings, get_recent_earnings_surprises
        upcoming = get_upcoming_earnings([ticker], days_ahead=30)
        if ticker in upcoming:
            result["upcoming"] = upcoming[ticker]

        recent = get_recent_earnings_surprises([ticker], days_back=90)
        if recent:
            result["recent_surprises"] = recent[:3]
    except Exception as e:
        logger.debug(f"Earnings lookup failed for {ticker}: {e}")

    return result


def _get_sector_intel(ticker: str, sub_sector: str | None) -> dict:
    """Get competitive intelligence if we can identify peers."""
    try:
        from src.research.competitive_intel import get_full_sector_intelligence
        intel = get_full_sector_intelligence(ticker, sub_sector)
        return intel
    except Exception as e:
        logger.debug(f"Sector intel failed for {ticker}: {e}")
        return {}


def _get_price_context(ticker: str) -> dict:
    """Get price and technical context."""
    try:
        from src.judge.market_context import get_price_context
        ctx = get_price_context(ticker)
        return ctx or {}
    except Exception as e:
        logger.debug(f"Price context failed for {ticker}: {e}")
        return {}


def _build_analysis_prompt(
    ticker: str,
    metadata: dict,
    scores: dict,
    news_data: dict,
    earnings: dict,
    sector_intel: dict,
    price_ctx: dict,
    risk_level: int,
    today: str,
) -> str:
    """Build the full analysis prompt for Claude."""
    sections = []

    sections.append(f"Analyze {ticker} ({metadata.get('name', ticker)}) as of {today}.")
    sections.append(f"Sector/Industry: {metadata.get('sub_sector', 'unknown')}")
    sections.append(f"Market cap tier: {metadata.get('market_cap_tier', 'unknown')}")
    sections.append(f"In portfolio universe: {'Yes' if metadata.get('in_universe') else 'No'}")

    # Risk level instruction
    sections.append(f"\n## Investor Risk Profile\n{RISK_LEVEL_INSTRUCTIONS[risk_level]}")

    # Factor scores
    if scores:
        sections.append("\n## Quantitative Factor Scores")
        sections.append(f"Composite score: {scores.get('composite_score', 'N/A')}")
        sections.append(f"Score decile: {scores.get('score_decile', 'N/A')} (10=best)")
        sections.append(f"Good stock (quality gate): {scores.get('is_good_stock', 'N/A')}")
        sections.append(f"Quality score: {scores.get('quality_score', 'N/A')}")
        sections.append(f"Momentum (12m-1m): {scores.get('momentum_12m1m', 'N/A')}")
        sections.append(f"EPS growth YoY: {scores.get('eps_growth_yoy', 'N/A')}")
        sections.append(f"Revenue growth YoY: {scores.get('revenue_growth_yoy', 'N/A')}")
        sections.append(f"Gross margin trend: {scores.get('gross_margin_trend', 'N/A')}")
        sections.append(f"Relative valuation: {scores.get('relative_valuation', 'N/A')}")
        sections.append(f"Recent price change: {scores.get('recent_price_change', 'N/A')}")
    else:
        sections.append("\n## Quantitative Factor Scores\nNo scored data available — this ticker may be outside the scored universe.")

    # Price context
    if price_ctx:
        sections.append("\n## Price & Technical Context")
        if "current_price" in price_ctx:
            sections.append(f"Current price: ${price_ctx['current_price']:.2f}")
        if "sma_20" in price_ctx:
            sections.append(f"SMA 20: ${price_ctx['sma_20']:.2f}")
        if "sma_50" in price_ctx:
            sections.append(f"SMA 50: ${price_ctx['sma_50']:.2f}")
        if "sma_200" in price_ctx:
            sections.append(f"SMA 200: ${price_ctx['sma_200']:.2f}")
        if "rsi_14" in price_ctx:
            sections.append(f"RSI 14: {price_ctx['rsi_14']:.1f}")
        if "atr_pct" in price_ctx:
            sections.append(f"ATR %: {price_ctx['atr_pct']:.2%}")
        if "distance_from_52w_high" in price_ctx:
            sections.append(f"Distance from 52w high: {price_ctx['distance_from_52w_high']:.1%}")
        if "volume_ratio" in price_ctx:
            sections.append(f"Volume vs avg: {price_ctx['volume_ratio']:.1f}x")

    # News
    articles = news_data.get("articles", [])
    summary = news_data.get("summary")
    if summary:
        sections.append("\n## News Research Summary")
        sections.append(f"Sentiment: {summary['sentiment']}")
        sections.append(f"Summary: {summary['ai_summary']}")
        if summary.get("risk_factors"):
            sections.append(f"Risk factors: {', '.join(summary['risk_factors'])}")
        if summary.get("opportunities"):
            sections.append(f"Opportunities: {', '.join(summary['opportunities'])}")
    elif articles:
        sections.append("\n## Recent Headlines")
        for a in articles[:8]:
            sections.append(f"- [{a.get('source', '?')}] {a.get('title', '')}")

    # Earnings
    if earnings:
        sections.append("\n## Earnings Context")
        upcoming = earnings.get("upcoming")
        if upcoming:
            sections.append(f"Next earnings: {upcoming['event_date']} ({upcoming['days_until']} days away)")
            if upcoming.get("eps_estimate"):
                sections.append(f"EPS estimate: ${upcoming['eps_estimate']:.2f}")
        recent = earnings.get("recent_surprises", [])
        for s in recent:
            sections.append(f"Recent: {s.get('event_date', '?')} — surprise {s.get('surprise_pct', 0):+.1f}%")

    # Competitive intelligence
    if sector_intel and sector_intel.get("competitive_dynamics"):
        sections.append(f"\n## Competitive Intelligence ({sector_intel.get('sub_sector', 'unknown')})")
        sections.append(f"Peers: {', '.join(sector_intel.get('peers_analyzed', []))}")
        sections.append(f"Sector sentiment: {sector_intel.get('sector_sentiment', 'unknown')}")
        sections.append(f"Competitive dynamics: {sector_intel['competitive_dynamics']}")
        themes = sector_intel.get("key_themes", [])
        if themes:
            sections.append(f"Key themes: {', '.join(themes)}")
        fc = sector_intel.get("fundamental_comparison", {})
        if fc:
            sections.append(f"Margins vs peers: {fc.get('margin_vs_peers', 'unknown')}")
            sections.append(f"Growth vs peers: {fc.get('growth_vs_peers', 'unknown')}")
            sections.append(f"Valuation vs peers: {fc.get('valuation_vs_peers', 'unknown')}")

    # Output schema
    sections.append("""
## Required Output Format
Return ONLY valid JSON:
{
  "recommendation": "BUY" | "SELL" | "HOLD",
  "confidence": <0.0-1.0>,
  "summary": "<2-3 sentence investment thesis>",
  "fundamentals": "<assessment of earnings quality, growth trajectory, margins>",
  "technicals": "<assessment of price action, momentum, support/resistance>",
  "competitive_position": "<where this company stands vs peers>",
  "risk_factors": ["<specific risk>"],
  "catalysts": ["<specific catalyst>"],
  "sector_context": "<how sector trends affect this stock>",
  "earnings_insight": "<earnings timing, recent surprises, expectations>",
  "risk_level_note": "<how the investor's risk profile affected this recommendation>"
}""")

    return "\n".join(sections)


def _call_claude(prompt: str, risk_level: int) -> dict:
    """Call Claude for the analysis."""
    try:
        client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)
        response = client.messages.create(
            model=settings.judge.model,
            max_tokens=2048,
            temperature=0.2,
            system=TICKER_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        return json.loads(raw)

    except Exception as e:
        logger.error(f"Claude analysis call failed: {e}")
        return {
            "recommendation": "HOLD",
            "confidence": 0.0,
            "summary": f"Analysis failed: {e}",
            "fundamentals": "",
            "technicals": "",
            "competitive_position": "",
            "risk_factors": [str(e)],
            "catalysts": [],
            "sector_context": "",
            "earnings_insight": "",
            "risk_level_note": "",
        }
