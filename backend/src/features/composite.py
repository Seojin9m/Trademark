"""Composite factor scoring: z-score, winsorize, and combine all factors."""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.features.momentum import compute_momentum
from src.features.quality import (
    compute_eps_growth,
    compute_revenue_growth,
    compute_gross_margin_trend,
)
from src.features.valuation import compute_relative_valuation


FACTOR_COLUMNS = [
    "momentum_12m1m",
    "eps_growth_yoy",
    "revenue_growth_yoy",
    "gross_margin_trend",
    "relative_valuation",
]


def winsorize(series: pd.Series, n_std: float = 3.0) -> pd.Series:
    """Winsorize a series at +/- n standard deviations."""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return series
    lower = mean - n_std * std
    upper = mean + n_std * std
    return series.clip(lower, upper)


def cross_sectional_zscore(series: pd.Series) -> pd.Series:
    """Z-score a series cross-sectionally (mean=0, std=1)."""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def compute_composite_scores(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute all factors and combine into a composite score for one date.

    Steps:
    1. Compute each factor independently
    2. Merge all factors (outer join - tickers may be missing some factors)
    3. Winsorize each factor at +/- 3 std
    4. Z-score each factor cross-sectionally
    5. Weighted sum -> composite score
    6. Assign deciles (1=worst, 10=best)
    """
    # Step 1: Compute each factor
    mom = compute_momentum(as_of_date)
    eps = compute_eps_growth(as_of_date)
    rev = compute_revenue_growth(as_of_date)
    gm = compute_gross_margin_trend(as_of_date)
    val = compute_relative_valuation(as_of_date)

    # Resolve as_of_date from momentum (it queries DB for max date)
    if not mom.empty:
        as_of_date = mom["date"].iloc[0]

    # Step 2: Merge all factors
    factors = mom[["ticker", "momentum_12m1m"]].copy()

    for df, col in [
        (eps, "eps_growth_yoy"),
        (rev, "revenue_growth_yoy"),
        (gm, "gross_margin_trend"),
        (val, "relative_valuation"),
    ]:
        if not df.empty:
            factors = factors.merge(df[["ticker", col]], on="ticker", how="outer")

    if factors.empty:
        return pd.DataFrame()

    # Step 3: Winsorize each factor
    win_std = settings.strategy.winsorize_std
    for col in FACTOR_COLUMNS:
        if col in factors.columns:
            factors[col] = winsorize(factors[col].astype(float), n_std=win_std)

    # Step 4: Z-score each factor cross-sectionally
    z_cols = {}
    for col in FACTOR_COLUMNS:
        if col in factors.columns:
            z_cols[col] = cross_sectional_zscore(factors[col])
        else:
            z_cols[col] = pd.Series(0.0, index=factors.index)

    # Step 5: Weighted sum
    weights = settings.strategy.factor_weights
    factors["composite_score"] = sum(
        z_cols[col] * weights.get(col, 0.0) for col in FACTOR_COLUMNS
    )

    # Fill NaN composite scores with 0 (neutral)
    factors["composite_score"] = factors["composite_score"].fillna(0.0)

    # Step 6: Assign deciles (1=worst, 10=best)
    # Use rank-based percentile to avoid qcut bin-edge issues
    ranks = factors["composite_score"].rank(method="first", pct=True)
    factors["score_decile"] = np.ceil(ranks * 10).clip(1, 10).astype(int)

    factors["date"] = as_of_date

    # Write z-scored values back for transparency
    for col in FACTOR_COLUMNS:
        if col in z_cols:
            factors[col] = z_cols[col]

    return factors[
        ["ticker", "date"] + FACTOR_COLUMNS + ["composite_score", "score_decile"]
    ].reset_index(drop=True)


def compute_composite_historical(
    start_date: str = "2021-06-01",
    end_date: str | None = None,
    freq: str = "W-FRI",
) -> pd.DataFrame:
    """Compute composite scores for all rebalance dates in range."""
    from src.db.schema import get_connection

    con = get_connection()
    if end_date is None:
        end_date = str(con.execute("SELECT MAX(date) FROM prices").fetchone()[0])

    trading_dates = con.execute("""
        SELECT DISTINCT date FROM prices
        WHERE date BETWEEN $1 AND $2
        ORDER BY date
    """, [start_date, end_date]).fetchdf()
    con.close()

    if trading_dates.empty:
        return pd.DataFrame()

    # Resample to weekly
    trading_dates["date"] = pd.to_datetime(trading_dates["date"])
    rebalance_dates = (
        trading_dates.set_index("date")
        .resample(freq)
        .last()
        .dropna()
        .index
    )

    all_trading = set(trading_dates["date"].dt.date)
    actual_dates = []
    for d in rebalance_dates:
        d_date = d.date()
        candidates = [t for t in all_trading if t <= d_date]
        if candidates:
            actual_dates.append(max(candidates))

    results = []
    total = len(actual_dates)
    for i, d in enumerate(actual_dates):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"  Computing scores for {d} ({i + 1}/{total})...")
        try:
            df = compute_composite_scores(str(d))
            if not df.empty:
                results.append(df)
        except Exception as e:
            print(f"  WARNING: Failed for {d}: {e}")
            continue

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)
