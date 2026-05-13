"""Forward analyst estimates ingestion: EPS estimates, price targets, growth forecasts.

Uses yfinance (already installed) as the primary source. Stores weekly snapshots
so that EPS revision momentum can be computed by comparing current vs prior estimates.

Follows existing ingestion patterns: ingestion_log cooldown, batch DB writes,
graceful per-ticker failure.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

COOLDOWN_HOURS = 7 * 24  # weekly refresh

# yfinance gets aggressively rate-limited on the analyst endpoints (the
# "Invalid Crumb" 401 wave we saw with 4 workers hitting 500 tickers).
# Drop to 1 worker + 1s per-ticker pause to stay under the threshold.
# Full universe coverage takes longer this way (200 tickers per weekly run
# over ~11 weeks for 2,166 tickers) but the trickle-fill works because
# compute_forward_estimate_factor tolerates partial coverage.
_FETCH_WORKERS = int(os.getenv("FORWARD_EST_WORKERS", "1"))
_PER_TICKER_DELAY_S = float(os.getenv("FORWARD_EST_DELAY_S", "1.0"))
_DEFAULT_MAX_TICKERS = int(os.getenv("FORWARD_EST_MAX_TICKERS", "200"))


def should_refresh_estimates() -> tuple[bool, str]:
    """Check ingestion_log to decide whether to re-fetch forward estimates."""
    try:
        con = get_connection()
        row = con.execute("""
            SELECT last_ingested_at FROM ingestion_log
            WHERE data_type = 'forward_estimates'
        """).fetchone()
        con.close()

        if row is None:
            return True, "never ingested"

        last = row[0]
        if isinstance(last, str):
            last = datetime.fromisoformat(last)
        hours_ago = (datetime.now() - last).total_seconds() / 3600
        if hours_ago >= COOLDOWN_HOURS:
            return True, f"last ingested {hours_ago:.0f}h ago"
        return False, f"ingested {hours_ago:.1f}h ago (cooldown {COOLDOWN_HOURS}h)"
    except Exception:
        return True, "ingestion_log check failed"


def _pick_stale_first(tickers: list[str], cap: int) -> list[str]:
    """Return up to `cap` tickers, prioritizing those with stale or missing
    forward_estimates rows. Converges to full coverage over multiple runs.

    Pulls max(fetch_date) per ticker into a Python dict (no DB array params
    so it works on both DuckDB and Postgres), then sorts: never-fetched
    first, then oldest fetch_date ascending. Falls back to sorted prefix
    on any DB error so a fresh install still works.
    """
    try:
        con = get_connection()
        df = con.execute(
            "SELECT ticker, MAX(fetch_date) AS last_fetch FROM forward_estimates GROUP BY ticker"
        ).fetchdf()
        con.close()
        last_by_ticker = (
            dict(zip(df["ticker"].astype(str), df["last_fetch"])) if not df.empty else {}
        )

        def sort_key(t: str):
            ts = last_by_ticker.get(t)
            # None (never fetched) sorts first; pandas Timestamps / Python
            # dates compare correctly via str() fallback when needed.
            return (ts is not None, str(ts) if ts is not None else "", t)

        return sorted(tickers, key=sort_key)[:cap]
    except Exception as e:
        print(f"  Forward estimates: stale-first selection failed ({e}); using sorted prefix")
        return sorted(tickers)[:cap]


def _fetch_one_ticker(ticker: str, today) -> dict | None:
    """Fetch forward-estimate data for a single ticker.

    Returns the record dict if any data was retrieved, else None. Never
    raises — yfinance failures are common (rate limit, delisted ticker)
    and a single bad ticker should not break the batch.

    Note: deliberately does NOT call `t.info`. That endpoint is the heaviest
    one and the first to get IP-rate-limited; recommendation_mean was the
    only field it provided, which we accept as occasionally NULL.
    """
    try:
        t = yf.Ticker(ticker)
        record = {
            "ticker": ticker,
            "fetch_date": today,
            "eps_est_current_q": None,
            "eps_est_next_q": None,
            "eps_est_current_y": None,
            "eps_est_next_y": None,
            "num_analysts": None,
            "price_target_mean": None,
            "price_target_high": None,
            "price_target_low": None,
            "price_target_current": None,
            "growth_est_next_y": None,
            "recommendation_mean": None,
        }

        try:
            targets = t.analyst_price_targets
            if targets is not None:
                if isinstance(targets, dict):
                    record["price_target_mean"] = targets.get("mean")
                    record["price_target_high"] = targets.get("high")
                    record["price_target_low"] = targets.get("low")
                    record["price_target_current"] = targets.get("current")
                elif isinstance(targets, pd.DataFrame) and not targets.empty:
                    for col in targets.columns:
                        cl = col.lower()
                        if "mean" in cl or "average" in cl:
                            record["price_target_mean"] = float(targets[col].iloc[0])
                        elif "high" in cl:
                            record["price_target_high"] = float(targets[col].iloc[0])
                        elif "low" in cl:
                            record["price_target_low"] = float(targets[col].iloc[0])
                        elif "current" in cl:
                            record["price_target_current"] = float(targets[col].iloc[0])
        except Exception:
            pass

        try:
            ee = t.earnings_estimate
            if ee is not None and isinstance(ee, pd.DataFrame) and not ee.empty:
                avg_col = None
                analysts_col = None
                for c in ee.columns:
                    cl = c.lower()
                    if "avg" in cl or "average" in cl:
                        avg_col = c
                    elif "analyst" in cl or "number" in cl:
                        analysts_col = c

                if avg_col:
                    for idx_label in ee.index:
                        il = str(idx_label).lower()
                        val = ee.loc[idx_label, avg_col]
                        val = float(val) if pd.notna(val) else None
                        if "current qtr" in il or "0q" in il:
                            record["eps_est_current_q"] = val
                        elif "next qtr" in il or "+1q" in il:
                            record["eps_est_next_q"] = val
                        elif "current year" in il or "0y" in il:
                            record["eps_est_current_y"] = val
                        elif "next year" in il or "+1y" in il:
                            record["eps_est_next_y"] = val

                if analysts_col:
                    vals = ee[analysts_col].dropna()
                    if not vals.empty:
                        record["num_analysts"] = int(vals.iloc[0])
        except Exception:
            pass

        try:
            ge = t.growth_estimates
            if ge is not None and isinstance(ge, pd.DataFrame) and not ge.empty:
                ticker_col = None
                for c in ge.columns:
                    if ticker.upper() in str(c).upper() or "stock" in str(c).lower():
                        ticker_col = c
                        break
                if ticker_col is None and len(ge.columns) > 0:
                    ticker_col = ge.columns[0]

                if ticker_col:
                    for idx_label in ge.index:
                        il = str(idx_label).lower()
                        if "next year" in il or "+1y" in il or "next 5" in il:
                            val = ge.loc[idx_label, ticker_col]
                            if pd.notna(val):
                                val = float(str(val).replace("%", "")) / 100 if "%" in str(val) else float(val)
                                record["growth_est_next_y"] = val
                                break
        except Exception:
            pass

        has_data = any(
            v is not None
            for k, v in record.items()
            if k not in ("ticker", "fetch_date")
        )
        return record if has_data else None
    except Exception:
        return None


def fetch_forward_estimates(tickers: list[str]) -> pd.DataFrame:
    """Fetch analyst estimates + price targets from yfinance.

    Run sequentially with a small per-ticker delay because the analyst
    endpoints rate-limit hard at concurrency > 1. ~200 tickers per run
    takes ~3-4 minutes at 1s/ticker pacing.
    """
    today = datetime.now().date()
    records: list[dict] = []
    skipped = 0
    total = len(tickers)
    t0 = time.time()

    if _FETCH_WORKERS <= 1:
        print(f"  Forward estimates: serial fetch ({_PER_TICKER_DELAY_S:.1f}s pacing)...")
        for i, ticker in enumerate(tickers, 1):
            rec = _fetch_one_ticker(ticker, today)
            if rec is None:
                skipped += 1
            else:
                records.append(rec)
            if i % 25 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                print(
                    f"  Forward estimates: {i}/{total} "
                    f"({rate:.1f}/s, ETA {eta:.0f}s, kept {len(records)}, skipped {skipped})"
                )
            if i < total and _PER_TICKER_DELAY_S > 0:
                time.sleep(_PER_TICKER_DELAY_S)
    else:
        print(f"  Forward estimates: parallel fetch with {_FETCH_WORKERS} workers...")
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
            futures = {ex.submit(_fetch_one_ticker, t, today): t for t in tickers}
            done = 0
            for fut in as_completed(futures):
                done += 1
                rec = fut.result()
                if rec is None:
                    skipped += 1
                else:
                    records.append(rec)
                if done % 100 == 0 or done == total:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    print(
                        f"  Forward estimates: {done}/{total} "
                        f"({rate:.1f}/s, ETA {eta:.0f}s, kept {len(records)}, skipped {skipped})"
                    )

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def store_forward_estimates(df: pd.DataFrame) -> None:
    """Upsert forward estimates into DuckDB."""
    if df.empty:
        return

    con = get_connection()

    for _, row in df.iterrows():
        con.execute("""
            DELETE FROM forward_estimates
            WHERE ticker = $1 AND fetch_date = $2
        """, [row["ticker"], row["fetch_date"]])

        con.execute("""
            INSERT INTO forward_estimates
            (ticker, fetch_date, eps_est_current_q, eps_est_next_q,
             eps_est_current_y, eps_est_next_y, num_analysts,
             price_target_mean, price_target_high, price_target_low,
             price_target_current, growth_est_next_y, recommendation_mean,
             source, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """, [
            row["ticker"], row["fetch_date"],
            row.get("eps_est_current_q"), row.get("eps_est_next_q"),
            row.get("eps_est_current_y"), row.get("eps_est_next_y"),
            row.get("num_analysts"),
            row.get("price_target_mean"), row.get("price_target_high"),
            row.get("price_target_low"), row.get("price_target_current"),
            row.get("growth_est_next_y"), row.get("recommendation_mean"),
            "yahoo", datetime.now(),
        ])

    now = datetime.now().isoformat()
    con.execute("DELETE FROM ingestion_log WHERE data_type = 'forward_estimates'")
    con.execute("""
        INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes)
        VALUES ('forward_estimates', $1, $2, $3)
    """, [now, len(df), f"{df['ticker'].nunique()} tickers"])
    con.close()

    print(f"  Stored forward estimates for {df['ticker'].nunique()} tickers")


def ingest_forward_estimates(
    tickers: list[str] | None = None,
    max_tickers: int | None = None,
) -> None:
    """Full forward estimates ingestion pipeline.

    ``max_tickers`` caps how many tickers a single run processes. Defaults
    to FORWARD_EST_MAX_TICKERS env var (500). Pass 0 to disable the cap.
    The factor scoring code only consumes rows that exist in
    forward_estimates — partial population over multiple weekly runs
    converges to full coverage without blocking any single pipeline run.
    """
    from src.db.schema import init_db
    init_db()

    should, reason = should_refresh_estimates()
    if not should:
        print(f"  Forward estimates up-to-date: {reason}")
        return

    if tickers is None:
        from src.ingest.prices import load_universe
        tickers = load_universe()

    cap = _DEFAULT_MAX_TICKERS if max_tickers is None else max_tickers
    if cap and cap > 0 and len(tickers) > cap:
        # Rotate: prefer tickers with stale or missing forward_estimates so
        # we converge to full coverage over multiple weekly runs instead of
        # re-hitting the same A-prefix every week.
        tickers = _pick_stale_first(tickers, cap)
        print(
            f"  Forward estimates: picked {len(tickers)} stalest of "
            f"{len(tickers)} tickers (set FORWARD_EST_MAX_TICKERS=0 for full universe)"
        )

    print(f"  Fetching forward estimates for {len(tickers)} tickers...")
    df = fetch_forward_estimates(tickers)
    if not df.empty:
        store_forward_estimates(df)
    else:
        print("  No forward estimate data retrieved")


if __name__ == "__main__":
    ingest_forward_estimates()
