"""Inter-company competitive intelligence layer.

Provides peer identification, earnings spillover detection, competitor news
collection, and fundamental comparison — all synthesized into a structured
sector intelligence package via Claude.

This module enriches both the full pipeline (judge + summarizer) and the
single-ticker AI analysis with competitive context.
"""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

logger = logging.getLogger("trademark.competitive_intel")


def get_sector_peers(
    ticker: str,
    sub_sector: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Find the top peer companies for a ticker within its sub_sector.

    For universe tickers: looks up sub_sector from universe.csv.
    For out-of-universe tickers: uses provided sub_sector or attempts to
    match via yfinance industry info.

    Returns list of {ticker, name, sub_sector, market_cap_tier}, sorted by
    market_cap_tier priority (mega > large > mid).
    """
    universe = pd.read_csv(settings.paths.universe_path)

    # Determine sub_sector
    if sub_sector is None:
        match = universe[universe["ticker"] == ticker.upper()]
        if not match.empty:
            sub_sector = match.iloc[0]["sub_sector"]
        else:
            sub_sector = _infer_sub_sector(ticker, universe)

    if not sub_sector:
        return []

    # Get peers in same sub_sector (exclude the target ticker)
    peers = universe[
        (universe["sub_sector"] == sub_sector) &
        (universe["ticker"] != ticker.upper())
    ].copy()

    if peers.empty:
        return []

    # Sort by market cap tier priority
    tier_order = {"mega": 0, "large": 1, "mid": 2}
    peers["_tier_rank"] = peers["market_cap_tier"].map(tier_order).fillna(3)
    peers = peers.sort_values("_tier_rank").head(limit)

    return [
        {
            "ticker": row["ticker"],
            "name": row.get("name", ""),
            "sub_sector": row["sub_sector"],
            "market_cap_tier": row.get("market_cap_tier", ""),
        }
        for _, row in peers.iterrows()
    ]


def _infer_sub_sector(ticker: str, universe: pd.DataFrame) -> str | None:
    """Attempt to infer the closest sub_sector for an out-of-universe ticker."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        industry = info.get("industry", "").lower()
        sector = info.get("sector", "").lower()

        # Simple keyword matching against existing sub_sectors
        sub_sectors = universe["sub_sector"].unique()
        for ss in sub_sectors:
            ss_lower = ss.lower().replace("_", " ")
            if ss_lower in industry or industry in ss_lower:
                return ss
            if ss_lower in sector or sector in ss_lower:
                return ss

        # Broader matching
        keyword_map = {
            "semiconductor": "semiconductors",
            "software": "enterprise_software",
            "cloud": "cloud_software",
            "cyber": "cybersecurity",
            "bank": "banks",
            "pharma": "pharma",
            "biotech": "biotech",
            "insurance": "insurance",
            "retail": "retail",
            "auto": "autos",
            "energy": "energy_majors",
            "utility": "utilities",
            "telecom": "telecom",
            "media": "media_entertainment",
            "aerospace": "aerospace_defense",
            "health": "healthcare_equipment",
        }
        for keyword, mapped_sector in keyword_map.items():
            if keyword in industry or keyword in sector:
                if mapped_sector in sub_sectors:
                    return mapped_sector

        return None
    except Exception:
        return None


def detect_earnings_spillover(
    peer_tickers: list[str],
    days: int = 14,
) -> list[dict]:
    """Detect recent earnings beats/misses among peer companies.

    Combines earnings_calendar data (actual surprise %) with news_research
    summaries to identify sector-wide earnings trends.
    """
    spillover = []

    # Check earnings calendar for concrete beats/misses
    try:
        from src.ingest.earnings_calendar import get_recent_earnings_surprises
        surprises = get_recent_earnings_surprises(peer_tickers, days_back=days)
        for s in surprises:
            surprise = s.get("surprise_pct")
            if surprise is None:
                continue
            event_type = "earnings_beat" if surprise > 0 else "earnings_miss"
            sentiment = "positive" if surprise > 0 else "negative"
            spillover.append({
                "peer_ticker": s["ticker"],
                "event_type": event_type,
                "sentiment": sentiment,
                "summary": f"EPS surprise: {surprise:+.1f}% (est {s.get('eps_estimate', '?')}, actual {s.get('eps_actual', '?')})",
                "date": s["event_date"],
            })
    except Exception as e:
        logger.debug(f"Earnings spillover calendar check failed: {e}")

    # Check news_research for earnings-related summaries
    try:
        con = get_connection()
        cutoff = (datetime.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
        placeholders = ", ".join(["$" + str(i + 2) for i in range(len(peer_tickers))])
        rows = con.execute(f"""
            SELECT ticker, ai_summary, sentiment, research_date
            FROM news_research
            WHERE ticker IN ({placeholders})
              AND research_date >= CAST($1 AS DATE)
              AND (ai_summary ILIKE '%earnings%' OR ai_summary ILIKE '%revenue%'
                   OR ai_summary ILIKE '%beat%' OR ai_summary ILIKE '%miss%'
                   OR ai_summary ILIKE '%guidance%')
        """, [cutoff] + peer_tickers).fetchall()
        con.close()

        existing_tickers = {s["peer_ticker"] for s in spillover}
        for r in rows:
            if r[0] not in existing_tickers:
                spillover.append({
                    "peer_ticker": r[0],
                    "event_type": "earnings_news",
                    "sentiment": r[2] or "neutral",
                    "summary": (r[1] or "")[:200],
                    "date": str(r[3]),
                })
    except Exception as e:
        logger.debug(f"Earnings spillover news check failed: {e}")

    return spillover


def collect_competitor_news(
    ticker: str,
    peer_tickers: list[str],
    max_per_peer: int = 3,
) -> dict[str, list[dict]]:
    """Fetch recent news for competitor tickers in parallel.

    Lighter than the main ticker's news search (fewer articles per peer).
    Reuses search_ticker_news() from news_agent.py.
    """
    from src.research.news_agent import search_ticker_news

    results: dict[str, list[dict]] = {}

    def _fetch(peer: str) -> tuple[str, list[dict]]:
        articles = search_ticker_news(peer, max_results=max_per_peer)
        return peer, articles

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch, p): p for p in peer_tickers}
        for future in as_completed(futures):
            try:
                peer, articles = future.result()
                results[peer] = articles
            except Exception:
                results[futures[future]] = []

    return results


def compare_peer_fundamentals(
    ticker: str,
    peer_tickers: list[str],
) -> dict:
    """Compare a ticker's fundamentals against peer averages.

    Uses existing factor_scores and fundamentals_pit tables.
    Returns relative positioning (above_avg, in_line, below_avg).
    """
    if not peer_tickers:
        return {}

    try:
        con = get_connection()

        # Get latest factor scores for ticker + peers
        all_tickers = [ticker.upper()] + [p.upper() for p in peer_tickers]
        placeholders = ", ".join(["$" + str(i + 1) for i in range(len(all_tickers))])

        scores = con.execute(f"""
            WITH latest AS (
                SELECT ticker, date,
                       eps_growth_yoy, revenue_growth_yoy, gross_margin_trend,
                       relative_valuation, composite_score, score_decile,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM factor_scores
                WHERE ticker IN ({placeholders})
            )
            SELECT * FROM latest WHERE rn = 1
        """, all_tickers).fetchdf()
        con.close()

        if scores.empty or ticker.upper() not in scores["ticker"].values:
            return {}

        target = scores[scores["ticker"] == ticker.upper()].iloc[0]
        peers_df = scores[scores["ticker"] != ticker.upper()]

        if peers_df.empty:
            return {}

        def _classify(val, peer_mean, peer_std):
            if pd.isna(val) or pd.isna(peer_mean):
                return "unknown"
            if peer_std == 0 or pd.isna(peer_std):
                return "in_line"
            z = (val - peer_mean) / peer_std
            if z > 0.5:
                return "above_avg"
            elif z < -0.5:
                return "below_avg"
            return "in_line"

        eps_growth = target.get("eps_growth_yoy")
        rev_growth = target.get("revenue_growth_yoy")
        gm_trend = target.get("gross_margin_trend")
        rel_val = target.get("relative_valuation")

        peer_metrics = []
        for _, p in peers_df.iterrows():
            peer_metrics.append({
                "ticker": p["ticker"],
                "eps_growth": round(float(p.get("eps_growth_yoy", 0)), 3) if pd.notna(p.get("eps_growth_yoy")) else None,
                "rev_growth": round(float(p.get("revenue_growth_yoy", 0)), 3) if pd.notna(p.get("revenue_growth_yoy")) else None,
                "gross_margin": round(float(p.get("gross_margin_trend", 0)), 3) if pd.notna(p.get("gross_margin_trend")) else None,
                "composite_score": round(float(p.get("composite_score", 0)), 3) if pd.notna(p.get("composite_score")) else None,
                "decile": int(p.get("score_decile", 0)) if pd.notna(p.get("score_decile")) else None,
            })

        peer_eps_mean = peers_df["eps_growth_yoy"].mean()
        peer_rev_mean = peers_df["revenue_growth_yoy"].mean()
        peer_gm_mean = peers_df["gross_margin_trend"].mean()

        peer_eps_std = peers_df["eps_growth_yoy"].std()
        peer_rev_std = peers_df["revenue_growth_yoy"].std()

        margin_vs = _classify(gm_trend, peer_gm_mean, peers_df["gross_margin_trend"].std())
        growth_vs = _classify(
            (float(eps_growth or 0) + float(rev_growth or 0)) / 2,
            (float(peer_eps_mean or 0) + float(peer_rev_mean or 0)) / 2,
            (float(peer_eps_std or 0) + float(peer_rev_std or 0)) / 2,
        )

        val_score = float(rel_val) if pd.notna(rel_val) else 0
        peer_val_mean = peers_df["relative_valuation"].mean()
        if val_score > 0.3:
            valuation_vs = "discount"
        elif val_score < -0.3:
            valuation_vs = "premium"
        else:
            valuation_vs = "fair"

        return {
            "margin_vs_peers": margin_vs,
            "growth_vs_peers": growth_vs,
            "valuation_vs_peers": valuation_vs,
            "peer_metrics": peer_metrics,
        }

    except Exception as e:
        logger.debug(f"Peer fundamentals comparison failed: {e}")
        return {}


def build_sector_intelligence(
    ticker: str,
    sub_sector: str,
    peer_news: dict[str, list[dict]],
    spillover: list[dict],
    peer_fundamentals: dict,
) -> dict:
    """Synthesize all competitive data into a structured intelligence package.

    Makes a single Claude API call per sub_sector to summarize competitive
    dynamics, contract wins/losses, and sector sentiment.
    """
    import anthropic

    # Build context for Claude
    news_context = ""
    for peer, articles in peer_news.items():
        if articles:
            headlines = "; ".join([a["title"] for a in articles[:3]])
            news_context += f"\n  {peer}: {headlines}"

    spillover_context = ""
    for s in spillover:
        spillover_context += f"\n  {s['peer_ticker']}: {s['event_type']} ({s['sentiment']}) - {s['summary']}"

    fundamentals_context = ""
    if peer_fundamentals:
        fundamentals_context = f"""
Relative positioning:
  Margins vs peers: {peer_fundamentals.get('margin_vs_peers', 'unknown')}
  Growth vs peers: {peer_fundamentals.get('growth_vs_peers', 'unknown')}
  Valuation vs peers: {peer_fundamentals.get('valuation_vs_peers', 'unknown')}"""

    prompt = f"""Analyze the competitive landscape for {ticker} in the {sub_sector} sector.

Recent peer news:{news_context or ' None available'}

Earnings activity:{spillover_context or ' None available'}

Fundamental comparison:{fundamentals_context or ' None available'}

Provide a concise analysis in JSON format:
{{
  "competitive_dynamics": "2-3 sentence summary of competitive positioning, contract wins/losses, market share shifts",
  "sector_sentiment": "positive" | "negative" | "neutral" | "mixed",
  "key_themes": ["theme1", "theme2", "theme3"]
}}

Be specific about competitive implications for {ticker}. If a peer beat earnings, explain the spillover effect. If a competitor won/lost a contract, note the impact."""

    try:
        client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON from response
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(text)

        return {
            "sub_sector": sub_sector,
            "peers_analyzed": list(peer_news.keys()),
            "earnings_spillover": spillover,
            "competitive_dynamics": parsed.get("competitive_dynamics", ""),
            "sector_sentiment": parsed.get("sector_sentiment", "neutral"),
            "key_themes": parsed.get("key_themes", []),
            "fundamental_comparison": peer_fundamentals,
        }
    except Exception as e:
        logger.warning(f"Sector intelligence synthesis failed for {sub_sector}: {e}")
        return {
            "sub_sector": sub_sector,
            "peers_analyzed": list(peer_news.keys()),
            "earnings_spillover": spillover,
            "competitive_dynamics": "",
            "sector_sentiment": "unknown",
            "key_themes": [],
            "fundamental_comparison": peer_fundamentals,
        }


def get_full_sector_intelligence(
    ticker: str,
    sub_sector: str | None = None,
) -> dict:
    """Convenience function: runs the full competitive intelligence pipeline.

    1. Find peers
    2. Collect competitor news
    3. Detect earnings spillover
    4. Compare fundamentals
    5. Synthesize with Claude
    """
    peers = get_sector_peers(ticker, sub_sector)
    if not peers:
        return {}

    actual_sub_sector = peers[0]["sub_sector"] if peers else (sub_sector or "unknown")
    peer_tickers = [p["ticker"] for p in peers]

    peer_news = collect_competitor_news(ticker, peer_tickers)
    spillover = detect_earnings_spillover(peer_tickers)
    fundamentals = compare_peer_fundamentals(ticker, peer_tickers)
    intel = build_sector_intelligence(ticker, actual_sub_sector, peer_news, spillover, fundamentals)

    return intel
