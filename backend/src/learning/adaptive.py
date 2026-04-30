"""Adaptive strategy tuning: data-driven optimization of factor weights,
position sizing, and constraint parameters.

Modern quant practices implemented:
1. Information Coefficient (IC) based factor weighting with Bayesian shrinkage
2. Regime detection via realized volatility
3. Volatility-targeted position sizing (inverse-vol)
4. Dynamic drawdown gates (continuous, not binary)
5. Adaptive decile change thresholds based on factor noise
6. Dynamic sector caps based on rolling performance
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

FACTOR_COLUMNS = [
    "momentum_12m1m",
    "eps_growth_yoy",
    "revenue_growth_yoy",
    "gross_margin_trend",
    "relative_valuation",
]

# Bayesian shrinkage: blend IC-optimal weights with equal weight prior
# Higher = more trust in IC data, lower = more conservative (stick to equal)
SHRINKAGE_STRENGTH = 0.5  # 0.0 = pure equal weight, 1.0 = pure IC-optimal

# Regime thresholds (annualized benchmark volatility)
REGIME_LOW_VOL = 0.12    # < 12% annualized = low vol
REGIME_HIGH_VOL = 0.25   # > 25% annualized = high vol

# Minimum lookback for IC calculation (trading days)
MIN_IC_LOOKBACK = 63  # ~3 months


# ============================================================
# 1. Factor Weight Optimization (IC-based + Bayesian shrinkage)
# ============================================================

def compute_factor_ic(lookback_days: int = 126) -> dict:
    """Compute Information Coefficient for each factor.

    IC = rank correlation between factor score and subsequent N-day forward return.
    Uses 21-day (1-month) forward returns as the target.

    Returns dict with per-factor IC, t-stat, and optimized weights.
    """
    con = get_connection()

    # Get factor scores with dates
    scores = con.execute(f"""
        SELECT ticker, date, momentum_12m1m, eps_growth_yoy, revenue_growth_yoy,
               gross_margin_trend, relative_valuation, composite_score, score_decile
        FROM factor_scores
        WHERE date >= (SELECT MAX(date) - INTERVAL '{lookback_days}' DAY FROM factor_scores)
        ORDER BY date, ticker
    """).fetchdf()

    if scores.empty or len(scores) < MIN_IC_LOOKBACK:
        con.close()
        return _default_ic_result()

    # Get prices for forward return computation
    min_date = str(scores["date"].min())
    prices = con.execute("""
        SELECT ticker, date, adj_close FROM prices
        WHERE date >= $1 AND adj_close > 0
        ORDER BY ticker, date
    """, [min_date]).fetchdf()
    con.close()

    if prices.empty:
        return _default_ic_result()

    prices["date"] = pd.to_datetime(prices["date"])
    scores["date"] = pd.to_datetime(scores["date"])

    # Compute 21-day forward returns for each ticker at each score date
    price_pivot = prices.pivot(index="date", columns="ticker", values="adj_close")
    fwd_returns = price_pivot.pct_change(periods=21, fill_method=None).shift(-21)  # 21-day forward return

    # Compute IC per factor per cross-section date
    ic_by_factor = {col: [] for col in FACTOR_COLUMNS}

    for date in scores["date"].unique():
        day_scores = scores[scores["date"] == date].set_index("ticker")
        day_fwd = fwd_returns.loc[date] if date in fwd_returns.index else None

        if day_fwd is None:
            continue

        # Align tickers
        common = day_scores.index.intersection(day_fwd.dropna().index)
        if len(common) < 10:
            continue

        for col in FACTOR_COLUMNS:
            if col not in day_scores.columns:
                continue
            factor_vals = day_scores.loc[common, col].astype(float)
            ret_vals = day_fwd[common].astype(float)

            # Drop NaN pairs
            mask = factor_vals.notna() & ret_vals.notna()
            if mask.sum() < 10:
                continue

            # Spearman rank correlation = IC
            ic = factor_vals[mask].corr(ret_vals[mask], method="spearman")
            if not np.isnan(ic):
                ic_by_factor[col].append(ic)

    # Compute average IC and t-stat per factor
    result = {"factors": {}, "regime": None}
    ic_values = {}

    for col in FACTOR_COLUMNS:
        ics = ic_by_factor[col]
        if len(ics) < 5:
            ic_values[col] = 0.0
            result["factors"][col] = {
                "avg_ic": 0.0,
                "ic_std": 0.0,
                "t_stat": 0.0,
                "n_observations": len(ics),
                "significant": False,
            }
        else:
            avg_ic = np.mean(ics)
            ic_std = np.std(ics, ddof=1)
            t_stat = avg_ic / (ic_std / np.sqrt(len(ics))) if ic_std > 0 else 0
            ic_values[col] = max(avg_ic, 0)  # Only use positive IC for weighting

            result["factors"][col] = {
                "avg_ic": round(avg_ic, 4),
                "ic_std": round(ic_std, 4),
                "t_stat": round(t_stat, 2),
                "n_observations": len(ics),
                "significant": abs(t_stat) > 1.96,  # 95% CI
            }

    # Compute IC-optimal weights (proportional to positive IC)
    total_ic = sum(ic_values.values())
    if total_ic > 0:
        ic_weights = {col: ic_values[col] / total_ic for col in FACTOR_COLUMNS}
    else:
        ic_weights = {col: 0.20 for col in FACTOR_COLUMNS}

    # Bayesian shrinkage: blend IC weights with equal-weight prior
    equal_weight = 1.0 / len(FACTOR_COLUMNS)
    shrunk_weights = {}
    for col in FACTOR_COLUMNS:
        shrunk_weights[col] = round(
            SHRINKAGE_STRENGTH * ic_weights[col] + (1 - SHRINKAGE_STRENGTH) * equal_weight,
            4,
        )

    # Normalize to sum to 1.0
    total = sum(shrunk_weights.values())
    if total > 0:
        shrunk_weights = {k: round(v / total, 4) for k, v in shrunk_weights.items()}

    result["ic_optimal_weights"] = ic_weights
    result["shrunk_weights"] = shrunk_weights
    result["equal_weights"] = {col: equal_weight for col in FACTOR_COLUMNS}
    result["shrinkage_strength"] = SHRINKAGE_STRENGTH
    result["lookback_days"] = lookback_days
    result["computed_at"] = datetime.now().isoformat()

    return result


def _default_ic_result() -> dict:
    """Return default IC result when insufficient data."""
    equal = 1.0 / len(FACTOR_COLUMNS)
    return {
        "factors": {col: {"avg_ic": 0, "ic_std": 0, "t_stat": 0, "n_observations": 0, "significant": False} for col in FACTOR_COLUMNS},
        "ic_optimal_weights": {col: equal for col in FACTOR_COLUMNS},
        "shrunk_weights": {col: equal for col in FACTOR_COLUMNS},
        "equal_weights": {col: equal for col in FACTOR_COLUMNS},
        "shrinkage_strength": SHRINKAGE_STRENGTH,
        "lookback_days": 0,
        "computed_at": datetime.now().isoformat(),
    }


# ============================================================
# 2. Regime Detection
# ============================================================

def detect_regime(lookback_days: int = 63) -> dict:
    """Detect current market regime using realized volatility of benchmark.

    Regimes:
    - LOW_VOL: calm markets, favor momentum, widen entry criteria
    - NORMAL: standard operation
    - HIGH_VOL: volatile markets, tighten stops, reduce position sizes, raise thresholds

    Also measures:
    - Momentum regime: is the market trending up or down?
    - Dispersion: are factor scores tightly clustered or spread out?
    """
    con = get_connection()
    benchmark = settings.primary_benchmark

    bench_prices = con.execute("""
        SELECT date, adj_close FROM prices
        WHERE ticker = $1 AND adj_close > 0
        ORDER BY date DESC LIMIT $2
    """, [benchmark, lookback_days + 5]).fetchdf()

    # Get factor score dispersion
    latest_scores = con.execute("""
        SELECT composite_score FROM factor_scores
        WHERE date = (SELECT MAX(date) FROM factor_scores)
    """).fetchdf()
    con.close()

    if bench_prices.empty or len(bench_prices) < 20:
        return _default_regime()

    bench_prices = bench_prices.sort_values("date")
    returns = bench_prices["adj_close"].pct_change().dropna()

    # Realized volatility (annualized)
    realized_vol = float(returns.std() * np.sqrt(252))

    # Determine vol regime
    if realized_vol < REGIME_LOW_VOL:
        vol_regime = "LOW_VOL"
    elif realized_vol > REGIME_HIGH_VOL:
        vol_regime = "HIGH_VOL"
    else:
        vol_regime = "NORMAL"

    # Momentum regime: 21-day benchmark return
    if len(bench_prices) >= 22:
        momentum_21d = float(bench_prices["adj_close"].iloc[-1] / bench_prices["adj_close"].iloc[-22] - 1)
    else:
        momentum_21d = 0.0

    if momentum_21d > 0.03:
        momentum_regime = "BULL"
    elif momentum_21d < -0.03:
        momentum_regime = "BEAR"
    else:
        momentum_regime = "SIDEWAYS"

    # Factor dispersion
    score_dispersion = float(latest_scores["composite_score"].std()) if not latest_scores.empty else 0.0

    return {
        "vol_regime": vol_regime,
        "realized_vol": round(realized_vol, 4),
        "momentum_regime": momentum_regime,
        "momentum_21d": round(momentum_21d, 4),
        "score_dispersion": round(score_dispersion, 4),
        "lookback_days": lookback_days,
        "benchmark": benchmark,
        "detected_at": datetime.now().isoformat(),
    }


def _default_regime() -> dict:
    return {
        "vol_regime": "NORMAL",
        "realized_vol": 0.18,
        "momentum_regime": "SIDEWAYS",
        "momentum_21d": 0.0,
        "score_dispersion": 0.0,
        "lookback_days": 0,
        "benchmark": settings.primary_benchmark,
        "detected_at": datetime.now().isoformat(),
    }


# ============================================================
# 3. Adaptive Constraint Tuning
# ============================================================

def compute_adaptive_constraints(regime: dict, ic_result: dict) -> dict:
    """Compute adaptive strategy parameters based on regime and IC analysis.

    Adjusts:
    - min_decile_change: tighter in high-vol (fewer trades), looser in low-vol
    - position_size_scalar: reduce in high-vol, increase in low-vol
    - drawdown_gate_scalar: continuous scaling instead of binary
    - max_new_positions_per_run: reduce in high-vol
    - sector_cap_adjustment: tighten when sector win rates are low
    """
    vol_regime = regime.get("vol_regime", "NORMAL")
    realized_vol = regime.get("realized_vol", 0.18)
    momentum_regime = regime.get("momentum_regime", "SIDEWAYS")

    # Base values from settings
    base_decile_change = settings.strategy.min_decile_change_to_trade
    base_max_new = settings.strategy.max_new_positions_per_run
    base_max_trades = settings.strategy.max_trades_per_run

    # --- Adaptive decile change threshold ---
    # High vol → more noise → require larger moves to trade
    # Low vol → signals are cleaner → can trade on smaller moves
    if vol_regime == "HIGH_VOL":
        adapted_decile_change = max(base_decile_change, 3)
    elif vol_regime == "LOW_VOL":
        adapted_decile_change = max(base_decile_change - 1, 1)
    else:
        adapted_decile_change = base_decile_change

    # --- Position size scalar (volatility targeting) ---
    # Target 18% annualized portfolio vol
    target_vol = 0.18
    vol_scalar = min(target_vol / max(realized_vol, 0.05), 1.5)  # Cap at 1.5x
    vol_scalar = max(vol_scalar, 0.5)  # Floor at 0.5x

    # --- Max new positions per run ---
    if vol_regime == "HIGH_VOL":
        adapted_max_new = max(base_max_new - 1, 1)
    elif vol_regime == "LOW_VOL" and momentum_regime == "BULL":
        adapted_max_new = base_max_new + 1
    else:
        adapted_max_new = base_max_new

    # --- Max trades per run ---
    if vol_regime == "HIGH_VOL":
        adapted_max_trades = max(base_max_trades - 1, 2)
    else:
        adapted_max_trades = base_max_trades

    # --- Drawdown scaling (continuous, not binary) ---
    # Instead of blocking all buys at -15%, scale position sizes down gradually
    # At 0% drawdown: 100% size, at -10%: 75%, at -15%: 50%, at -20%: 0%
    drawdown_schedule = [
        {"drawdown": 0.0, "size_pct": 1.0},
        {"drawdown": -0.05, "size_pct": 0.90},
        {"drawdown": -0.10, "size_pct": 0.75},
        {"drawdown": -0.15, "size_pct": 0.50},
        {"drawdown": -0.20, "size_pct": 0.0},
    ]

    # --- Factor weight recommendation ---
    recommended_weights = ic_result.get("shrunk_weights", settings.strategy.factor_weights)

    # In bear markets, overweight valuation (buy cheap) and underweight momentum (reversals)
    if momentum_regime == "BEAR" and vol_regime == "HIGH_VOL":
        # Shift 5% from momentum to valuation
        bear_adj = dict(recommended_weights)
        shift = 0.05
        bear_adj["momentum_12m1m"] = max(bear_adj.get("momentum_12m1m", 0.2) - shift, 0.05)
        bear_adj["relative_valuation"] = bear_adj.get("relative_valuation", 0.2) + shift
        # Renormalize
        total = sum(bear_adj.values())
        recommended_weights = {k: round(v / total, 4) for k, v in bear_adj.items()}

    # --- Sector cap adjustments from outcome patterns ---
    sector_caps = _compute_sector_cap_adjustments()

    rationale = _build_rationale(regime, vol_scalar, adapted_decile_change)
    for sector, mult in sector_caps.items():
        rationale.append(f"Sector '{sector}' cap tightened to {mult:.0%} of base (poor outcome history)")

    return {
        "min_decile_change": adapted_decile_change,
        "position_size_scalar": round(vol_scalar, 3),
        "max_new_positions_per_run": adapted_max_new,
        "max_trades_per_run": adapted_max_trades,
        "drawdown_schedule": drawdown_schedule,
        "recommended_factor_weights": recommended_weights,
        "sector_cap_adjustments": sector_caps,
        "regime": regime,
        "rationale": rationale,
        "computed_at": datetime.now().isoformat(),
    }


def _compute_sector_cap_adjustments() -> dict[str, float]:
    """Compute sector cap tightening multipliers from outcome pattern alerts.

    Reads decision_patterns where dimension='sub_sector' and is_alert=TRUE.
    For sectors with win_rate < 40% and sample_size >= 5, returns a
    tightening multiplier (0.5 to 1.0) applied to the configured sector cap.
    """
    try:
        con = get_connection()
        rows = con.execute("""
            SELECT dimension_value, win_rate, sample_size
            FROM decision_patterns
            WHERE dimension = 'sub_sector' AND is_alert = TRUE AND sample_size >= 5
        """).fetchall()
        con.close()
    except Exception:
        return {}

    adjustments = {}
    for sector, win_rate, sample_size in rows:
        multiplier = max(0.5, win_rate / 0.50)
        adjustments[sector] = round(multiplier, 2)

    return adjustments


def _build_rationale(regime: dict, vol_scalar: float, decile_change: int) -> list[str]:
    """Build human-readable rationale for adaptive parameter choices."""
    reasons = []
    vol_regime = regime.get("vol_regime", "NORMAL")
    momentum_regime = regime.get("momentum_regime", "SIDEWAYS")
    realized_vol = regime.get("realized_vol", 0.18)

    reasons.append(f"Market regime: {vol_regime} vol ({realized_vol:.0%} annualized), {momentum_regime} trend")

    if vol_scalar < 0.8:
        reasons.append(f"Position sizes reduced to {vol_scalar:.0%} of base (high volatility → smaller bets)")
    elif vol_scalar > 1.2:
        reasons.append(f"Position sizes increased to {vol_scalar:.0%} of base (low volatility → larger bets)")

    if decile_change > 2:
        reasons.append("Decile threshold raised to 3 (noisy signals in high-vol → require stronger conviction)")
    elif decile_change < 2:
        reasons.append("Decile threshold lowered to 1 (clean signals in low-vol → capture more opportunities)")

    if momentum_regime == "BEAR" and vol_regime == "HIGH_VOL":
        reasons.append("Bear + high-vol regime: shifted weight from momentum to valuation (momentum reversals likely)")

    return reasons


# ============================================================
# 4. Volatility-Targeted Position Sizing
# ============================================================

def compute_vol_adjusted_weights(
    target_weights: dict[str, float],
    vol_scalar: float,
    lookback_days: int = 63,
) -> dict[str, float]:
    """Adjust position weights by inverse volatility.

    Instead of equal 6% for all decile-9 stocks, allocate more to
    low-vol stocks and less to high-vol stocks, targeting similar
    risk contribution from each position.

    Args:
        target_weights: Base target weights from decile mapping
        vol_scalar: Overall portfolio vol scalar from regime
        lookback_days: Lookback for per-ticker volatility
    """
    if not target_weights:
        return {}

    con = get_connection()
    tickers = list(target_weights.keys())

    # Get recent returns for volatility computation
    vol_data = con.execute(f"""
        WITH recent_prices AS (
            SELECT ticker, date, adj_close,
                   LAG(adj_close) OVER (PARTITION BY ticker ORDER BY date) as prev_close
            FROM prices
            WHERE ticker = ANY($1)
              AND date >= (SELECT MAX(date) - INTERVAL '{lookback_days}' DAY FROM prices)
              AND adj_close > 0
        )
        SELECT ticker, STDDEV(LN(adj_close / prev_close)) * SQRT(252) as ann_vol
        FROM recent_prices
        WHERE prev_close > 0
        GROUP BY ticker
        HAVING COUNT(*) >= 20
    """, [tickers]).fetchdf()
    con.close()

    if vol_data.empty:
        # No vol data, just apply scalar to base weights
        return {t: round(w * vol_scalar, 4) for t, w in target_weights.items()}

    ticker_vol = dict(zip(vol_data["ticker"], vol_data["ann_vol"]))

    # Compute inverse-vol weights
    inv_vols = {}
    for ticker in tickers:
        vol = ticker_vol.get(ticker, 0.30)  # Default 30% vol if missing
        vol = max(vol, 0.05)  # Floor at 5% to avoid infinity
        inv_vols[ticker] = 1.0 / vol

    # Scale inverse-vol to preserve total portfolio weight
    total_base = sum(target_weights.values())
    total_inv_vol = sum(inv_vols.get(t, 1.0) for t in tickers)

    if total_inv_vol == 0:
        return {t: round(w * vol_scalar, 4) for t, w in target_weights.items()}

    adjusted = {}
    for ticker, base_weight in target_weights.items():
        # Blend: keep tier structure but adjust within tier by inv-vol
        inv_vol_ratio = inv_vols.get(ticker, 1.0) / (total_inv_vol / len(tickers))
        # Clamp adjustment to avoid extreme over/under-weighting (0.5x to 2.0x)
        inv_vol_ratio = max(0.5, min(2.0, inv_vol_ratio))
        adjusted[ticker] = round(base_weight * inv_vol_ratio * vol_scalar, 4)

    # Clip to max position weight
    max_w = settings.strategy.max_single_position_weight
    adjusted = {t: min(w, max_w) for t, w in adjusted.items()}

    return adjusted


# ============================================================
# 5. Drawdown Position Scaling
# ============================================================

def drawdown_size_scalar(
    current_drawdown: float,
    schedule: list[dict] | None = None,
) -> float:
    """Compute position size scalar based on current drawdown level.

    Uses linear interpolation between schedule breakpoints instead of
    binary gates. Returns a float between 0.0 and 1.0.

    Args:
        current_drawdown: Current drawdown from peak (negative number, e.g., -0.12)
        schedule: List of {drawdown, size_pct} breakpoints, sorted by drawdown desc
    """
    if schedule is None:
        schedule = [
            {"drawdown": 0.0, "size_pct": 1.0},
            {"drawdown": -0.05, "size_pct": 0.90},
            {"drawdown": -0.10, "size_pct": 0.75},
            {"drawdown": -0.15, "size_pct": 0.50},
            {"drawdown": -0.20, "size_pct": 0.0},
        ]

    # Sort by drawdown descending (0, -5, -10, ...)
    schedule = sorted(schedule, key=lambda x: x["drawdown"], reverse=True)

    # If above best case, full size
    if current_drawdown >= schedule[0]["drawdown"]:
        return schedule[0]["size_pct"]

    # If below worst case, zero
    if current_drawdown <= schedule[-1]["drawdown"]:
        return schedule[-1]["size_pct"]

    # Linear interpolation between breakpoints
    for i in range(len(schedule) - 1):
        upper = schedule[i]
        lower = schedule[i + 1]
        if lower["drawdown"] <= current_drawdown <= upper["drawdown"]:
            # Interpolate
            dd_range = upper["drawdown"] - lower["drawdown"]
            if dd_range == 0:
                return upper["size_pct"]
            t = (current_drawdown - lower["drawdown"]) / dd_range
            return lower["size_pct"] + t * (upper["size_pct"] - lower["size_pct"])

    return 1.0


# ============================================================
# 6. Full Adaptive Analysis (Pipeline Entry Point)
# ============================================================

def run_adaptive_analysis() -> dict:
    """Run complete adaptive analysis: IC computation, regime detection, constraint tuning.

    This is the main entry point called by the pipeline.
    Returns the full adaptive state including recommended parameters.
    """
    print("Running adaptive analysis...")

    # Step 1: Regime detection
    regime = detect_regime()
    print(f"  Regime: {regime['vol_regime']} vol ({regime['realized_vol']:.0%}), "
          f"{regime['momentum_regime']} trend ({regime['momentum_21d']:+.1%})")

    # Step 2: Factor IC analysis
    ic_result = compute_factor_ic(lookback_days=126)
    sig_factors = [f for f, d in ic_result["factors"].items() if d.get("significant")]
    print(f"  Significant factors: {', '.join(sig_factors) if sig_factors else 'none (insufficient data)'}")
    print(f"  Recommended weights: {ic_result['shrunk_weights']}")

    # Step 3: Adaptive constraints
    constraints = compute_adaptive_constraints(regime, ic_result)
    print(f"  Adapted decile threshold: {constraints['min_decile_change']}")
    print(f"  Position size scalar: {constraints['position_size_scalar']:.0%}")
    for r in constraints["rationale"]:
        print(f"    - {r}")

    # Store results
    _store_adaptive_state(constraints)

    return {
        "regime": regime,
        "ic_analysis": ic_result,
        "adaptive_constraints": constraints,
    }


def _store_adaptive_state(constraints: dict) -> None:
    """Persist the latest adaptive state to the database for dashboard access."""
    con = get_connection()

    # Create table if not exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS adaptive_state (
            key VARCHAR PRIMARY KEY,
            value JSON,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    state_json = json.dumps(constraints, default=str)
    now = datetime.now().isoformat()
    con.execute("""
        INSERT INTO adaptive_state (key, value, updated_at)
        VALUES ('latest', $1, $2)
        ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = $2
    """, [state_json, now])
    con.close()


def get_adaptive_state() -> dict | None:
    """Retrieve the latest adaptive state from the database."""
    con = get_connection()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS adaptive_state (
                key VARCHAR PRIMARY KEY,
                value JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        row = con.execute("""
            SELECT value FROM adaptive_state WHERE key = 'latest'
        """).fetchone()
        con.close()
        if row:
            return json.loads(row[0])
        return None
    except Exception:
        con.close()
        return None
