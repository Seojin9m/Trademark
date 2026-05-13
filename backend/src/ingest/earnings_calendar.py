"""Earnings calendar ingestion: tracks upcoming and historical earnings dates.

Uses yfinance (already installed) as the primary source.
Follows existing ingestion patterns: ingestion_log cooldown, batch DB writes,
graceful per-ticker failure.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

COOLDOWN_HOURS = 24


def should_refresh_earnings() -> tuple[bool, str]:
    """Check ingestion_log to decide whether to re-fetch earnings data."""
    try:
        con = get_connection()
        row = con.execute("""
            SELECT last_ingested_at FROM ingestion_log
            WHERE data_type = 'earnings_calendar'
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


def fetch_earnings_calendar(tickers: list[str]) -> pd.DataFrame:
    """Fetch earnings dates and estimates/actuals from yfinance.

    Returns DataFrame with columns matching the earnings_calendar table.
    """
    records = []
    skipped = []

    for i, ticker in enumerate(tickers):
        try:
            t = yf.Ticker(ticker)

            # Upcoming earnings from .calendar
            try:
                cal = t.calendar
                if cal is not None and not (isinstance(cal, pd.DataFrame) and cal.empty):
                    if isinstance(cal, dict):
                        earn_date = cal.get("Earnings Date")
                        if isinstance(earn_date, list) and earn_date:
                            earn_date = earn_date[0]
                        if earn_date is not None:
                            records.append({
                                "ticker": ticker,
                                "event_type": "earnings",
                                "event_date": pd.Timestamp(earn_date).date(),
                                "eps_estimate": cal.get("EPS Estimate"),
                                "eps_actual": None,
                                "surprise_pct": None,
                                "revenue_estimate": cal.get("Revenue Estimate"),
                                "revenue_actual": None,
                                "source": "yahoo",
                            })
                    elif isinstance(cal, pd.DataFrame):
                        if "Earnings Date" in cal.index:
                            dates = cal.loc["Earnings Date"]
                            earn_date = dates.iloc[0] if hasattr(dates, "iloc") else dates
                            if earn_date is not None and str(earn_date) != "NaT":
                                records.append({
                                    "ticker": ticker,
                                    "event_type": "earnings",
                                    "event_date": pd.Timestamp(earn_date).date(),
                                    "eps_estimate": None,
                                    "eps_actual": None,
                                    "surprise_pct": None,
                                    "revenue_estimate": None,
                                    "revenue_actual": None,
                                    "source": "yahoo",
                                })
            except Exception:
                pass

            # Historical earnings from .earnings_dates
            try:
                edates = t.earnings_dates
                if edates is not None and not edates.empty:
                    for idx, row in edates.head(8).iterrows():
                        edate = pd.Timestamp(idx).date() if not isinstance(idx, datetime) else idx.date()
                        eps_est = row.get("EPS Estimate")
                        eps_act = row.get("Reported EPS")
                        surprise = row.get("Surprise(%)")

                        eps_est = float(eps_est) if pd.notna(eps_est) else None
                        eps_act = float(eps_act) if pd.notna(eps_act) else None
                        surprise = float(surprise) if pd.notna(surprise) else None

                        records.append({
                            "ticker": ticker,
                            "event_type": "earnings",
                            "event_date": edate,
                            "eps_estimate": eps_est,
                            "eps_actual": eps_act,
                            "surprise_pct": surprise,
                            "revenue_estimate": None,
                            "revenue_actual": None,
                            "source": "yahoo",
                        })
            except Exception:
                pass

        except Exception as e:
            skipped.append((ticker, str(e)))

        if (i + 1) % 10 == 0:
            time.sleep(0.3)

    if skipped:
        print(f"  Earnings calendar: skipped {len(skipped)} tickers")

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.drop_duplicates(subset=["ticker", "event_type", "event_date"], keep="last")
    return df


def store_earnings_calendar(df: pd.DataFrame) -> None:
    """Upsert earnings data into DuckDB."""
    if df.empty:
        return

    con = get_connection()

    for _, row in df.iterrows():
        con.execute("""
            DELETE FROM earnings_calendar
            WHERE ticker = $1 AND event_type = $2 AND event_date = $3
        """, [row["ticker"], row["event_type"], row["event_date"]])

        con.execute("""
            INSERT INTO earnings_calendar
            (ticker, event_type, event_date, eps_estimate, eps_actual,
             surprise_pct, revenue_estimate, revenue_actual, source, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, [
            row["ticker"], row["event_type"], row["event_date"],
            row.get("eps_estimate"), row.get("eps_actual"), row.get("surprise_pct"),
            row.get("revenue_estimate"), row.get("revenue_actual"),
            row.get("source", "yahoo"), datetime.now(),
        ])

    now = datetime.now().isoformat()
    con.execute("DELETE FROM ingestion_log WHERE data_type = 'earnings_calendar'")
    con.execute("""
        INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes)
        VALUES ('earnings_calendar', $1, $2, $3)
    """, [now, len(df), f"{df['ticker'].nunique()} tickers"])
    con.close()

    print(f"  Stored {len(df)} earnings events for {df['ticker'].nunique()} tickers")


def get_upcoming_earnings(tickers: list[str], days_ahead: int = 14) -> dict[str, dict]:
    """Query earnings_calendar for tickers reporting soon.

    Returns {ticker: {event_date, days_until, eps_estimate}} for tickers
    with earnings within days_ahead days.
    """
    try:
        con = get_connection()
        today = datetime.now().date()
        cutoff = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        placeholders = ", ".join(["$" + str(i + 3) for i in range(len(tickers))])
        rows = con.execute(f"""
            SELECT ticker, event_date, eps_estimate
            FROM earnings_calendar
            WHERE event_type = 'earnings'
              AND event_date >= CAST($1 AS DATE)
              AND event_date <= CAST($2 AS DATE)
              AND ticker IN ({placeholders})
            ORDER BY event_date ASC
        """, [today_str, cutoff] + tickers).fetchall()
        con.close()

        result: dict[str, dict] = {}
        for r in rows:
            ticker = r[0]
            if ticker not in result:
                edate = r[1]
                if isinstance(edate, str):
                    edate = datetime.strptime(edate, "%Y-%m-%d").date()
                result[ticker] = {
                    "event_date": str(edate),
                    "days_until": (edate - today).days,
                    "eps_estimate": r[2],
                }
        return result
    except Exception:
        return {}


def get_recent_earnings_surprises(tickers: list[str], days_back: int = 30) -> list[dict]:
    """Get recent earnings beats/misses for a set of tickers.

    Returns list of {ticker, event_date, surprise_pct, eps_estimate, eps_actual}.
    """
    try:
        con = get_connection()
        cutoff = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        placeholders = ", ".join(["$" + str(i + 2) for i in range(len(tickers))])
        rows = con.execute(f"""
            SELECT ticker, event_date, surprise_pct, eps_estimate, eps_actual
            FROM earnings_calendar
            WHERE event_type = 'earnings'
              AND event_date >= CAST($1 AS DATE)
              AND eps_actual IS NOT NULL
              AND ticker IN ({placeholders})
            ORDER BY event_date DESC
        """, [cutoff] + tickers).fetchall()
        con.close()

        return [
            {"ticker": r[0], "event_date": str(r[1]), "surprise_pct": r[2],
             "eps_estimate": r[3], "eps_actual": r[4]}
            for r in rows
        ]
    except Exception:
        return []


def ingest_earnings_calendar(tickers: list[str] | None = None) -> None:
    """Full earnings calendar ingestion pipeline."""
    from src.db.schema import init_db
    init_db()

    should, reason = should_refresh_earnings()
    if not should:
        print(f"  Earnings calendar up-to-date: {reason}")
        return

    if tickers is None:
        from src.ingest.prices import load_universe
        tickers = load_universe()

    print(f"  Fetching earnings calendar for {len(tickers)} tickers...")
    df = fetch_earnings_calendar(tickers)
    if not df.empty:
        store_earnings_calendar(df)
    else:
        print("  No earnings data retrieved")


if __name__ == "__main__":
    ingest_earnings_calendar()
