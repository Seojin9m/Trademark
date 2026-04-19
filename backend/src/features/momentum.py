"""Price momentum factor: 12M-1M trend momentum + recent price dip signal.

12M-1M captures medium-term trend (Jegadeesh & Titman, 1993).
Recent dip signal identifies stocks whose short-term price has fallen,
which — for fundamentally good stocks — represents a buying opportunity
rather than a negative signal. This avoids pure price-chasing.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection


def compute_momentum(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute 12M-1M momentum and recent price change for all tickers.

    Returns DataFrame with columns:
        ticker, date, momentum_12m1m, recent_price_change, price_dip_score
    """
    con = get_connection()

    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]

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
            MAX(CASE WHEN rn = 5 THEN adj_close END) as price_1w,
            MAX(CASE WHEN rn = 21 THEN adj_close END) as price_1m,
            MAX(CASE WHEN rn = 63 THEN adj_close END) as price_3m,
            MAX(CASE WHEN rn = 252 THEN adj_close END) as price_12m
        FROM ranked
        WHERE rn IN (1, 5, 21, 63, 252)
        GROUP BY ticker
    """, [str(as_of_date)]).fetchdf()
    con.close()

    if prices.empty:
        return pd.DataFrame(columns=["ticker", "date", "momentum_12m1m", "recent_price_change", "price_dip_score"])

    # 12M-1M momentum (medium-term trend, excludes recent month)
    prices["momentum_12m1m"] = (prices["price_1m"] / prices["price_12m"]) - 1.0

    # Recent price change: how much has the price moved in the last month
    prices["recent_price_change"] = (prices["price_now"] / prices["price_1m"]) - 1.0

    # Price dip score: positive when price has recently fallen (opportunity).
    # A stock that dropped 10% in the last month gets a dip score of +0.10.
    # A stock that rose 10% gets a dip score of -0.10 (penalized for chase risk).
    # This score is only meaningful when combined with quality assessment.
    prices["price_dip_score"] = -prices["recent_price_change"]
    prices["price_dip_score"] = np.clip(prices["price_dip_score"], -0.3, 0.3)

    valid = prices.dropna(subset=["momentum_12m1m"])
    result = valid[["ticker"]].copy()
    result["momentum_12m1m"] = valid["momentum_12m1m"]
    result["recent_price_change"] = valid["recent_price_change"]
    result["price_dip_score"] = valid["price_dip_score"]
    result["date"] = as_of_date

    return result[["ticker", "date", "momentum_12m1m", "recent_price_change", "price_dip_score"]].reset_index(drop=True)


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
