"""Relative valuation factor: Price-to-Sales (P/S) vs. sub-sector peers.

Lower P/S relative to peers = cheaper = higher factor score.
Inverted so that "cheap" stocks get a high (positive) z-score.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection
from config.settings import settings


def compute_relative_valuation(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute relative P/S valuation for all tickers vs sub-sector median.

    Returns inverted score: negative P/S z-score (cheap = positive).
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]

    # Get latest prices
    prices = con.execute("""
        WITH latest AS (
            SELECT ticker, adj_close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM prices
            WHERE date <= CAST($1 AS DATE) AND adj_close > 0
        )
        SELECT ticker, adj_close as price FROM latest WHERE rn = 1
    """, [str(as_of_date)]).fetchdf()

    # Get TTM revenue and shares outstanding (PIT-safe)
    fundamentals = con.execute("""
        WITH latest_quarters AS (
            SELECT ticker, revenue, shares_outstanding,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fiscal_period_end DESC) as rn
            FROM fundamentals_pit
            WHERE report_date <= CAST($1 AS DATE)
        ),
        ttm AS (
            SELECT
                ticker,
                SUM(revenue) as ttm_revenue,
                MAX(CASE WHEN rn = 1 THEN shares_outstanding END) as shares
            FROM latest_quarters
            WHERE rn <= 4
            GROUP BY ticker
            HAVING COUNT(*) = 4
        )
        SELECT * FROM ttm
    """, [str(as_of_date)]).fetchdf()
    con.close()

    if prices.empty or fundamentals.empty:
        return pd.DataFrame(columns=["ticker", "date", "relative_valuation"])

    # Merge price + fundamentals
    merged = prices.merge(fundamentals, on="ticker", how="inner")
    merged = merged[merged["shares"] > 0]
    merged = merged[merged["ttm_revenue"] > 0]

    # Market cap = price * shares, P/S = market cap / TTM revenue
    merged["market_cap"] = merged["price"] * merged["shares"]
    merged["ps_ratio"] = merged["market_cap"] / merged["ttm_revenue"]

    # Load sub-sector mapping
    universe = pd.read_csv(settings.paths.universe_path)
    merged = merged.merge(universe[["ticker", "sub_sector"]], on="ticker", how="left")

    # Compute P/S relative to sub-sector median
    sector_medians = merged.groupby("sub_sector")["ps_ratio"].median().rename("sector_median_ps")
    merged = merged.merge(sector_medians, on="sub_sector", how="left")

    # Relative valuation: log(P/S) - log(sector median P/S)
    # Inverted: cheap stocks (low P/S) get positive score
    merged["relative_valuation"] = -(
        np.log(merged["ps_ratio"]) - np.log(merged["sector_median_ps"])
    )

    # Cap extreme values
    merged["relative_valuation"] = np.clip(merged["relative_valuation"], -3.0, 3.0)

    result = merged[["ticker"]].copy()
    result["relative_valuation"] = merged["relative_valuation"]
    result["date"] = as_of_date

    return result[["ticker", "date", "relative_valuation"]].reset_index(drop=True)
