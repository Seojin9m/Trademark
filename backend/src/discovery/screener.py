"""Auto-discovery engine: finds breakout stocks outside the current universe.

Combines multiple free scraping sources (Finviz, EDGAR, Yahoo Finance) and
earnings calendar data to surface new investment candidates.

Follows existing ingestion patterns: ingestion_log cooldown (24h default),
graceful failure per source, deduplication, and DuckDB storage.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

COOLDOWN_HOURS = 24


def should_run_discovery() -> tuple[bool, str]:
    """Check ingestion_log to decide whether to run a discovery scan."""
    try:
        con = get_connection()
        row = con.execute("""
            SELECT last_ingested_at FROM ingestion_log
            WHERE data_type = 'discovery'
        """).fetchone()
        con.close()

        if row is None:
            return True, "never scanned"

        last = row[0]
        if isinstance(last, str):
            last = datetime.fromisoformat(last)
        hours_ago = (datetime.now() - last).total_seconds() / 3600
        if hours_ago >= COOLDOWN_HOURS:
            return True, f"last scanned {hours_ago:.0f}h ago"
        return False, f"scanned {hours_ago:.1f}h ago (cooldown {COOLDOWN_HOURS}h)"
    except Exception:
        return True, "ingestion_log check failed"


def _load_universe_tickers() -> set[str]:
    """Load current universe tickers to filter them out of discovery results."""
    try:
        df = pd.read_csv(settings.paths.universe_path)
        return set(df["ticker"].str.upper().tolist())
    except Exception:
        return set()


def run_discovery_scan() -> list[dict]:
    """Execute a full discovery scan across all sources.

    Returns list of new candidate dicts. Filters out tickers already in the
    universe. Stores results to discovery_candidates table.
    """
    universe_tickers = _load_universe_tickers()
    candidates: dict[str, dict] = {}

    # --- Source 1: Finviz screens ---
    print("  [Discovery] Running Finviz screens...")
    try:
        from src.ingest.screener_sources import fetch_all_finviz_screens
        finviz_df = fetch_all_finviz_screens()
        if not finviz_df.empty:
            for _, row in finviz_df.iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if not ticker or ticker in universe_tickers:
                    continue
                if ticker not in candidates:
                    candidates[ticker] = {
                        "ticker": ticker,
                        "company_name": row.get("company_name", ""),
                        "sector": row.get("sector", ""),
                        "industry": row.get("industry", ""),
                        "market_cap": str(row.get("market_cap", "")),
                        "sources": [],
                        "reasons": [],
                        "metrics": {},
                    }
                screen = row.get("screen_type", "finviz")
                candidates[ticker]["sources"].append(f"finviz_{screen}")
                candidates[ticker]["reasons"].append(f"Finviz {screen} screen")
                candidates[ticker]["metrics"][f"finviz_{screen}"] = {
                    "price": row.get("price"),
                    "change_pct": row.get("change_pct"),
                    "volume": row.get("volume"),
                    "pe": row.get("pe"),
                }
            print(f"    Finviz: {len([t for t in finviz_df['ticker'] if t.upper() not in universe_tickers])} new candidates")
    except Exception as e:
        print(f"    Finviz failed (non-critical): {e}")

    # --- Source 2: SEC EDGAR filings ---
    print("  [Discovery] Checking SEC EDGAR filings...")
    try:
        from src.ingest.screener_sources import fetch_recent_filings
        edgar_df = fetch_recent_filings(["8-K"], days=7)
        if not edgar_df.empty:
            for _, row in edgar_df.iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if not ticker or ticker in universe_tickers:
                    continue
                if ticker not in candidates:
                    candidates[ticker] = {
                        "ticker": ticker,
                        "company_name": row.get("company_name", ""),
                        "sector": "",
                        "industry": "",
                        "market_cap": "",
                        "sources": [],
                        "reasons": [],
                        "metrics": {},
                    }
                candidates[ticker]["sources"].append("edgar_8k")
                candidates[ticker]["reasons"].append(f"SEC 8-K filing on {row.get('filing_date', 'unknown')}")
                candidates[ticker]["metrics"]["edgar"] = {
                    "filing_type": row.get("filing_type"),
                    "filing_date": row.get("filing_date"),
                }
            print(f"    EDGAR: found {len(edgar_df)} recent filings")
    except Exception as e:
        print(f"    EDGAR failed (non-critical): {e}")

    # --- Source 3: Yahoo Finance trending ---
    print("  [Discovery] Checking Yahoo Finance trending...")
    try:
        from src.ingest.screener_sources import fetch_yahoo_trending
        yahoo_df = fetch_yahoo_trending()
        if not yahoo_df.empty:
            for _, row in yahoo_df.iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if not ticker or ticker in universe_tickers:
                    continue
                if ticker not in candidates:
                    candidates[ticker] = {
                        "ticker": ticker,
                        "company_name": row.get("company_name", ""),
                        "sector": row.get("sector", ""),
                        "industry": row.get("industry", ""),
                        "market_cap": str(row.get("market_cap", "")),
                        "sources": [],
                        "reasons": [],
                        "metrics": {},
                    }
                screen = row.get("screen_type", "yahoo")
                candidates[ticker]["sources"].append(screen)
                candidates[ticker]["reasons"].append(f"Yahoo {screen.replace('yahoo_', '')}")
                candidates[ticker]["metrics"]["yahoo"] = {
                    "price": row.get("price"),
                    "change_pct": row.get("change_pct"),
                    "volume": row.get("volume"),
                }
            print(f"    Yahoo: {len([t for t in yahoo_df['ticker'] if str(t).upper() not in universe_tickers])} new candidates")
    except Exception as e:
        print(f"    Yahoo trending failed (non-critical): {e}")

    # --- Source 4: Recent earnings beats ---
    print("  [Discovery] Checking recent earnings beats...")
    try:
        from src.ingest.earnings_calendar import get_recent_earnings_surprises
        all_tickers_with_data = list(universe_tickers)
        surprises = get_recent_earnings_surprises(all_tickers_with_data, days_back=14)
        beats = [s for s in surprises if s.get("surprise_pct") and s["surprise_pct"] > 5.0]
        for s in beats:
            ticker = s["ticker"]
            if ticker in universe_tickers:
                continue
            if ticker not in candidates:
                candidates[ticker] = {
                    "ticker": ticker,
                    "company_name": "",
                    "sector": "",
                    "industry": "",
                    "market_cap": "",
                    "sources": [],
                    "reasons": [],
                    "metrics": {},
                }
            candidates[ticker]["sources"].append("earnings_beat")
            candidates[ticker]["reasons"].append(
                f"Earnings beat: {s['surprise_pct']:.1f}% surprise on {s['event_date']}"
            )
            candidates[ticker]["metrics"]["earnings"] = {
                "surprise_pct": s["surprise_pct"],
                "eps_estimate": s.get("eps_estimate"),
                "eps_actual": s.get("eps_actual"),
            }
    except Exception as e:
        print(f"    Earnings beats check failed (non-critical): {e}")

    # --- Store candidates ---
    candidate_list = list(candidates.values())
    if candidate_list:
        _store_candidates(candidate_list)
    _log_discovery(len(candidate_list))

    print(f"  [Discovery] Complete: {len(candidate_list)} new candidates found")
    return candidate_list


def _store_candidates(candidates: list[dict]) -> None:
    """Insert discovery candidates into DuckDB."""
    con = get_connection()
    today = datetime.now().date().strftime("%Y-%m-%d")

    for c in candidates:
        primary_source = c["sources"][0] if c["sources"] else "unknown"
        reason = " | ".join(c["reasons"])
        metrics_json = json.dumps(c["metrics"])

        con.execute("""
            DELETE FROM discovery_candidates
            WHERE ticker = $1 AND discovery_source = $2 AND discovery_date = $3
        """, [c["ticker"], primary_source, today])

        con.execute("""
            INSERT INTO discovery_candidates
            (ticker, company_name, sector, industry, market_cap,
             discovery_source, discovery_date, discovery_reason, metrics, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'new')
        """, [
            c["ticker"], c.get("company_name", ""), c.get("sector", ""),
            c.get("industry", ""), c.get("market_cap", ""),
            primary_source, today, reason, metrics_json,
        ])

    con.close()


def _log_discovery(count: int) -> None:
    """Update ingestion_log for discovery scans."""
    try:
        con = get_connection()
        now = datetime.now().isoformat()
        con.execute("DELETE FROM ingestion_log WHERE data_type = 'discovery'")
        con.execute("""
            INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes)
            VALUES ('discovery', $1, $2, $3)
        """, [now, count, f"{count} candidates found"])
        con.close()
    except Exception:
        pass


def get_candidates(status: str | None = None, limit: int = 50) -> list[dict]:
    """Retrieve discovery candidates from DuckDB."""
    try:
        con = get_connection()
        if status:
            rows = con.execute("""
                SELECT ticker, company_name, sector, industry, market_cap,
                       discovery_source, discovery_date, discovery_reason, metrics, status
                FROM discovery_candidates
                WHERE status = $1
                ORDER BY discovery_date DESC
                LIMIT $2
            """, [status, limit]).fetchall()
        else:
            rows = con.execute("""
                SELECT ticker, company_name, sector, industry, market_cap,
                       discovery_source, discovery_date, discovery_reason, metrics, status
                FROM discovery_candidates
                ORDER BY discovery_date DESC
                LIMIT $1
            """, [limit]).fetchall()
        con.close()

        return [
            {
                "ticker": r[0], "company_name": r[1], "sector": r[2],
                "industry": r[3], "market_cap": r[4], "discovery_source": r[5],
                "discovery_date": str(r[6]), "discovery_reason": r[7],
                "metrics": json.loads(r[8]) if r[8] else {},
                "status": r[9],
            }
            for r in rows
        ]
    except Exception:
        return []


def update_candidate_status(ticker: str, status: str) -> None:
    """Update a candidate's status (new → analyzed | promoted | dismissed)."""
    con = get_connection()
    con.execute("""
        UPDATE discovery_candidates SET status = $1
        WHERE ticker = $2
    """, [status, ticker.upper()])
    con.close()


def _parse_market_cap(cap_str: str) -> float | None:
    """Parse market cap strings like '5.2B', '300M', '50M' into float dollars."""
    if not cap_str:
        return None
    cap_str = str(cap_str).strip().upper().replace(",", "").replace("$", "")
    try:
        if cap_str.endswith("T"):
            return float(cap_str[:-1]) * 1e12
        if cap_str.endswith("B"):
            return float(cap_str[:-1]) * 1e9
        if cap_str.endswith("M"):
            return float(cap_str[:-1]) * 1e6
        if cap_str.endswith("K"):
            return float(cap_str[:-1]) * 1e3
        return float(cap_str)
    except (ValueError, IndexError):
        return None


def classify_risk_tier(market_cap_str: str, is_profitable: bool) -> str:
    """Classify a stock's risk tier based on market cap and profitability.

    Returns 'standard', 'moderate_risk', or 'high_risk'.
    """
    cap = _parse_market_cap(market_cap_str)
    if cap is None:
        return "moderate_risk"

    if cap >= 2e9:
        tier = "standard"
    elif cap >= 500e6:
        tier = "moderate_risk"
    else:
        tier = "high_risk"

    if not is_profitable:
        if tier == "standard":
            tier = "moderate_risk"
        elif tier == "moderate_risk":
            tier = "high_risk"

    return tier


def promote_to_universe(
    ticker: str, sub_sector: str, company_name: str = "",
    risk_tier: str = "standard",
) -> None:
    """Add a discovered ticker to the main universe CSV and ingest its data."""
    import csv

    ticker = ticker.upper()
    universe_path = settings.paths.universe_path

    existing = pd.read_csv(universe_path)
    if ticker in existing["ticker"].values:
        print(f"  {ticker} already in universe")
        update_candidate_status(ticker, "promoted")
        return

    has_risk_tier = "risk_tier" in existing.columns
    with open(universe_path, "a", newline="") as f:
        writer = csv.writer(f)
        row = [ticker, company_name, sub_sector, "mid"]
        if has_risk_tier:
            row.append(risk_tier)
        writer.writerow(row)

    print(f"  Added {ticker} to universe (sub_sector={sub_sector}, risk_tier={risk_tier})")

    try:
        from src.ingest.prices import backfill_historical
        backfill_historical([ticker])
        print(f"  Backfilled price history for {ticker}")
    except Exception as e:
        print(f"  WARNING: Price backfill failed for {ticker}: {e}")

    update_candidate_status(ticker, "promoted")


def auto_promote_candidates() -> list[str]:
    """Auto-promote candidates that score in top 30% composite for 2 consecutive runs.

    Returns list of promoted tickers.
    """
    promoted = []
    try:
        con = get_connection()

        candidates = con.execute("""
            SELECT DISTINCT ticker FROM discovery_candidates
            WHERE status IN ('new', 'analyzed')
        """).fetchdf()

        if candidates.empty:
            con.close()
            return promoted

        scoring_dates = con.execute("""
            SELECT DISTINCT date FROM factor_scores
            ORDER BY date DESC LIMIT 2
        """).fetchdf()

        if len(scoring_dates) < 2:
            con.close()
            return promoted

        date1 = str(scoring_dates["date"].iloc[0])
        date2 = str(scoring_dates["date"].iloc[1])

        for ticker in candidates["ticker"].tolist():
            scores = con.execute("""
                SELECT date, score_decile FROM factor_scores
                WHERE ticker = $1 AND date IN ($2, $3)
                ORDER BY date DESC
            """, [ticker, date1, date2]).fetchdf()

            if len(scores) >= 2 and all(scores["score_decile"] >= 8):
                cap_row = con.execute("""
                    SELECT market_cap, sector, industry FROM discovery_candidates
                    WHERE ticker = $1
                    ORDER BY discovery_date DESC LIMIT 1
                """, [ticker]).fetchone()

                market_cap = cap_row[0] if cap_row else ""
                sector = cap_row[1] if cap_row else ""
                industry = cap_row[2] if cap_row else ""

                is_profitable = True
                try:
                    eps_row = con.execute("""
                        SELECT SUM(eps_diluted) as ttm_eps
                        FROM (
                            SELECT eps_diluted, ROW_NUMBER() OVER (ORDER BY fiscal_period_end DESC) AS rn
                            FROM fundamentals_pit WHERE ticker = $1
                        ) WHERE rn <= 4
                    """, [ticker]).fetchone()
                    if eps_row and eps_row[0] is not None:
                        is_profitable = eps_row[0] > 0
                except Exception:
                    pass

                risk_tier = classify_risk_tier(market_cap, is_profitable)
                sub_sector = industry.lower().replace(" ", "_") if industry else sector.lower().replace(" ", "_") if sector else "unknown"

                con.close()
                promote_to_universe(ticker, sub_sector, risk_tier=risk_tier)
                promoted.append(ticker)
                con = get_connection()

        con.close()
    except Exception as e:
        print(f"  Auto-promote failed: {e}")

    if promoted:
        print(f"  Auto-promoted {len(promoted)} tickers: {', '.join(promoted)}")
    return promoted


def flag_weak_universe_tickers() -> list[dict]:
    """Flag universe tickers below decile 3 for 90+ consecutive days.

    Returns list of {ticker, avg_decile, days_below, recommendation}.
    Does NOT auto-delete — flags for user review only.
    """
    flagged = []
    try:
        con = get_connection()

        cutoff_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        universe = pd.read_csv(settings.paths.universe_path)
        universe_tickers = universe["ticker"].tolist()

        for ticker in universe_tickers:
            scores = con.execute("""
                SELECT date, score_decile FROM factor_scores
                WHERE ticker = $1 AND date >= CAST($2 AS DATE)
                ORDER BY date ASC
            """, [ticker, cutoff_date]).fetchdf()

            if len(scores) < 3:
                continue

            if (scores["score_decile"] <= 3).all():
                avg_d = float(scores["score_decile"].mean())
                entry = {
                    "ticker": ticker,
                    "avg_decile": round(avg_d, 1),
                    "days_below": len(scores),
                    "recommendation": "review_for_removal",
                }
                flagged.append(entry)

                today = datetime.now().date().strftime("%Y-%m-%d")
                con.execute("""
                    DELETE FROM discovery_candidates
                    WHERE ticker = $1 AND discovery_source = 'auto_demote'
                """, [ticker])
                con.execute("""
                    INSERT INTO discovery_candidates
                    (ticker, company_name, sector, industry, market_cap,
                     discovery_source, discovery_date, discovery_reason, metrics, status)
                    VALUES ($1, '', '', '', '', 'auto_demote', $2, $3, '{}', 'flagged_weak')
                """, [ticker, today, f"Below decile 3 for 90+ days (avg {avg_d:.1f})"])

        con.close()
    except Exception as e:
        print(f"  Flag weak tickers failed: {e}")

    if flagged:
        print(f"  Flagged {len(flagged)} weak tickers for review")
    return flagged


if __name__ == "__main__":
    from src.db.schema import init_db
    init_db()
    run_discovery_scan()
