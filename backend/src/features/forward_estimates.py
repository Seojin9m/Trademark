"""Forward estimate revision factor: analyst EPS revisions, forward P/E, price target upside.

Blends three sub-signals:
1. EPS revision momentum (40%) — are analysts raising or lowering estimates?
2. Forward P/E discount (30%) — forward P/E vs sector median, inverted
3. Price target upside (30%) — consensus target vs current price

Each sub-signal is z-scored cross-sectionally before blending.
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection
from config.settings import settings

SUB_SIGNAL_WEIGHTS = {
    "eps_revision": 0.40,
    "forward_pe_discount": 0.30,
    "price_target_upside": 0.30,
}


def _zscore(series: pd.Series) -> pd.Series:
    """Cross-sectional z-score with NaN tolerance."""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def compute_forward_estimate_factor(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute the forward_estimate_revision factor for all tickers.

    Returns DataFrame with columns: ticker, date, forward_estimate_revision
    """
    con = get_connection()

    if as_of_date is None:
        raw_max = con.execute("SELECT MAX(fetch_date) FROM forward_estimates").fetchone()[0]
        if raw_max is None:
            con.close()
            return pd.DataFrame(columns=["ticker", "date", "forward_estimate_revision"])
        as_of_date = raw_max if isinstance(raw_max, str) else str(raw_max)

    latest = con.execute("""
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) AS rn
            FROM forward_estimates
            WHERE fetch_date <= CAST($1 AS DATE)
        )
        SELECT ticker, fetch_date, eps_est_next_y, num_analysts,
               price_target_mean, price_target_current
        FROM ranked WHERE rn = 1
    """, [as_of_date]).fetchdf()

    prior = con.execute("""
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) AS rn
            FROM forward_estimates
            WHERE fetch_date <= CAST($1 AS DATE) - INTERVAL 28 DAY
        )
        SELECT ticker, eps_est_next_y AS prior_eps_est_next_y
        FROM ranked WHERE rn = 1
    """, [as_of_date]).fetchdf()

    prices = con.execute("""
        WITH latest AS (
            SELECT ticker, adj_close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices
            WHERE date <= CAST($1 AS DATE) AND adj_close > 0
        )
        SELECT ticker, adj_close AS price FROM latest WHERE rn = 1
    """, [as_of_date]).fetchdf()

    universe = pd.read_csv(settings.paths.universe_path)
    sector_map = dict(zip(universe["ticker"], universe["sub_sector"]))

    con.close()

    if latest.empty:
        return pd.DataFrame(columns=["ticker", "date", "forward_estimate_revision"])

    df = latest.merge(prior, on="ticker", how="left")
    df = df.merge(prices, on="ticker", how="left")
    df["sub_sector"] = df["ticker"].map(sector_map)

    # --- Sub-signal 1: EPS revision momentum ---
    has_revision = (
        df["eps_est_next_y"].notna()
        & df["prior_eps_est_next_y"].notna()
        & (df["prior_eps_est_next_y"].abs() > 0.01)
    )
    df["eps_revision"] = np.nan
    df.loc[has_revision, "eps_revision"] = (
        (df.loc[has_revision, "eps_est_next_y"] - df.loc[has_revision, "prior_eps_est_next_y"])
        / df.loc[has_revision, "prior_eps_est_next_y"].abs()
    )
    df["eps_revision"] = df["eps_revision"].clip(-2.0, 2.0)

    # --- Sub-signal 2: Forward P/E discount vs sector ---
    has_fwd_pe = (
        df["eps_est_next_y"].notna()
        & (df["eps_est_next_y"] > 0.01)
        & df["price"].notna()
    )
    df["forward_pe"] = np.nan
    df.loc[has_fwd_pe, "forward_pe"] = (
        df.loc[has_fwd_pe, "price"] / df.loc[has_fwd_pe, "eps_est_next_y"]
    )
    df["forward_pe"] = df["forward_pe"].clip(0, 200)

    df["forward_pe_discount"] = np.nan
    for sector in df["sub_sector"].dropna().unique():
        mask = (df["sub_sector"] == sector) & df["forward_pe"].notna()
        if mask.sum() < 3:
            continue
        sector_median = df.loc[mask, "forward_pe"].median()
        if sector_median > 0:
            df.loc[mask, "forward_pe_discount"] = -(
                np.log(df.loc[mask, "forward_pe"]) - np.log(sector_median)
            )
    df["forward_pe_discount"] = df["forward_pe_discount"].clip(-3.0, 3.0)

    # --- Sub-signal 3: Price target upside ---
    has_target = (
        df["price_target_mean"].notna()
        & df["price"].notna()
        & (df["price"] > 0)
    )
    df["price_target_upside"] = np.nan
    df.loc[has_target, "price_target_upside"] = (
        (df.loc[has_target, "price_target_mean"] - df.loc[has_target, "price"])
        / df.loc[has_target, "price"]
    )
    df["price_target_upside"] = df["price_target_upside"].clip(-1.0, 1.0)

    # --- Blend sub-signals ---
    sub_signals = ["eps_revision", "forward_pe_discount", "price_target_upside"]
    weights = [SUB_SIGNAL_WEIGHTS[s] for s in sub_signals]

    for col in sub_signals:
        valid = df[col].notna()
        if valid.sum() >= 3:
            df.loc[valid, col + "_z"] = _zscore(df.loc[valid, col])
        else:
            df[col + "_z"] = np.nan

    z_cols = [s + "_z" for s in sub_signals]
    df["forward_estimate_revision"] = np.nan

    for idx in df.index:
        vals = []
        w = []
        for z_col, weight in zip(z_cols, weights):
            v = df.loc[idx, z_col]
            if pd.notna(v):
                vals.append(v)
                w.append(weight)
        if vals:
            total_w = sum(w)
            df.loc[idx, "forward_estimate_revision"] = sum(
                v * wi / total_w for v, wi in zip(vals, w)
            )

    result = df[["ticker"]].copy()
    result["date"] = as_of_date
    result["forward_estimate_revision"] = df["forward_estimate_revision"]

    return result[["ticker", "date", "forward_estimate_revision"]].reset_index(drop=True)


if __name__ == "__main__":
    df = compute_forward_estimate_factor()
    if not df.empty:
        print(df.sort_values("forward_estimate_revision", ascending=False).head(20))
    else:
        print("No forward estimate data available")
