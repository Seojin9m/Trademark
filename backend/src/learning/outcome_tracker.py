"""Outcome tracker: measures decision returns and classifies GOOD/BAD/NEUTRAL.

For each completed trade proposal, tracks the stock's performance at
1-week, 1-month, and 3-month horizons relative to the benchmark (QQQ).

Outcome classification (based on 1-month excess return):
  GOOD:    excess return >= +2%
  BAD:     excess return <= -2%
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


def seed_outcomes_from_proposals() -> int:
    """Seed decision_outcomes from trade_proposals that don't have outcomes yet.

    This links each approved/executed proposal to the outcome tracking table
    so we can measure returns over time.
    """
    con = get_connection()
    universe = pd.read_csv(settings.paths.universe_path)
    sector_map = dict(zip(universe["ticker"], universe.get("sub_sector", pd.Series())))

    # Find proposals that were approved by judge but don't have outcomes yet
    new_proposals = con.execute("""
        SELECT tp.proposal_id, tp.ticker, tp.action, tp.created_at, tp.shares,
               tp.signal_data, tp.judge_response, tp.status
        FROM trade_proposals tp
        LEFT JOIN decision_outcomes do ON tp.proposal_id = do.proposal_id
        WHERE do.proposal_id IS NULL
          AND tp.status IN ('JUDGE_APPROVED', 'APPROVED', 'NEEDS_REVIEW')
    """).fetchall()

    seeded = 0
    for row in new_proposals:
        proposal_id, ticker, action, created_at, shares, signal_data_raw, judge_response_raw, status = row

        # Parse signal data
        signal_data = json.loads(signal_data_raw) if isinstance(signal_data_raw, str) else (signal_data_raw or {})
        judge_response = json.loads(judge_response_raw) if isinstance(judge_response_raw, str) else (judge_response_raw or {})

        decision_date = str(created_at)[:10]
        entry_price = _get_price_on_date(con, ticker, decision_date)

        con.execute("""
            INSERT INTO decision_outcomes
            (proposal_id, ticker, action, decision_date, entry_price, shares,
             composite_score, score_decile, prior_decile,
             judge_verdict, judge_confidence,
             sector, sub_sector, factor_snapshot)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        """, [
            proposal_id,
            ticker,
            action,
            decision_date,
            entry_price,
            shares,
            signal_data.get("composite_score"),
            signal_data.get("decile"),
            signal_data.get("prior_decile"),
            judge_response.get("verdict"),
            judge_response.get("confidence"),
            universe.loc[universe["ticker"] == ticker, "sector"].iloc[0] if not universe.loc[universe["ticker"] == ticker, "sector"].empty else None,
            sector_map.get(ticker),
            json.dumps(signal_data.get("factors", {})),
        ])
        seeded += 1

    con.close()
    return seeded


def measure_outcomes() -> dict:
    """Measure returns for all decision_outcomes that have unmeasured horizons.

    Computes stock return and benchmark return at each horizon, then
    calculates excess return and classifies the outcome.

    Returns summary of measurements made.
    """
    con = get_connection()
    benchmark = settings.primary_benchmark

    # Get outcomes that still need measurement at any horizon
    outcomes = con.execute("""
        SELECT proposal_id, ticker, decision_date, entry_price
        FROM decision_outcomes
        WHERE entry_price IS NOT NULL
          AND (return_1w IS NULL OR return_1m IS NULL OR return_3m IS NULL)
    """).fetchall()

    stats = {"measured_1w": 0, "measured_1m": 0, "measured_3m": 0, "classified": 0}

    for proposal_id, ticker, decision_date, entry_price in outcomes:
        decision_date_str = str(decision_date)
        benchmark_entry = _get_price_on_date(con, benchmark, decision_date_str)
        updates = {}

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
            stock_return = _compute_return(entry_price, exit_price)

            if stock_return is not None:
                bench_exit, _ = _get_price_after_days(con, benchmark, decision_date_str, trading_days)
                bench_return = _compute_return(benchmark_entry, bench_exit) if benchmark_entry else None
                excess = (stock_return - bench_return) if bench_return is not None else None

                updates[return_col] = stock_return
                updates[measured_col] = exit_date
                updates[bench_col] = bench_return
                updates[excess_col] = excess
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
        LIMIT ?
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
    }


def run_outcome_tracking() -> dict:
    """Full outcome tracking pipeline step: seed new outcomes + measure existing ones."""
    seeded = seed_outcomes_from_proposals()
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
