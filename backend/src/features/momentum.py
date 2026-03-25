"""Price momentum factor: 12-month return minus 1-month return (12M-1M).

Classic cross-sectional momentum signal. Excludes the most recent month
to avoid the short-term reversal effect (Jegadeesh & Titman, 1993).
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection


def compute_momentum(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute 12M-1M momentum for all tickers as of a given date.

    Returns DataFrame with columns: ticker, date, momentum_12m1m
    """
    con = get_connection()

    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]

    # Get prices for the relevant lookback windows
    # 12M-1M: return from 252 trading days ago to 21 trading days ago
    prices = con.execute("""
        WITH ranked AS (
            SELECT
                ticker,
                date,
                adj_close,
                ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM prices
            WHERE date <= CAST($1 AS DATE)
              AND adj_close IS NOT NULL
              AND adj_close > 0
        )
        SELECT
            ticker,
            MAX(CASE WHEN rn = 1 THEN adj_close END) as price_now,
            MAX(CASE WHEN rn = 21 THEN adj_close END) as price_1m,
            MAX(CASE WHEN rn = 252 THEN adj_close END) as price_12m
        FROM ranked
        WHERE rn IN (1, 21, 252)
        GROUP BY ticker
    """, [str(as_of_date)]).fetchdf()
    con.close()

    if prices.empty:
        return pd.DataFrame(columns=["ticker", "date", "momentum_12m1m"])

    # 12M-1M momentum: return from 12 months ago to 1 month ago
    prices["momentum_12m1m"] = (prices["price_1m"] / prices["price_12m"]) - 1.0

    # Drop tickers missing either price point
    result = prices.dropna(subset=["momentum_12m1m"])[["ticker"]].copy()
    result["momentum_12m1m"] = prices.dropna(subset=["momentum_12m1m"])["momentum_12m1m"]
    result["date"] = as_of_date

    return result[["ticker", "date", "momentum_12m1m"]].reset_index(drop=True)


def compute_momentum_historical(
    start_date: str = "2017-01-01",
    end_date: str | None = None,
    freq: str = "W-FRI",
) -> pd.DataFrame:
    """Compute momentum for all rebalance dates in range.

    Computes weekly (Friday) momentum scores for backtesting.
    """
    con = get_connection()

    if end_date is None:
        end_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]

    # Get all trading dates
    trading_dates = con.execute("""
        SELECT DISTINCT date FROM prices
        WHERE date BETWEEN $1 AND $2
        ORDER BY date
    """, [start_date, str(end_date)]).fetchdf()
    con.close()

    if trading_dates.empty:
        return pd.DataFrame()

    # Resample to weekly frequency
    trading_dates["date"] = pd.to_datetime(trading_dates["date"])
    rebalance_dates = (
        trading_dates.set_index("date")
        .resample(freq)
        .last()
        .dropna()
        .index
    )

    # Get the actual closest trading dates
    all_trading = set(trading_dates["date"].dt.date)
    actual_dates = []
    for d in rebalance_dates:
        d_date = d.date()
        # Find the closest trading date on or before
        candidates = [t for t in all_trading if t <= d_date]
        if candidates:
            actual_dates.append(max(candidates))

    results = []
    for d in actual_dates:
        df = compute_momentum(str(d))
        if not df.empty:
            results.append(df)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)
