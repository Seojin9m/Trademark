"""Outcome tracker: measures decision returns and classifies GOOD/BAD/NEUTRAL.

For each executed trade, tracks the stock's performance at
1-week, 1-month, and 3-month horizons relative to the benchmark (QQQ).

Outcome classification (based on 1-month excess return):
  GOOD:    excess return >= +2%  (BUY that beat market, or SELL where stock dropped)
  BAD:     excess return <= -2%  (BUY that lagged market, or SELL where stock rallied)
  NEUTRAL: between -2% and +2%
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection

# Trading days approximation for horizons
HORIZON_TRADING_DAYS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
}

OUTCOME_THRESHOLDS = {
    "GOOD": 0.02,    # >= +2% excess
    "BAD": -0.02,    # <= -2% excess
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
    """Get the adj_close approximately N trading days after start_date.

    Returns (price, actual_date) or (None, None) if not enough data.
    """
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


def seed_outcomes_from_executions() -> int:
    """Seed decision_outcomes from trade_executions that don't have outcomes yet.

    Only seeds from successful executions — these are trades that actually happened,
    not just proposals that were approved.
    """
    con = get_connection()
    universe = pd.read_csv(settings.paths.universe_path)
    sector_map = dict(zip(universe["ticker"], universe.get("sub_sector", pd.Series())))

    # Find successful executions that don't have outcomes yet
    new_executions = con.execute("""
        SELECT te.execution_id, te.proposal_id, te.ticker, te.action,
               te.executed_at, te.shares, te.execution_price,
               tp.signal_data, tp.judge_response
        FROM trade_executions te
        LEFT JOIN decision_outcomes dout ON te.execution_id = dout.execution_id
        LEFT JOIN trade_proposals tp ON te.proposal_id = tp.proposal_id
        WHERE dout.execution_id IS NULL
          AND te.success = TRUE
          AND te.shares > 0
    """).fetchall()

    seeded = 0
    for row in new_executions:
        execution_id, proposal_id, ticker, action, executed_at, shares, execution_price, signal_data_raw, judge_response_raw = row

        # Parse signal data
        signal_data = json.loads(signal_data_raw) if isinstance(signal_data_raw, str) else (signal_data_raw or {})
        judge_response = json.loads(judge_response_raw) if isinstance(judge_response_raw, str) else (judge_response_raw or {})

        decision_date = str(executed_at)[:10]

        con.execute("""
            INSERT INTO decision_outcomes
            (proposal_id, execution_id, ticker, action, decision_date, entry_price, shares,
             composite_score, score_decile, prior_decile,
             judge_verdict, judge_confidence,
             sector, sub_sector, factor_snapshot)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """, [
            proposal_id,
            execution_id,
            ticker,
            action,
            decision_date,
            execution_price,  # Use actual execution price, not market close
            shares,
            signal_data.get("composite_score"),
            signal_data.get("decile"),
            signal_data.get("prior_decile"),
            judge_response.get("verdict"),
            judge_response.get("confidence"),
            universe.loc[universe["ticker"] == ticker, "sub_sector"].iloc[0] if not universe.loc[universe["ticker"] == ticker, "sub_sector"].empty else None,
            sector_map.get(ticker),
            json.dumps(signal_data.get("factors", {})),
        ])
        seeded += 1

    con.close()
    return seeded


def measure_outcomes() -> dict:
    """Measure returns for all decision_outcomes that have unmeasured horizons.

    For BUY/ADD: measures if the stock went up (good) or down (bad) vs benchmark.
    For SELL/TRIM: inverts the return — stock dropping after sell = GOOD decision.

    Returns summary of measurements made.
    """
    con = get_connection()
    benchmark = settings.primary_benchmark

    # Get outcomes that still need measurement at any horizon
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

            # Check if already measured
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

                # For SELL/TRIM: invert the return
                # If we sold and the stock dropped 5%, that's a +5% "decision return" (good call)
                # If we sold and the stock rose 8%, that's a -8% "decision return" (bad call)
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
            # Build dynamic UPDATE
            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
            values = list(updates.values())

            con.execute(f"""
                UPDATE decision_outcomes
                SET {set_clauses}, updated_at = CURRENT_TIMESTAMP
                WHERE proposal_id = $1
            """, [proposal_id] + values)

            # Classify outcome based on 1m excess return
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
    """Get high-level summary of decision outcomes."""
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

    # Breakdown by action type
    buy_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND action IN ('BUY','ADD')").fetchone()[0]
    buy_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND action IN ('BUY','ADD')").fetchone()[0]
    sell_good = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m = 'GOOD' AND action IN ('SELL','TRIM')").fetchone()[0]
    sell_total = con.execute("SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL AND action IN ('SELL','TRIM')").fetchone()[0]

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
    }


def run_outcome_tracking() -> dict:
    """Full outcome tracking pipeline step: seed new outcomes + measure existing ones."""
    seeded = seed_outcomes_from_executions()
    measurements = measure_outcomes()
    summary = get_outcome_summary()

    print(f"Outcome tracking: seeded {seeded} new, measured {measurements}")
    print(f"  Summary: {summary['classified']} classified, "
          f"win rate: {summary['win_rate']:.0%}" if summary['win_rate'] else "  Summary: no outcomes classified yet")

    return {
        "seeded": seeded,
        "measurements": measurements,
        "summary": summary,
    }
