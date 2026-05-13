"""Outcome tracker: measures proposal returns and classifies GOOD/BAD/NEUTRAL.

For every trade proposal (regardless of approval status), tracks the stock's
performance from the proposal date at 1-week, 1-month, and 3-month horizons
relative to the benchmark (QQQ).

This lets us evaluate whether the MODEL's signals are good — independent of
whether the judge approved or rejected the proposal.

Outcome classification (based on 1-month excess return):
  GOOD:    excess return >= +2%  (BUY that beat market, or SELL where stock dropped)
  BAD:     excess return <= -2%  (BUY that lagged market, or SELL where stock rallied)
  NEUTRAL: between -2% and +2%
"""

import json
import math
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

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
    "forward_estimate_revision",
]


def _sanitize_for_json(d: dict) -> dict:
    """Replace NaN/Inf float values with None for safe JSON serialization."""
    return {
        k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
        for k, v in d.items()
    }

HORIZON_TRADING_DAYS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
}

OUTCOME_THRESHOLDS = {
    "GOOD": 0.02,
    "BAD": -0.02,
}


def _get_price_on_date(con, ticker: str, target_date: str) -> float | None:
    """Get the closest available adj_close on or before target_date."""
    row = con.execute("""
        SELECT adj_close FROM prices
        WHERE ticker = $1 AND date <= $2 AND adj_close > 0
        ORDER BY date DESC LIMIT 1
    """, [ticker, target_date]).fetchone()
    return row[0] if row else None


def _get_price_after_days(con, ticker: str, start_date: str, trading_days: int) -> tuple[float | None, str | None]:
    """Get the adj_close approximately N trading days after start_date."""
    rows = con.execute("""
        SELECT adj_close, date FROM prices
        WHERE ticker = $1 AND date > $2 AND adj_close > 0
        ORDER BY date ASC
    """, [ticker, start_date]).fetchall()

    if len(rows) >= trading_days:
        price, dt = rows[trading_days - 1]
        return price, str(dt)
    return None, None


def _compute_return(entry_price: float, exit_price: float | None) -> float | None:
    if exit_price is None or entry_price <= 0:
        return None
    return (exit_price / entry_price) - 1


def _classify_outcome(excess_return_1m: float | None) -> str | None:
    if excess_return_1m is None:
        return None
    if excess_return_1m >= OUTCOME_THRESHOLDS["GOOD"]:
        return "GOOD"
    elif excess_return_1m <= OUTCOME_THRESHOLDS["BAD"]:
        return "BAD"
    return "NEUTRAL"


def seed_outcomes_from_proposals() -> int:
    """Seed decision_outcomes from all trade proposals that don't have outcomes yet.

    Tracks every proposal (APPROVED, REJECTED, PENDING, NEEDS_REVIEW) so we can
    evaluate model signal quality independent of the judge's filtering.
    Uses the market close price on the proposal date as entry price.
    """
    con = get_connection()

    # Sync stale proposal_status values from trade_proposals → decision_outcomes
    con.execute("""
        UPDATE decision_outcomes
        SET proposal_status = tp.status
        FROM trade_proposals tp
        WHERE decision_outcomes.proposal_id = tp.proposal_id
          AND decision_outcomes.proposal_status != tp.status
    """)

    universe = pd.read_csv(settings.paths.universe_path)
    sector_map = dict(zip(universe["ticker"], universe.get("sub_sector", pd.Series())))

    new_proposals = con.execute("""
        SELECT tp.proposal_id, tp.ticker, tp.action, tp.created_at,
               tp.shares, tp.signal_data, tp.judge_response, tp.status
        FROM trade_proposals tp
        LEFT JOIN decision_outcomes dout ON tp.proposal_id = dout.proposal_id
        WHERE dout.proposal_id IS NULL
          AND tp.action NOT IN ('STAY', 'HOLD')
          AND tp.ticker IS NOT NULL
    """).fetchall()

    seeded = 0
    for row in new_proposals:
        proposal_id, ticker, action, created_at, shares, signal_data_raw, judge_response_raw, status = row

        signal_data = json.loads(signal_data_raw) if isinstance(signal_data_raw, str) else (signal_data_raw or {})
        judge_response = json.loads(judge_response_raw) if isinstance(judge_response_raw, str) else (judge_response_raw or {})

        proposal_date = str(created_at)[:10]

        entry_price = _get_price_on_date(con, ticker, proposal_date)
        if entry_price is None:
            continue

        sub_sector_val = None
        match = universe.loc[universe["ticker"] == ticker, "sub_sector"]
        if not match.empty:
            sub_sector_val = match.iloc[0]

        factors = signal_data.get("factors", {})
        if not factors or all(v is None for v in factors.values()):
            row_fs = con.execute("""
                SELECT momentum_12m1m, eps_growth_yoy, revenue_growth_yoy,
                       gross_margin_trend, relative_valuation
                FROM factor_scores
                WHERE ticker = $1 AND date <= CAST($2 AS DATE)
                ORDER BY date DESC LIMIT 1
            """, [ticker, proposal_date]).fetchone()
            if row_fs:
                factors = dict(zip(FACTOR_COLUMNS, row_fs))

        factors = _sanitize_for_json(factors)

        con.execute("""
            INSERT INTO decision_outcomes
            (proposal_id, ticker, action, decision_date, entry_price, shares,
             composite_score, score_decile, prior_decile,
             judge_verdict, judge_confidence,
             sector, sub_sector, factor_snapshot, proposal_status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """, [
            proposal_id,
            ticker,
            action,
            proposal_date,
            entry_price,
            shares,
            signal_data.get("composite_score"),
            signal_data.get("decile"),
            signal_data.get("prior_decile"),
            judge_response.get("verdict"),
            judge_response.get("confidence"),
            sub_sector_val,
            sector_map.get(ticker),
            json.dumps(factors),
            status,
        ])
        seeded += 1

    con.close()
    return seeded


def measure_outcomes() -> dict:
    """Measure returns for all decision_outcomes that have unmeasured horizons.

    For BUY/ADD: measures if the stock went up (good) or down (bad) vs benchmark.
    For SELL/TRIM: inverts the return — stock dropping after sell = GOOD decision.
    """
    con = get_connection()
    benchmark = settings.primary_benchmark

    outcomes = con.execute("""
        SELECT proposal_id, ticker, action, decision_date, entry_price
        FROM decision_outcomes
        WHERE entry_price IS NOT NULL
          AND (return_1w IS NULL OR return_1m IS NULL OR return_3m IS NULL)
    """).fetchall()

    stats = {"measured_1w": 0, "measured_1m": 0, "measured_3m": 0, "classified": 0}

    for proposal_id, ticker, action, decision_date, entry_price in outcomes:
        decision_date_str = str(decision_date)
        benchmark_entry = _get_price_on_date(con, benchmark, decision_date_str)
        updates = {}

        is_sell = action in ("SELL", "TRIM")

        for horizon_key, trading_days in HORIZON_TRADING_DAYS.items():
            return_col = f"return_{horizon_key}"
            measured_col = f"measured_at_{horizon_key}"
            bench_col = f"benchmark_return_{horizon_key}"
            excess_col = f"excess_return_{horizon_key}"

            existing = con.execute(f"""
                SELECT {return_col} FROM decision_outcomes
                WHERE proposal_id = $1
            """, [proposal_id]).fetchone()

            if existing and existing[0] is not None:
                continue

            exit_price, exit_date = _get_price_after_days(con, ticker, decision_date_str, trading_days)
            raw_stock_return = _compute_return(entry_price, exit_price)

            if raw_stock_return is not None:
                bench_exit, _ = _get_price_after_days(con, benchmark, decision_date_str, trading_days)
                bench_return = _compute_return(benchmark_entry, bench_exit) if benchmark_entry else None

                if is_sell:
                    effective_return = -raw_stock_return
                    raw_excess = (-raw_stock_return - bench_return) if bench_return is not None else None
                else:
                    effective_return = raw_stock_return
                    raw_excess = (raw_stock_return - bench_return) if bench_return is not None else None

                updates[return_col] = effective_return
                updates[measured_col] = exit_date
                updates[bench_col] = bench_return
                updates[excess_col] = raw_excess
                stats[f"measured_{horizon_key}"] += 1

        if updates:
            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
            values = list(updates.values())

            con.execute(f"""
                UPDATE decision_outcomes
                SET {set_clauses}, updated_at = CURRENT_TIMESTAMP
                WHERE proposal_id = $1
            """, [proposal_id] + values)

            if "excess_return_1m" in updates and updates["excess_return_1m"] is not None:
                outcome = _classify_outcome(updates["excess_return_1m"])
                if outcome:
                    con.execute("""
                        UPDATE decision_outcomes
                        SET outcome_1m = $1
                        WHERE proposal_id = $2
                    """, [outcome, proposal_id])
                    stats["classified"] += 1

    con.close()
    return stats


def get_outcomes(limit: int = 100) -> list[dict]:
    """Retrieve recent decision outcomes."""
    con = get_connection()
    df = con.execute("""
        SELECT * FROM decision_outcomes
        ORDER BY decision_date DESC
        LIMIT $1
    """, [limit]).fetchdf()
    con.close()
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def get_outcome_summary() -> dict:
    """Get high-level summary of decision outcomes with status breakdown."""
    con = get_connection()

    total = con.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0]
    classified = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL").fetchone()[0]
    pending = total - classified

    good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD'").fetchone()[0]
    bad = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'BAD'").fetchone()[0]
    neutral = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'NEUTRAL'").fetchone()[0]

    avg_excess_1m = con.execute("""
        SELECT AVG(excess_return_1m) FROM decision_outcomes WHERE excess_return_1m IS NOT NULL
    """).fetchone()[0]

    avg_excess_3m = con.execute("""
        SELECT AVG(excess_return_3m) FROM decision_outcomes WHERE excess_return_3m IS NOT NULL
    """).fetchone()[0]

    win_rate = good / classified if classified > 0 else None

    buy_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND action IN ('BUY','ADD')").fetchone()[0]
    buy_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND action IN ('BUY','ADD')").fetchone()[0]
    sell_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND action IN ('SELL','TRIM')").fetchone()[0]
    sell_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND action IN ('SELL','TRIM')").fetchone()[0]

    # Breakdown by proposal status (approved vs rejected vs pending)
    approved_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND proposal_status IN ('APPROVED', 'JUDGE_APPROVED')").fetchone()[0]
    approved_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND proposal_status IN ('APPROVED', 'JUDGE_APPROVED')").fetchone()[0]
    rejected_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND proposal_status IN ('REJECTED', 'JUDGE_REJECTED', 'NEEDS_REVIEW')").fetchone()[0]
    rejected_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND proposal_status IN ('REJECTED', 'JUDGE_REJECTED', 'NEEDS_REVIEW')").fetchone()[0]

    con.close()
    return {
        "total_decisions": total,
        "classified": classified,
        "pending_measurement": pending,
        "good": good,
        "bad": bad,
        "neutral": neutral,
        "win_rate": win_rate,
        "avg_excess_return_1m": avg_excess_1m,
        "avg_excess_return_3m": avg_excess_3m,
        "buy_win_rate": buy_good / buy_total if buy_total > 0 else None,
        "buy_total": buy_total,
        "sell_win_rate": sell_good / sell_total if sell_total > 0 else None,
        "sell_total": sell_total,
        "approved_win_rate": approved_good / approved_total if approved_total > 0 else None,
        "approved_total": approved_total,
        "rejected_win_rate": rejected_good / rejected_total if rejected_total > 0 else None,
        "rejected_total": rejected_total,
    }


def run_outcome_tracking() -> dict:
    """Full outcome tracking pipeline step: seed new outcomes + measure existing ones."""
    seeded = seed_outcomes_from_proposals()
    measurements = measure_outcomes()
    summary = get_outcome_summary()

    print(f"Outcome tracking: seeded {seeded} new from proposals, measured {measurements}")
    if summary['win_rate']:
        print(f"  Summary: {summary['classified']} classified, win rate: {summary['win_rate']:.0%}")
    else:
        print("  Summary: no outcomes classified yet")

    return {
        "seeded": seeded,
        "measurements": measurements,
        "summary": summary,
    }
