"""Relative valuation factor: P/S vs. sub-sector peers + P/E ratio filtering.

Lower P/S relative to peers = cheaper = higher factor score.
Inverted so that "cheap" stocks get a high (positive) z-score.
P/E filtering removes stocks with excessive absolute or relative PER.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection
from config.settings import settings


_val_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}

def _get_price_and_fundamentals(as_of_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Shared data fetch for valuation computations."""
    if as_of_date in _val_cache:
        p, f = _val_cache[as_of_date]
        return p.copy(), f.copy()
    con = get_connection()

    prices = con.execute("""
        WITH latest AS (
            SELECT ticker, adj_close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM prices
            WHERE date <= CAST($1 AS DATE) AND adj_close > 0
        )
        SELECT ticker, adj_close as price FROM latest WHERE rn = 1
    """, [str(as_of_date)]).fetchdf()

    fundamentals = con.execute("""
        WITH latest_quarters AS (
            SELECT ticker, revenue, net_income, shares_outstanding,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fiscal_period_end DESC) as rn
            FROM fundamentals_pit
            WHERE report_date <= CAST($1 AS DATE)
        ),
        ttm AS (
            SELECT
                ticker,
                SUM(revenue) as ttm_revenue,
                SUM(net_income) as ttm_net_income,
                MAX(CASE WHEN rn = 1 THEN shares_outstanding END) as shares
            FROM latest_quarters
            WHERE rn <= 4
            GROUP BY ticker
            HAVING COUNT(*) = 4
        )
        SELECT * FROM ttm
    """, [str(as_of_date)]).fetchdf()
    con.close()

    _val_cache[as_of_date] = (prices, fundamentals)
    return prices.copy(), fundamentals.copy()


def compute_relative_valuation(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute relative P/S valuation for all tickers vs sub-sector median.

    Returns inverted score: negative P/S z-score (cheap = positive).
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()
        if as_of_date is None:
            return pd.DataFrame(columns=["ticker", "date", "relative_valuation"])

    prices, fundamentals = _get_price_and_fundamentals(str(as_of_date))

    if prices.empty or fundamentals.empty:
        return pd.DataFrame(columns=["ticker", "date", "relative_valuation"])

    merged = prices.merge(fundamentals, on="ticker", how="inner")
    merged = merged[merged["shares"] > 0]
    merged = merged[merged["ttm_revenue"] > 0]

    merged["market_cap"] = merged["price"] * merged["shares"]
    merged["ps_ratio"] = merged["market_cap"] / merged["ttm_revenue"]

    universe = pd.read_csv(settings.paths.universe_path)
    merged = merged.merge(universe[["ticker", "sub_sector"]], on="ticker", how="left")

    sector_medians = merged.groupby("sub_sector")["ps_ratio"].median().rename("sector_median_ps")
    merged = merged.merge(sector_medians, on="sub_sector", how="left")

    merged["relative_valuation"] = -(
        np.log(merged["ps_ratio"]) - np.log(merged["sector_median_ps"])
    )

    merged["relative_valuation"] = np.clip(merged["relative_valuation"], -3.0, 3.0)

    result = merged[["ticker"]].copy()
    result["relative_valuation"] = merged["relative_valuation"]
    result["date"] = as_of_date

    return result[["ticker", "date", "relative_valuation"]].reset_index(drop=True)


def compute_per_filter(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute P/E ratio and filter stocks with excessive valuations.

    Returns DataFrame with columns:
        ticker, date, per_ratio, per_vs_peer, per_absolute_pass, per_relative_pass, per_penalty

    Filtering logic:
    - per_absolute_pass = False if PER > max_absolute_per (default 40)
    - per_relative_pass = False if PER > max_relative_per_vs_peer * sector_median_per
    - per_penalty: negative score applied to stocks failing either check
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()
        if as_of_date is None:
            return pd.DataFrame(
                columns=[
                    "ticker",
                    "date",
                    "per_ratio",
                    "per_vs_peer",
                    "per_absolute_pass",
                    "per_relative_pass",
                    "per_penalty",
                ]
            )

    prices, fundamentals = _get_price_and_fundamentals(str(as_of_date))

    if prices.empty or fundamentals.empty:
        return pd.DataFrame(columns=[
            "ticker", "date", "per_ratio", "per_vs_peer",
            "per_absolute_pass", "per_relative_pass", "per_penalty",
        ])

    merged = prices.merge(fundamentals, on="ticker", how="inner")
    merged = merged[merged["shares"] > 0]

    # Compute P/E ratio: price / (TTM EPS)
    # TTM EPS = TTM net income / shares outstanding
    merged["ttm_eps"] = merged["ttm_net_income"] / merged["shares"]
    # Only compute PER for profitable companies (positive TTM EPS)
    merged = merged[merged["ttm_eps"] > 0.01].copy()
    merged["per_ratio"] = merged["price"] / merged["ttm_eps"]

    if merged.empty:
        return pd.DataFrame(columns=[
            "ticker", "date", "per_ratio", "per_vs_peer",
            "per_absolute_pass", "per_relative_pass", "per_penalty",
        ])

    universe = pd.read_csv(settings.paths.universe_path)
    merged = merged.merge(universe[["ticker", "sub_sector"]], on="ticker", how="left")

    # Compute peer median PER
    sector_median_per = merged.groupby("sub_sector")["per_ratio"].median().rename("sector_median_per")
    merged = merged.merge(sector_median_per, on="sub_sector", how="left")

    merged["per_vs_peer"] = merged["per_ratio"] / merged["sector_median_per"].replace(0, np.nan)

    max_abs = settings.strategy.max_absolute_per
    max_rel = settings.strategy.max_relative_per_vs_peer

    merged["per_absolute_pass"] = merged["per_ratio"] <= max_abs
    merged["per_relative_pass"] = merged["per_vs_peer"] <= max_rel

    # Penalty: 0 if both pass, graduated negative if either fails.
    # Penalty is softened (2x denominator) so high-growth stocks with
    # strong quality factors can still qualify as "good stocks."
    merged["per_penalty"] = 0.0
    abs_fail = ~merged["per_absolute_pass"]
    rel_fail = ~merged["per_relative_pass"]
    merged.loc[abs_fail, "per_penalty"] -= np.clip(
        (merged.loc[abs_fail, "per_ratio"] - max_abs) / (2 * max_abs), 0, 1.0
    )
    merged.loc[rel_fail, "per_penalty"] -= np.clip(
        (merged.loc[rel_fail, "per_vs_peer"] - max_rel) / (2 * max_rel), 0, 0.75
    )

    result = merged[["ticker"]].copy()
    result["date"] = as_of_date
    result["per_ratio"] = merged["per_ratio"]
    result["per_vs_peer"] = merged["per_vs_peer"]
    result["per_absolute_pass"] = merged["per_absolute_pass"]
    result["per_relative_pass"] = merged["per_relative_pass"]
    result["per_penalty"] = merged["per_penalty"]

    return result.reset_index(drop=True)
