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


# Minimum quarters needed to compute YoY at all (Q0 vs Q-4 requires 5 rows).
# Threshold for switching from single-quarter YoY to TTM-on-TTM smoothing.
_MIN_QUARTERS_SINGLE_Q = 5
_MIN_QUARTERS_TTM = 8


def compute_eps_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute EPS growth YoY for all tickers.

    Uses TTM-on-TTM (sum of last 4q vs prior 4q) when 8+ quarters are
    available — smoother and resistant to one-off quarterly noise. Falls
    back to single-quarter YoY (Q0 vs Q-4) when only 5-7 quarters exist,
    which is the case for yfinance-sourced tickers (Yahoo only exposes ~6q).
    Same underlying measurement (same calendar quarter year-over-year),
    just noisier without the TTM smoothing.
    """
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()

    fund = _get_pit_fundamentals(str(as_of_date))
    if fund.empty:
        return pd.DataFrame(columns=["ticker", "date", "eps_growth_yoy"])

    fund = fund.sort_values(["ticker", "fiscal_period_end"])

    results = []
    for ticker, group in fund.groupby("ticker"):
        n = len(group)
        growth = None

        if n >= _MIN_QUARTERS_TTM:
            recent_4 = group.tail(4)
            prior_4 = group.head(4)
            ttm_now = recent_4["eps_diluted"].sum()
            ttm_prior = prior_4["eps_diluted"].sum()
            if pd.notna(ttm_prior) and abs(ttm_prior) > 0.01:
                growth = (ttm_now / ttm_prior) - 1.0
        elif n >= _MIN_QUARTERS_SINGLE_Q:
            q0 = group.iloc[-1]["eps_diluted"]
            q_prior = group.iloc[-5]["eps_diluted"]
            if pd.notna(q0) and pd.notna(q_prior) and abs(q_prior) > 0.01:
                growth = (q0 / q_prior) - 1.0

        if growth is not None:
            growth = float(np.clip(growth, -5.0, 10.0))
            results.append({"ticker": ticker, "eps_growth_yoy": growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "eps_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "eps_growth_yoy"]]


def compute_revenue_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute revenue growth YoY for all tickers.

    Same TTM-or-single-Q hybrid logic as compute_eps_growth — see that
    docstring for the rationale.
    """
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
        n = len(group)
        growth = None

        if n >= _MIN_QUARTERS_TTM:
            recent_4 = group.tail(4)
            prior_4 = group.head(4)
            ttm_now = recent_4["revenue"].sum()
            ttm_prior = prior_4["revenue"].sum()
            if pd.notna(ttm_prior) and ttm_prior > 0:
                growth = (ttm_now / ttm_prior) - 1.0
        elif n >= _MIN_QUARTERS_SINGLE_Q:
            q0 = group.iloc[-1]["revenue"]
            q_prior = group.iloc[-5]["revenue"]
            if pd.notna(q0) and pd.notna(q_prior) and q_prior > 0:
                growth = (q0 / q_prior) - 1.0

        if growth is not None:
            growth = float(np.clip(growth, -2.0, 10.0))
            results.append({"ticker": ticker, "revenue_growth_yoy": growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "revenue_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "revenue_growth_yoy"]]


def compute_gross_margin_trend(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute gross margin trend: current gross margin minus year-ago margin.

    Positive = margin expanding (good). Negative = margin compressing.
    Uses TTM gross margins when 8+ quarters available, otherwise single
    quarter gross margins (Q0 vs Q-4). Banks and insurance don't report
    gross profit, so this stays NaN for them — handled downstream.
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
        n = len(group)
        gm_trend = None

        if n >= _MIN_QUARTERS_TTM:
            recent_4 = group.tail(4)
            prior_4 = group.head(4)
            rev_now = recent_4["revenue"].sum()
            gp_now = recent_4["gross_profit"].sum()
            rev_prior = prior_4["revenue"].sum()
            gp_prior = prior_4["gross_profit"].sum()
            if (pd.notna(gp_now) and pd.notna(gp_prior)
                    and rev_now > 0 and rev_prior > 0):
                gm_trend = (gp_now / rev_now) - (gp_prior / rev_prior)
        elif n >= _MIN_QUARTERS_SINGLE_Q:
            q0 = group.iloc[-1]
            q_prior = group.iloc[-5]
            rev_now = q0["revenue"]
            gp_now = q0["gross_profit"]
            rev_prior = q_prior["revenue"]
            gp_prior = q_prior["gross_profit"]
            if (pd.notna(gp_now) and pd.notna(gp_prior)
                    and pd.notna(rev_now) and pd.notna(rev_prior)
                    and rev_now > 0 and rev_prior > 0):
                gm_trend = (gp_now / rev_now) - (gp_prior / rev_prior)

        if gm_trend is not None:
            gm_trend = float(np.clip(gm_trend, -0.5, 0.5))
            results.append({"ticker": ticker, "gross_margin_trend": gm_trend})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "gross_margin_trend"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "gross_margin_trend"]]
