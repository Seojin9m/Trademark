"""Two-stage composite scoring: quality-first assessment, then price-adjusted opportunity.

Stage 1: Evaluate fundamentals (quality, growth, valuation, PER) to determine
         whether each stock is a "good stock" candidate — BEFORE using price.
Stage 2: For good stocks, apply price dip/rise as a timing signal.
         Dip on a good stock = better opportunity. Rise on a good stock = watch/caution.
         Bad stocks are not rescued by price dips.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.features.momentum import compute_momentum, coerce_scoring_date
from src.features.quality import (
    compute_eps_growth,
    compute_revenue_growth,
    compute_gross_margin_trend,
)
from src.features.valuation import compute_relative_valuation, compute_per_filter
from src.features.forward_estimates import compute_forward_estimate_factor


FACTOR_COLUMNS = [
    "momentum_12m1m",
    "eps_growth_yoy",
    "revenue_growth_yoy",
    "gross_margin_trend",
    "relative_valuation",
    "forward_estimate_revision",
]

QUALITY_FACTOR_COLUMNS = [
    "eps_growth_yoy",
    "revenue_growth_yoy",
    "gross_margin_trend",
    "relative_valuation",
    "forward_estimate_revision",
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
    """Z-score a series cross-sectionally (mean=0, std=1). NaN inputs stay NaN."""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(np.nan, index=series.index, dtype=float)
    return (series - mean) / std


def sector_neutral_zscore(
    values: pd.Series,
    sectors: pd.Series,
    blend: float,
    min_group_size: int,
) -> pd.Series:
    """Blend of within-sector and global z-scores."""
    global_z = cross_sectional_zscore(values)
    if blend == 0.0:
        return global_z

    sector_z = pd.Series(np.nan, index=values.index, dtype=float)
    df = pd.DataFrame({"v": values, "s": sectors})
    for sector_name, group in df.groupby("s", dropna=False):
        idx = group.index
        if len(group) < min_group_size or pd.isna(sector_name):
            sector_z.loc[idx] = global_z.loc[idx]
            continue
        present = group["v"].notna()
        if present.sum() < 2:
            sector_z.loc[idx] = global_z.loc[idx]
            continue
        mean = group.loc[present, "v"].mean()
        std = group.loc[present, "v"].std()
        if std == 0 or pd.isna(std):
            sector_z.loc[group.index[present.values]] = 0.0
        else:
            sector_z.loc[idx] = (group["v"] - mean) / std

    if blend == 1.0:
        return sector_z
    return blend * sector_z + (1.0 - blend) * global_z


def _load_user_overrides(as_of_date: str) -> dict[tuple[str, str], float]:
    """Load user-corrected metric values from stock_metrics table."""
    from src.db.schema import get_connection
    try:
        con = get_connection()
        overrides = con.execute("""
            SELECT ticker, metric_name, user_value
            FROM stock_metrics
            WHERE user_value IS NOT NULL
              AND as_of_date = (
                  SELECT MAX(as_of_date) FROM stock_metrics
                  WHERE as_of_date <= CAST($1 AS DATE) AND user_value IS NOT NULL
              )
        """, [str(as_of_date)]).fetchdf()
        con.close()
        if overrides.empty:
            return {}
        return {
            (row["ticker"], row["metric_name"]): row["user_value"]
            for _, row in overrides.iterrows()
        }
    except Exception:
        return {}


def _apply_user_overrides(factors: pd.DataFrame, overrides: dict, as_of_date: str) -> pd.DataFrame:
    """Apply user-corrected values over raw computed values."""
    if not overrides:
        return factors

    for (ticker, metric), value in overrides.items():
        if metric in factors.columns:
            mask = factors["ticker"] == ticker
            if mask.any():
                factors.loc[mask, metric] = value
    return factors


def compute_composite_scores(
    as_of_date: str | None = None,
    factor_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Two-stage composite scoring.

    Stage 1: Compute quality score from fundamentals + valuation + PER filter.
             Determine is_good_stock before considering price movement.
    Stage 2: For good stocks, apply price dip as opportunity bonus.
             For bad stocks, price dip does NOT improve score.
             Price rise penalizes buy urgency (avoids chasing).

    Args:
        as_of_date: Scoring date. Defaults to latest available.
        factor_weights: IC-optimized weights from adaptive analysis.
                        Falls back to settings.strategy.factor_weights if None.
    """
    # Regime-adaptive momentum: shorter lookback in high-vol markets
    long_anchor = 252
    try:
        from src.learning.adaptive import detect_regime
        regime = detect_regime()
        if regime["vol_regime"] == "HIGH_VOL":
            long_anchor = 126
    except Exception:
        pass

    # Step 1: Compute each factor
    mom = compute_momentum(as_of_date, long_anchor=long_anchor)
    eps = compute_eps_growth(as_of_date)
    rev = compute_revenue_growth(as_of_date)
    gm = compute_gross_margin_trend(as_of_date)
    val = compute_relative_valuation(as_of_date)
    per = compute_per_filter(as_of_date)
    fwd = compute_forward_estimate_factor(as_of_date)

    if not mom.empty:
        as_of_date = mom["date"].iloc[0]

    as_of_date = coerce_scoring_date(as_of_date)
    if as_of_date is None:
        from src.db.schema import get_connection
        _con = get_connection()
        _mx = _con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        _con.close()
        as_of_date = coerce_scoring_date(_mx)
    if as_of_date is None:
        return pd.DataFrame()

    # Step 2: Merge all factors
    factors = mom[["ticker", "momentum_12m1m", "recent_price_change", "price_dip_score"]].copy()

    for df, col in [
        (eps, "eps_growth_yoy"),
        (rev, "revenue_growth_yoy"),
        (gm, "gross_margin_trend"),
        (val, "relative_valuation"),
        (fwd, "forward_estimate_revision"),
    ]:
        if not df.empty:
            factors = factors.merge(df[["ticker", col]], on="ticker", how="outer")

    # Merge PER filter data
    if not per.empty:
        factors = factors.merge(
            per[["ticker", "per_ratio", "per_vs_peer", "per_absolute_pass",
                 "per_relative_pass", "per_penalty"]],
            on="ticker", how="left"
        )
    else:
        factors["per_ratio"] = np.nan
        factors["per_vs_peer"] = np.nan
        factors["per_absolute_pass"] = True
        factors["per_relative_pass"] = True
        factors["per_penalty"] = 0.0

    if factors.empty:
        return pd.DataFrame()

    # Step 2b: Apply user-corrected values from DB
    overrides = _load_user_overrides(str(as_of_date))
    factors = _apply_user_overrides(factors, overrides, str(as_of_date))

    # Merge in sub_sector
    universe = pd.read_csv(settings.paths.universe_path)
    factors = factors.merge(
        universe[["ticker", "sub_sector"]], on="ticker", how="left"
    )

    # Step 3: Winsorize each factor
    win_std = settings.strategy.winsorize_std
    for col in FACTOR_COLUMNS:
        if col in factors.columns:
            factors[col] = winsorize(factors[col].astype(float), n_std=win_std)

    # Step 4: Sector-neutral z-score each factor
    blend = settings.strategy.sector_neutral_blend
    min_group = settings.strategy.sector_neutral_min_group_size
    z_cols = {}
    for col in FACTOR_COLUMNS:
        if col in factors.columns:
            z_cols[col] = sector_neutral_zscore(
                factors[col], factors["sub_sector"], blend=blend, min_group_size=min_group
            )
        else:
            z_cols[col] = pd.Series(np.nan, index=factors.index)

    # ---- STAGE 1: Quality-first assessment (BEFORE price) ----
    # Quality score uses only fundamental factors, not momentum
    quality_weights = {k: v for k, v in settings.strategy.factor_weights.items()
                       if k in QUALITY_FACTOR_COLUMNS}
    quality_sum = pd.Series(0.0, index=factors.index)
    quality_weight_total = pd.Series(0.0, index=factors.index)
    for col in QUALITY_FACTOR_COLUMNS:
        w = quality_weights.get(col, 0.0)
        if w == 0.0 or col not in z_cols:
            continue
        z = z_cols[col]
        present = z.notna()
        quality_sum = quality_sum + (z.where(present, 0.0) * w)
        quality_weight_total = quality_weight_total + present.astype(float) * w

    # Normalize quality score
    factors["quality_score"] = (
        quality_sum / quality_weight_total.replace(0.0, np.nan)
    ).fillna(0.0)

    # Apply PER penalty to quality score
    factors["per_penalty"] = factors["per_penalty"].fillna(0.0)
    factors["quality_score"] = factors["quality_score"] + factors["per_penalty"]

    # Determine "good stock" status from quality_score alone.
    # PER is already factored in via per_penalty on quality_score, so a high-PER
    # stock with strong growth can still qualify (penalty is offset by quality).
    # No hard PER gate — avoids wrongly disqualifying high-growth stocks.
    min_quality = settings.strategy.min_quality_zscore
    factors["is_good_stock"] = factors["quality_score"] >= min_quality

    # Build quality reasons
    def _build_reasons(row):
        reasons = []
        if pd.notna(row.get("eps_growth_yoy")) and row["eps_growth_yoy"] > 0:
            reasons.append("EPS growing")
        if pd.notna(row.get("revenue_growth_yoy")) and row["revenue_growth_yoy"] > 0:
            reasons.append("Revenue growing")
        if pd.notna(row.get("gross_margin_trend")) and row["gross_margin_trend"] > 0:
            reasons.append("Margins expanding")
        if pd.notna(row.get("relative_valuation")) and row["relative_valuation"] > 0:
            reasons.append("Undervalued vs peers")
        per_abs = row.get("per_absolute_pass")
        if pd.notna(per_abs) and not bool(per_abs):
            per_val = row.get("per_ratio", 0)
            reasons.append(f"PER too high ({float(per_val) if pd.notna(per_val) else 0:.1f})")
        per_rel = row.get("per_relative_pass")
        if pd.notna(per_rel) and not bool(per_rel):
            pvp = row.get("per_vs_peer", 0)
            reasons.append(f"PER high vs peers ({float(pvp) if pd.notna(pvp) else 0:.1f}x)")
        return reasons

    factors["quality_reasons"] = factors.apply(_build_reasons, axis=1)

    # ---- STAGE 2: Price-adjusted composite score ----
    # Full composite includes momentum, but the price dip/rise adjusts
    # the final score differently based on good-stock status.
    weights = factor_weights if factor_weights else settings.strategy.factor_weights
    weighted_sum = pd.Series(0.0, index=factors.index)
    weight_total = pd.Series(0.0, index=factors.index)
    for col in FACTOR_COLUMNS:
        w = weights.get(col, 0.0)
        if w == 0.0 or col not in z_cols:
            continue
        z = z_cols[col]
        present = z.notna()
        weighted_sum = weighted_sum + (z.where(present, 0.0) * w)
        weight_total = weight_total + present.astype(float) * w

    base_composite = (
        weighted_sum / weight_total.replace(0.0, np.nan)
    ).fillna(0.0)

    # Apply PER penalty
    base_composite = base_composite + factors["per_penalty"]

    # Price opportunity adjustment:
    # Good stocks with price dip → bonus (better buy opportunity)
    # Good stocks with price rise → penalty (avoid chasing)
    # Bad stocks → no price-based bonus regardless of direction
    price_dip = pd.to_numeric(factors["price_dip_score"], errors="coerce").fillna(0.0)
    price_adj = pd.Series(0.0, index=factors.index)

    good_mask = factors["is_good_stock"]
    # For good stocks: dip adds up to +0.3 to composite, rise subtracts up to -0.3
    price_adj[good_mask] = price_dip[good_mask] * 0.5
    # For bad stocks: no bonus from dips, but still penalize chasing
    bad_rising = (~good_mask) & (price_dip < 0)
    price_adj[bad_rising] = price_dip[bad_rising] * 0.3

    factors["price_opportunity_score"] = price_adj
    factors["composite_score"] = base_composite + price_adj

    # Step 6: Assign deciles (1=worst, 10=best)
    ranks = factors["composite_score"].rank(method="first", pct=True)
    factors["score_decile"] = np.ceil(ranks * 10).clip(1, 10).astype(int)

    factors["date"] = as_of_date

    # Write z-scored values back for transparency
    for col in FACTOR_COLUMNS:
        if col in z_cols:
            factors[col] = z_cols[col]

    output_cols = (
        ["ticker", "date"] + FACTOR_COLUMNS +
        ["composite_score", "score_decile", "quality_score", "is_good_stock",
         "per_ratio", "per_vs_peer", "per_absolute_pass", "per_relative_pass",
         "recent_price_change", "price_dip_score", "price_opportunity_score",
         "quality_reasons"]
    )
    # Only include columns that exist
    output_cols = [c for c in output_cols if c in factors.columns]

    return factors[output_cols].reset_index(drop=True)


def store_quality_assessments(scores: pd.DataFrame) -> None:
    """Persist quality assessments to the stock_quality_assessment table."""
    if scores.empty or "is_good_stock" not in scores.columns:
        return

    from src.db.schema import get_connection
    con = get_connection()
    date_val = str(scores["date"].iloc[0])

    con.execute("DELETE FROM stock_quality_assessment WHERE date = $1", [date_val])

    def _safe_bool(val, default: bool) -> bool:
        return bool(val) if pd.notna(val) else default

    def _safe_float(val, default: float = 0.0):
        return float(val) if pd.notna(val) else default

    for _, row in scores.iterrows():
        con.execute("""
            INSERT INTO stock_quality_assessment
            (ticker, date, is_good_stock, quality_score, quality_reasons,
             per_ratio, per_vs_peer, per_absolute_pass, per_relative_pass,
             price_opportunity_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, [
            row["ticker"], date_val,
            _safe_bool(row.get("is_good_stock"), False),
            _safe_float(row.get("quality_score")),
            json.dumps(row.get("quality_reasons", [])),
            float(row["per_ratio"]) if pd.notna(row.get("per_ratio")) else None,
            float(row["per_vs_peer"]) if pd.notna(row.get("per_vs_peer")) else None,
            _safe_bool(row.get("per_absolute_pass"), True),
            _safe_bool(row.get("per_relative_pass"), True),
            _safe_float(row.get("price_opportunity_score")),
        ])

    con.close()


def store_stock_metrics(scores: pd.DataFrame) -> None:
    """Persist computed factor values to stock_metrics for user review/editing."""
    if scores.empty:
        return

    from datetime import datetime
    from src.db.schema import get_connection
    con = get_connection()
    date_val = str(scores["date"].iloc[0])
    now = datetime.now().isoformat()

    con.execute("DELETE FROM stock_metrics WHERE as_of_date = $1 AND source = 'computed'", [date_val])

    metric_cols = FACTOR_COLUMNS + ["quality_score", "per_ratio", "per_vs_peer",
                                     "recent_price_change", "price_dip_score"]

    for _, row in scores.iterrows():
        ticker = row["ticker"]
        for metric in metric_cols:
            val = row.get(metric)
            if pd.notna(val):
                con.execute("""
                    INSERT INTO stock_metrics (ticker, metric_name, raw_value, source, as_of_date, updated_at)
                    VALUES ($1, $2, $3, 'computed', $4, $5)
                """, [ticker, metric, float(val), date_val, now])

    con.close()


def compute_composite_historical(
    start_date: str = "2021-06-01",
    end_date: str | None = None,
    freq: str = "W-FRI",
) -> pd.DataFrame:
    """Compute composite scores for all rebalance dates in range."""
    from src.db.schema import get_connection

    con = get_connection()
    if end_date is None:
        end_date_val = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        if end_date_val is None:
            con.close()
            return pd.DataFrame()
        end_date = str(end_date_val)

    trading_dates = con.execute("""
        SELECT DISTINCT date FROM prices
        WHERE date BETWEEN $1 AND $2
        ORDER BY date
    """, [start_date, end_date]).fetchdf()
    con.close()

    if trading_dates.empty:
        return pd.DataFrame()

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
