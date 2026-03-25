"""Quality/Growth factors: EPS growth (TTM YoY), Revenue growth (YoY), Gross margin trend.

All factors use PIT-safe fundamentals (report_date, not fiscal_period_end).
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection


def _get_pit_fundamentals(as_of_date: str) -> pd.DataFrame:
    """Get the most recent PIT-safe fundamentals for each ticker.

    Only includes data that was publicly available as of as_of_date.
    Returns the last 8 quarters per ticker for TTM computation.
    """
    con = get_connection()
    df = con.execute("""
        WITH ranked AS (
            SELECT
                ticker,
                fiscal_period_end,
                report_date,
                revenue,
                gross_profit,
                net_income,
                eps_diluted,
                shares_outstanding,
                ROW_NUMBER() OVER (
                    PARTITION BY ticker
                    ORDER BY fiscal_period_end DESC
                ) as quarter_rank
            FROM fundamentals_pit
            WHERE report_date <= CAST($1 AS DATE)
        )
        SELECT * FROM ranked
        WHERE quarter_rank <= 8
        ORDER BY ticker, fiscal_period_end
    """, [str(as_of_date)]).fetchdf()
    con.close()
    return df


def _compute_ttm(df: pd.DataFrame, column: str) -> pd.Series:
    """Compute trailing twelve months (sum of last 4 quarters)."""
    return df.groupby("ticker")[column].transform(
        lambda x: x.rolling(4, min_periods=4).sum()
    )


def compute_eps_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute EPS growth (TTM YoY) for all tickers.

    TTM EPS now / TTM EPS 4 quarters ago - 1.
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()

    fund = _get_pit_fundamentals(str(as_of_date))
    if fund.empty:
        return pd.DataFrame(columns=["ticker", "date", "eps_growth_yoy"])

    # Need at least 8 quarters (4 for current TTM + 4 for prior TTM)
    fund = fund.sort_values(["ticker", "fiscal_period_end"])

    results = []
    for ticker, group in fund.groupby("ticker"):
        if len(group) < 8:
            continue

        # TTM EPS = sum of last 4 quarters' net_income / latest shares
        recent_4 = group.tail(4)
        prior_4 = group.head(4)

        ttm_eps_now = recent_4["eps_diluted"].sum()
        ttm_eps_prior = prior_4["eps_diluted"].sum()

        if ttm_eps_prior is not None and abs(ttm_eps_prior) > 0.01:
            eps_growth = (ttm_eps_now / ttm_eps_prior) - 1.0
            # Cap extreme values
            eps_growth = np.clip(eps_growth, -5.0, 10.0)
            results.append({"ticker": ticker, "eps_growth_yoy": eps_growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "eps_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "eps_growth_yoy"]]


def compute_revenue_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute revenue growth (TTM YoY) for all tickers."""
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()

    fund = _get_pit_fundamentals(str(as_of_date))
    if fund.empty:
        return pd.DataFrame(columns=["ticker", "date", "revenue_growth_yoy"])

    fund = fund.sort_values(["ticker", "fiscal_period_end"])

    results = []
    for ticker, group in fund.groupby("ticker"):
        if len(group) < 8:
            continue

        recent_4 = group.tail(4)
        prior_4 = group.head(4)

        ttm_rev_now = recent_4["revenue"].sum()
        ttm_rev_prior = prior_4["revenue"].sum()

        if ttm_rev_prior is not None and ttm_rev_prior > 0:
            rev_growth = (ttm_rev_now / ttm_rev_prior) - 1.0
            rev_growth = np.clip(rev_growth, -2.0, 10.0)
            results.append({"ticker": ticker, "revenue_growth_yoy": rev_growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "revenue_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "revenue_growth_yoy"]]


def compute_gross_margin_trend(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute gross margin trend: current TTM gross margin minus prior year TTM.

    Positive = margin expanding (good). Negative = margin compressing.
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()

    fund = _get_pit_fundamentals(str(as_of_date))
    if fund.empty:
        return pd.DataFrame(columns=["ticker", "date", "gross_margin_trend"])

    fund = fund.sort_values(["ticker", "fiscal_period_end"])

    results = []
    for ticker, group in fund.groupby("ticker"):
        if len(group) < 8:
            continue

        recent_4 = group.tail(4)
        prior_4 = group.head(4)

        rev_now = recent_4["revenue"].sum()
        gp_now = recent_4["gross_profit"].sum()
        rev_prior = prior_4["revenue"].sum()
        gp_prior = prior_4["gross_profit"].sum()

        if rev_now > 0 and rev_prior > 0:
            gm_now = gp_now / rev_now
            gm_prior = gp_prior / rev_prior
            gm_trend = gm_now - gm_prior  # In percentage points
            gm_trend = np.clip(gm_trend, -0.5, 0.5)
            results.append({"ticker": ticker, "gross_margin_trend": gm_trend})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "gross_margin_trend"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "gross_margin_trend"]]
