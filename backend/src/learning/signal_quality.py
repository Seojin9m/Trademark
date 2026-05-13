"""Signal quality tracker: rolling factor IC, hit rates, decay detection, feedback weights.

Closes the feedback loop by measuring how well each factor predicts future returns
and adjusting weights accordingly. Uses existing decision_outcomes and factor_scores
tables as ground truth.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

FACTOR_COLUMNS = [
    "momentum_12m1m",
    "eps_growth_yoy",
    "revenue_growth_yoy",
    "gross_margin_trend",
    "relative_valuation",
    "forward_estimate_revision",
]

SHRINKAGE_STRENGTH = 0.5
DECAY_LOOKBACK_MONTHS = 3
IC_WINDOW_DAYS = 21


def compute_rolling_factor_ic(lookback_days: int = 126, window: int = 21) -> dict:
    """Compute rolling IC for each factor over time.

    Returns per-factor IC time series with 4-week rolling mean and decay flag.
    """
    con = get_connection()

    scores = con.execute(f"""
        SELECT ticker, date, {', '.join(FACTOR_COLUMNS)}
        FROM factor_scores
        WHERE date >= (SELECT MAX(date) - INTERVAL '{lookback_days}' DAY FROM factor_scores)
        ORDER BY date, ticker
    """).fetchdf()

    if scores.empty:
        con.close()
        return {col: {"dates": [], "ic_values": [], "rolling_mean": [], "is_decaying": False} for col in FACTOR_COLUMNS}

    min_date = str(scores["date"].min())
    prices = con.execute("""
        SELECT ticker, date, adj_close FROM prices
        WHERE date >= $1 AND adj_close > 0
        ORDER BY ticker, date
    """, [min_date]).fetchdf()
    con.close()

    if prices.empty:
        return {col: {"dates": [], "ic_values": [], "rolling_mean": [], "is_decaying": False} for col in FACTOR_COLUMNS}

    prices["date"] = pd.to_datetime(prices["date"])
    scores["date"] = pd.to_datetime(scores["date"])

    price_pivot = prices.pivot(index="date", columns="ticker", values="adj_close")
    fwd_returns = price_pivot.pct_change(periods=window, fill_method=None).shift(-window)

    ic_series = {col: {"dates": [], "values": []} for col in FACTOR_COLUMNS}

    for date in sorted(scores["date"].unique()):
        day_scores = scores[scores["date"] == date].set_index("ticker")
        if date not in fwd_returns.index:
            continue
        day_fwd = fwd_returns.loc[date]
        common = day_scores.index.intersection(day_fwd.dropna().index)
        if len(common) < 10:
            continue

        for col in FACTOR_COLUMNS:
            if col not in day_scores.columns:
                continue
            factor_vals = day_scores.loc[common, col].astype(float)
            ret_vals = day_fwd[common].astype(float)
            mask = factor_vals.notna() & ret_vals.notna()
            if mask.sum() < 10:
                continue
            ic = factor_vals[mask].corr(ret_vals[mask], method="spearman")
            if not np.isnan(ic):
                ic_series[col]["dates"].append(str(date.date()) if hasattr(date, "date") else str(date))
                ic_series[col]["values"].append(round(float(ic), 4))

    result = {}
    for col in FACTOR_COLUMNS:
        dates = ic_series[col]["dates"]
        vals = ic_series[col]["values"]

        rolling_mean = []
        if len(vals) >= 4:
            s = pd.Series(vals)
            rm = s.rolling(4, min_periods=2).mean()
            rolling_mean = [round(float(v), 4) if pd.notna(v) else 0.0 for v in rm]
        else:
            rolling_mean = vals.copy()

        is_decaying = False
        if len(vals) >= 6:
            recent_mean = np.mean(vals[-3:])
            prior_mean = np.mean(vals[:3])
            if prior_mean > 0 and recent_mean < prior_mean * 0.5:
                is_decaying = True

        result[col] = {
            "dates": dates,
            "ic_values": vals,
            "rolling_mean": rolling_mean,
            "is_decaying": is_decaying,
        }

    return result


def compute_scoring_run_hitrate(run_date: str | None = None) -> dict:
    """Compute hit rate for a specific scoring run's BUY signals."""
    con = get_connection()

    if run_date is None:
        row = con.execute("""
            SELECT MAX(decision_date) FROM decision_outcomes
            WHERE action = 'BUY' AND return_1m IS NOT NULL
        """).fetchone()
        if row is None or row[0] is None:
            con.close()
            return {"run_date": None, "total_buys": 0, "hits": 0, "misses": 0,
                    "hit_rate": 0.0, "avg_excess_return": 0.0, "factor_contribution": {}}
        run_date = str(row[0])

    outcomes = con.execute("""
        SELECT ticker, excess_return_1m, factor_snapshot
        FROM decision_outcomes
        WHERE action = 'BUY' AND decision_date = CAST($1 AS DATE)
          AND return_1m IS NOT NULL
    """, [run_date]).fetchdf()
    con.close()

    if outcomes.empty:
        return {"run_date": run_date, "total_buys": 0, "hits": 0, "misses": 0,
                "hit_rate": 0.0, "avg_excess_return": 0.0, "factor_contribution": {}}

    total = len(outcomes)
    hits = int((outcomes["excess_return_1m"] > 0).sum())
    misses = total - hits
    hit_rate = hits / total if total > 0 else 0.0
    avg_excess = float(outcomes["excess_return_1m"].mean())

    factor_contrib = {}
    import json
    for col in FACTOR_COLUMNS:
        vals = []
        rets = []
        for _, row in outcomes.iterrows():
            snap = row.get("factor_snapshot")
            if snap:
                try:
                    d = json.loads(snap) if isinstance(snap, str) else snap
                    v = d.get(col)
                    if v is not None and pd.notna(row["excess_return_1m"]):
                        vals.append(float(v))
                        rets.append(float(row["excess_return_1m"]))
                except Exception:
                    pass
        if len(vals) >= 5:
            corr = pd.Series(vals).corr(pd.Series(rets), method="spearman")
            factor_contrib[col] = round(float(corr), 3) if not np.isnan(corr) else 0.0
        else:
            factor_contrib[col] = 0.0

    return {
        "run_date": run_date,
        "total_buys": total,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hit_rate, 3),
        "avg_excess_return": round(avg_excess, 4),
        "factor_contribution": factor_contrib,
    }


def detect_factor_decay() -> list[dict]:
    """Detect factors whose IC is decaying (losing predictive power)."""
    rolling_ic = compute_rolling_factor_ic(lookback_days=180)
    decaying = []

    for col in FACTOR_COLUMNS:
        data = rolling_ic[col]
        vals = data["ic_values"]
        if len(vals) < 8:
            continue

        n = len(vals)
        mid = n // 2
        prior_ic = float(np.mean(vals[:mid]))
        current_ic = float(np.mean(vals[mid:]))

        x = np.arange(n, dtype=float)
        y = np.array(vals, dtype=float)
        if len(x) >= 3:
            slope = float(np.polyfit(x, y, 1)[0])
        else:
            slope = 0.0

        if prior_ic > 0.01 and current_ic < prior_ic * 0.5:
            rec = "reduce_weight"
            if current_ic < 0:
                rec = "strongly_reduce_weight"
            decaying.append({
                "factor": col,
                "prior_ic": round(prior_ic, 4),
                "current_ic": round(current_ic, 4),
                "slope": round(slope, 6),
                "recommendation": rec,
            })

    return decaying


def compute_feedback_weights() -> dict[str, float]:
    """Compute recommended factor weights from signal quality analysis.

    Uses double shrinkage: IC-optimal → equal-weight → current production weights.
    """
    rolling_ic = compute_rolling_factor_ic(lookback_days=126)
    decaying = detect_factor_decay()
    decay_set = {d["factor"] for d in decaying}

    ic_means = {}
    for col in FACTOR_COLUMNS:
        vals = rolling_ic[col]["ic_values"]
        if len(vals) >= 5:
            ic_means[col] = max(0.0, float(np.mean(vals[-8:])))
        else:
            ic_means[col] = 0.0

    for col in decay_set:
        ic_means[col] *= 0.5

    total = sum(ic_means.values())
    if total > 0:
        ic_weights = {col: ic_means[col] / total for col in FACTOR_COLUMNS}
    else:
        ic_weights = {col: 1.0 / len(FACTOR_COLUMNS) for col in FACTOR_COLUMNS}

    equal_weight = 1.0 / len(FACTOR_COLUMNS)
    current_weights = settings.strategy.factor_weights

    shrunk = {}
    for col in FACTOR_COLUMNS:
        w_ic = ic_weights.get(col, equal_weight)
        w_eq = equal_weight
        w_prod = current_weights.get(col, equal_weight)

        stage1 = SHRINKAGE_STRENGTH * w_ic + (1 - SHRINKAGE_STRENGTH) * w_eq
        stage2 = 0.7 * stage1 + 0.3 * w_prod
        shrunk[col] = stage2

    total_w = sum(shrunk.values())
    if total_w > 0:
        shrunk = {k: round(v / total_w, 4) for k, v in shrunk.items()}

    return shrunk


def compute_quality_dashboard() -> dict:
    """Full signal quality dashboard data."""
    rolling_ic = compute_rolling_factor_ic(lookback_days=126)
    decaying = detect_factor_decay()
    feedback_weights = compute_feedback_weights()

    recent_runs = []
    try:
        con = get_connection()
        dates = con.execute("""
            SELECT DISTINCT decision_date FROM decision_outcomes
            WHERE action = 'BUY' AND return_1m IS NOT NULL
            ORDER BY decision_date DESC LIMIT 12
        """).fetchdf()
        con.close()

        for _, row in dates.iterrows():
            hr = compute_scoring_run_hitrate(str(row["decision_date"]))
            recent_runs.append(hr)
    except Exception:
        pass

    overall_hit_rate = 0.0
    overall_excess = 0.0
    if recent_runs:
        total_buys = sum(r["total_buys"] for r in recent_runs)
        total_hits = sum(r["hits"] for r in recent_runs)
        if total_buys > 0:
            overall_hit_rate = round(total_hits / total_buys, 3)
            overall_excess = round(
                sum(r["avg_excess_return"] * r["total_buys"] for r in recent_runs) / total_buys, 4
            )

    return {
        "rolling_factor_ic": rolling_ic,
        "recent_run_hitrates": recent_runs,
        "overall_hit_rate": overall_hit_rate,
        "overall_avg_excess_return": overall_excess,
        "factor_decay_alerts": decaying,
        "feedback_weights": feedback_weights,
        "current_weights": dict(settings.strategy.factor_weights),
    }


def log_signal_quality(run_date: str) -> None:
    """Store signal quality metrics to signal_quality_log table."""
    rolling_ic = compute_rolling_factor_ic(lookback_days=126)
    hitrate = compute_scoring_run_hitrate(run_date)

    con = get_connection()
    for col in FACTOR_COLUMNS:
        vals = rolling_ic[col]["ic_values"]
        ic_val = float(np.mean(vals[-4:])) if vals else None
        hr = hitrate.get("factor_contribution", {}).get(col)

        con.execute("""
            DELETE FROM signal_quality_log
            WHERE run_date = $1 AND factor_name = $2
        """, [run_date, col])
        con.execute("""
            INSERT INTO signal_quality_log
            (run_date, factor_name, ic_value, hit_rate, avg_excess_return, n_signals, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, [
            run_date, col, ic_val, hr,
            hitrate.get("avg_excess_return"),
            hitrate.get("total_buys", 0),
            datetime.now(),
        ])
    con.close()
