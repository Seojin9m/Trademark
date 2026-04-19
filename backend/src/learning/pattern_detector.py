"""Pattern detector: aggregate decision outcomes into actionable patterns.

Analyzes win rates and excess returns across multiple dimensions:
- By sub-sector (e.g., "semiconductors buys win 35% of the time")
- By action type (BUY vs SELL vs TRIM)
- By judge verdict (APPROVE vs NEEDS_REVIEW)
- By score decile at entry
- By factor profile (which factor was dominant)

Generates alerts when patterns are concerning (low win rate with enough sample size).
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection

MIN_SAMPLE_SIZE = 5  # Don't flag patterns with fewer than this many decisions
ALERT_WIN_RATE_THRESHOLD = 0.40  # Alert if win rate drops below 40%


def _compute_dimension_patterns(con, dimension: str, query: str) -> list[dict]:
    """Run a grouping query and build pattern records."""
    rows = con.execute(query).fetchall()
    patterns = []

    for row in rows:
        dim_value, total, good, bad, neutral, avg_excess_1m, avg_excess_3m, best, worst = row
        if total == 0:
            continue

        win_rate = good / total if total > 0 else 0
        is_alert = total >= MIN_SAMPLE_SIZE and win_rate < ALERT_WIN_RATE_THRESHOLD
        alert_msg = None
        if is_alert:
            alert_msg = f"{dimension}='{dim_value}' has {win_rate:.0%} win rate ({good}/{total} good) — avg excess 1m: {avg_excess_1m:.1%}" if avg_excess_1m else f"{dimension}='{dim_value}' has {win_rate:.0%} win rate ({good}/{total} good)"

        patterns.append({
            "pattern_id": str(uuid.uuid4())[:8],
            "dimension": dimension,
            "dimension_value": str(dim_value) if dim_value else "unknown",
            "sample_size": total,
            "win_rate": win_rate,
            "avg_excess_return_1m": avg_excess_1m,
            "avg_excess_return_3m": avg_excess_3m,
            "best_ticker": best,
            "worst_ticker": worst,
            "is_alert": is_alert,
            "alert_message": alert_msg,
        })

    return patterns


def detect_patterns() -> list[dict]:
    """Analyze all classified decision outcomes and detect patterns.

    Returns list of pattern dicts and stores them in decision_patterns table.
    """
    con = get_connection()

    # Check we have enough data
    total = con.execute(
        "SELECT COUNT(*) FROM decision_outcomes WHERE outcome_1m IS NOT NULL"
    ).fetchone()[0]

    if total < 3:
        con.close()
        return []

    all_patterns = []

    # --- Pattern 1: By sub-sector ---
    patterns = _compute_dimension_patterns(con, "sub_sector", """
        SELECT sub_sector,
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END) as good,
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END) as bad,
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END) as neutral,
               AVG(excess_return_1m) as avg_excess_1m,
               AVG(excess_return_3m) as avg_excess_3m,
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.sub_sector = d.sub_sector AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m DESC LIMIT 1) as best,
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.sub_sector = d.sub_sector AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m ASC LIMIT 1) as worst
        FROM decision_outcomes d
        WHERE outcome_1m IS NOT NULL
        GROUP BY sub_sector
    """)
    all_patterns.extend(patterns)

    # --- Pattern 2: By action type ---
    patterns = _compute_dimension_patterns(con, "action", """
        SELECT action,
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END),
               AVG(excess_return_1m),
               AVG(excess_return_3m),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.action = d.action AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m DESC LIMIT 1),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.action = d.action AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m ASC LIMIT 1)
        FROM decision_outcomes d
        WHERE outcome_1m IS NOT NULL
        GROUP BY action
    """)
    all_patterns.extend(patterns)

    # --- Pattern 3: By judge verdict ---
    patterns = _compute_dimension_patterns(con, "judge_verdict", """
        SELECT judge_verdict,
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END),
               AVG(excess_return_1m),
               AVG(excess_return_3m),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.judge_verdict = d.judge_verdict AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m DESC LIMIT 1),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.judge_verdict = d.judge_verdict AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m ASC LIMIT 1)
        FROM decision_outcomes d
        WHERE outcome_1m IS NOT NULL AND judge_verdict IS NOT NULL
        GROUP BY judge_verdict
    """)
    all_patterns.extend(patterns)

    # --- Pattern 4: By score decile at entry ---
    patterns = _compute_dimension_patterns(con, "score_decile", """
        SELECT score_decile,
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END),
               AVG(excess_return_1m),
               AVG(excess_return_3m),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.score_decile = d.score_decile AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m DESC LIMIT 1),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.score_decile = d.score_decile AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m ASC LIMIT 1)
        FROM decision_outcomes d
        WHERE outcome_1m IS NOT NULL AND score_decile IS NOT NULL
        GROUP BY score_decile
    """)
    all_patterns.extend(patterns)

    # --- Pattern 5: By proposal status (approved vs rejected) ---
    patterns = _compute_dimension_patterns(con, "proposal_status", """
        SELECT proposal_status,
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END),
               AVG(excess_return_1m),
               AVG(excess_return_3m),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.proposal_status = d.proposal_status AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m DESC LIMIT 1),
               (SELECT ticker FROM decision_outcomes d2
                WHERE d2.proposal_status = d.proposal_status AND d2.excess_return_1m IS NOT NULL
                ORDER BY d2.excess_return_1m ASC LIMIT 1)
        FROM decision_outcomes d
        WHERE outcome_1m IS NOT NULL AND proposal_status IS NOT NULL
        GROUP BY proposal_status
    """)
    all_patterns.extend(patterns)

    # --- Pattern 6: Overall ---
    patterns = _compute_dimension_patterns(con, "overall", """
        SELECT 'all_decisions',
               COUNT(*) as total,
               SUM(CASE WHEN outcome_1m = 'GOOD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'BAD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome_1m = 'NEUTRAL' THEN 1 ELSE 0 END),
               AVG(excess_return_1m),
               AVG(excess_return_3m),
               (SELECT ticker FROM decision_outcomes
                WHERE excess_return_1m IS NOT NULL
                ORDER BY excess_return_1m DESC LIMIT 1),
               (SELECT ticker FROM decision_outcomes
                WHERE excess_return_1m IS NOT NULL
                ORDER BY excess_return_1m ASC LIMIT 1)
        FROM decision_outcomes
        WHERE outcome_1m IS NOT NULL
    """)
    all_patterns.extend(patterns)

    # Store patterns (replace old ones)
    con.execute("DELETE FROM decision_patterns")
    for p in all_patterns:
        con.execute("""
            INSERT INTO decision_patterns
            (pattern_id, dimension, dimension_value, sample_size,
             win_rate, avg_excess_return_1m, avg_excess_return_3m,
             best_ticker, worst_ticker, is_alert, alert_message, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """, [
            p["pattern_id"], p["dimension"], p["dimension_value"], p["sample_size"],
            p["win_rate"], p["avg_excess_return_1m"], p["avg_excess_return_3m"],
            p["best_ticker"], p["worst_ticker"], p["is_alert"], p["alert_message"],
            datetime.now().isoformat(),
        ])

    con.close()

    alerts = [p for p in all_patterns if p["is_alert"]]
    if alerts:
        print(f"Pattern detection: {len(all_patterns)} patterns, {len(alerts)} ALERTS:")
        for a in alerts:
            print(f"  ! {a['alert_message']}")
    else:
        print(f"Pattern detection: {len(all_patterns)} patterns, no alerts")

    return all_patterns


def get_patterns() -> list[dict]:
    """Retrieve the latest computed patterns."""
    con = get_connection()
    df = con.execute("""
        SELECT * FROM decision_patterns ORDER BY dimension, sample_size DESC
    """).fetchdf()
    con.close()
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def get_alerts() -> list[dict]:
    """Retrieve only alerting patterns."""
    con = get_connection()
    df = con.execute("""
        SELECT * FROM decision_patterns WHERE is_alert = TRUE ORDER BY win_rate ASC
    """).fetchdf()
    con.close()
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def find_similar_decisions(ticker: str, score_decile: int, sub_sector: str | None = None, limit: int = 5) -> list[dict]:
    """Find past decisions with similar characteristics for judge context injection.

    Similarity criteria (in priority order):
    1. Same ticker (exact match)
    2. Same sub_sector + similar decile (±1)
    3. Same decile range
    """
    con = get_connection()
    results = []

    # Same ticker — most relevant
    same_ticker = con.execute("""
        SELECT * FROM decision_outcomes
        WHERE ticker = $1 AND outcome_1m IS NOT NULL
        ORDER BY decision_date DESC LIMIT 3
    """, [ticker]).fetchdf()
    if not same_ticker.empty:
        results.extend(json.loads(same_ticker.to_json(orient="records", date_format="iso")))

    # Same sub_sector + similar decile
    if sub_sector and len(results) < limit:
        remaining = limit - len(results)
        similar = con.execute("""
            SELECT * FROM decision_outcomes
            WHERE sub_sector = $1
              AND ABS(score_decile - $2) <= 1
              AND ticker != $3
              AND outcome_1m IS NOT NULL
            ORDER BY decision_date DESC LIMIT $4
        """, [sub_sector, score_decile, ticker, remaining]).fetchdf()
        if not similar.empty:
            results.extend(json.loads(similar.to_json(orient="records", date_format="iso")))

    # Fill remaining with same decile
    if len(results) < limit:
        existing_ids = [r["proposal_id"] for r in results]
        remaining = limit - len(results)
        same_decile = con.execute("""
            SELECT * FROM decision_outcomes
            WHERE score_decile = $1
              AND outcome_1m IS NOT NULL
            ORDER BY decision_date DESC LIMIT $2
        """, [score_decile, remaining + len(existing_ids)]).fetchdf()
        if not same_decile.empty:
            for rec in json.loads(same_decile.to_json(orient="records", date_format="iso")):
                if rec["proposal_id"] not in existing_ids and len(results) < limit:
                    results.append(rec)

    con.close()
    return results[:limit]
