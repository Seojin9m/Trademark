"""Quality/Growth factors: EPS growth, Revenue growth, Gross margin trend.

Uses recent 2-4 quarters only to detect whether the company is improving
recently, rather than diluting the signal with old data.
All factors use PIT-safe fundamentals (report_date, not fiscal_period_end).
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection
from config.settings import settings


_pit_cache: dict[str, pd.DataFrame] = {}

def _get_pit_fundamentals(as_of_date: str, max_quarters: int | None = None) -> pd.DataFrame:
    """Get the most recent PIT-safe fundamentals for each ticker.

    Only includes data that was publicly available as of as_of_date.
    Returns the last `max_quarters` quarters per ticker (default from settings).
    """
    if max_quarters is None:
        max_quarters = settings.strategy.quality_recent_quarters
    fetch_quarters = max_quarters + 4

    cache_key = f"{as_of_date}:{fetch_quarters}"
    if cache_key in _pit_cache:
        return _pit_cache[cache_key].copy()

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
        WHERE quarter_rank <= $2
        ORDER BY ticker, fiscal_period_end
    """, [str(as_of_date), fetch_quarters]).fetchdf()
    con.close()
    _pit_cache[cache_key] = df
    return df.copy()


def _compute_ttm(df: pd.DataFrame, column: str) -> pd.Series:
    """Compute trailing twelve months (sum of last 4 quarters)."""
    return df.groupby("ticker")[column].transform(
        lambda x: x.rolling(4, min_periods=4).sum()
    )


# With recent-quarter focus: need at least 2 quarters for sequential growth,
# and at least 4 quarters for YoY single-quarter comparison (Q0 vs Q-4).
_MIN_QUARTERS_SEQUENTIAL = 2
_MIN_QUARTERS_YOY = 4


def _compute_sequential_growth(group: pd.DataFrame, column: str) -> float | None:
    """Compute average sequential (QoQ) growth over recent quarters."""
    n = len(group)
    recent_n = min(n, settings.strategy.quality_recent_quarters)
    recent = group.tail(recent_n)

    vals = recent[column].dropna()
    if len(vals) < 2:
        return None

    growths = []
    for i in range(1, len(vals)):
        prev = vals.iloc[i - 1]
        curr = vals.iloc[i]
        if abs(prev) > 0.01:
            growths.append((curr / prev) - 1.0)

    if not growths:
        return None
    return float(np.mean(growths))


def compute_eps_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute EPS growth using recent 2-4 quarters.

    Primary: YoY single-quarter comparison (Q0 vs Q-4) when 4+ quarters exist.
    Fallback: sequential QoQ average growth when only 2-3 quarters available.
    Emphasizes recent improvement over long historical averages.
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

        if n >= _MIN_QUARTERS_YOY + 1:
            # YoY: compare most recent quarter to same quarter a year ago
            q0 = group.iloc[-1]["eps_diluted"]
            q_prior = group.iloc[-(settings.strategy.quality_recent_quarters + 1)]["eps_diluted"]
            if pd.notna(q0) and pd.notna(q_prior) and abs(q_prior) > 0.01:
                growth = (q0 / q_prior) - 1.0
        elif n >= _MIN_QUARTERS_SEQUENTIAL:
            growth = _compute_sequential_growth(group, "eps_diluted")

        if growth is not None:
            growth = float(np.clip(growth, -5.0, 10.0))
            results.append({"ticker": ticker, "eps_growth_yoy": growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "eps_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "eps_growth_yoy"]]


def compute_revenue_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute revenue growth using recent 2-4 quarters.

    Same recent-quarter logic as compute_eps_growth.
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

        if n >= _MIN_QUARTERS_YOY + 1:
            q0 = group.iloc[-1]["revenue"]
            q_prior = group.iloc[-(settings.strategy.quality_recent_quarters + 1)]["revenue"]
            if pd.notna(q0) and pd.notna(q_prior) and q_prior > 0:
                growth = (q0 / q_prior) - 1.0
        elif n >= _MIN_QUARTERS_SEQUENTIAL:
            growth = _compute_sequential_growth(group, "revenue")

        if growth is not None:
            growth = float(np.clip(growth, -2.0, 10.0))
            results.append({"ticker": ticker, "revenue_growth_yoy": growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "revenue_growth_yoy"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "revenue_growth_yoy"]]


def compute_gross_margin_trend(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute gross margin trend over recent 2-4 quarters.

    Compares most recent 2 quarters' average margin vs prior 2 quarters.
    Banks and insurance don't report gross profit — stays NaN for them.
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

        if n >= 4:
            # Compare recent 2 quarters vs prior 2 quarters
            recent_2 = group.tail(2)
            prior_2 = group.iloc[-(4):-(2)] if n >= 4 else group.head(2)
            rev_now = recent_2["revenue"].sum()
            gp_now = recent_2["gross_profit"].sum()
            rev_prior = prior_2["revenue"].sum()
            gp_prior = prior_2["gross_profit"].sum()
            if (pd.notna(gp_now) and pd.notna(gp_prior)
                    and rev_now > 0 and rev_prior > 0):
                gm_trend = (gp_now / rev_now) - (gp_prior / rev_prior)
        elif n >= 2:
            q0 = group.iloc[-1]
            q1 = group.iloc[-2]
            rev_now, gp_now = q0["revenue"], q0["gross_profit"]
            rev_prior, gp_prior = q1["revenue"], q1["gross_profit"]
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


def compute_net_income_growth(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute net income growth using recent 2-4 quarters."""
    con = get_connection()
    if as_of_date is None:
        as_of_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        con.close()

    fund = _get_pit_fundamentals(str(as_of_date))
    if fund.empty:
        return pd.DataFrame(columns=["ticker", "date", "net_income_growth"])

    fund = fund.sort_values(["ticker", "fiscal_period_end"])

    results = []
    for ticker, group in fund.groupby("ticker"):
        n = len(group)
        growth = None

        if n >= _MIN_QUARTERS_YOY + 1:
            q0 = group.iloc[-1]["net_income"]
            q_prior = group.iloc[-(settings.strategy.quality_recent_quarters + 1)]["net_income"]
            if pd.notna(q0) and pd.notna(q_prior) and abs(q_prior) > 1000:
                growth = (q0 / q_prior) - 1.0
        elif n >= _MIN_QUARTERS_SEQUENTIAL:
            growth = _compute_sequential_growth(group, "net_income")

        if growth is not None:
            growth = float(np.clip(growth, -5.0, 10.0))
            results.append({"ticker": ticker, "net_income_growth": growth})

    if not results:
        return pd.DataFrame(columns=["ticker", "date", "net_income_growth"])

    result = pd.DataFrame(results)
    result["date"] = as_of_date
    return result[["ticker", "date", "net_income_growth"]]
