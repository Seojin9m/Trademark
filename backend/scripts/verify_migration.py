"""Verify DuckDB -> Supabase Postgres migration.

Performs three classes of checks:
  1. Row count parity per table (DuckDB count == Postgres count)
  2. Spot-check critical tickers (price coverage matches by ticker)
  3. Schema sanity (all expected tables exist in Postgres)

Exits non-zero on any mismatch so you can wire this into CI later.

Run
---
    cd backend && python -u -m scripts.verify_migration
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.db.postgres import get_pg_connection


# Tables we expect to exist + check rowcount parity. Mirrors
# scripts/migrate_to_supabase.py:TABLES_TO_MIGRATE.
TABLES_TO_VERIFY = [
    "prices",
    "fundamentals_pit",
    "macro_data",
    "factor_scores",
    "stock_quality_assessment",
    "stock_metrics",
    "trade_proposals",
    "simulated_positions",
    "trade_executions",
    "portfolio_snapshots",
    "decision_outcomes",
    "decision_patterns",
    "news_research",
    "ingestion_log",
]

NEW_TABLES = ["universe", "universe_history", "portfolio_state",
              "factor_weights_state", "pipeline_runs"]

# Critical names whose price coverage we spot-check across both backends.
SPOT_CHECK_TICKERS = ["AAPL", "MSFT", "GOOGL", "NVDA", "MO", "LRCX", "SPY", "QQQ"]


def main() -> int:
    failures: list[str] = []
    duck_conn = duckdb.connect(str(settings.paths.duckdb_path), read_only=True)
    pg_conn = get_pg_connection(role="direct")

    # ---------- 1. Schema presence ----------
    print("--- Schema presence ---")
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        pg_tables = {row[0] for row in cur.fetchall()}
    for t in TABLES_TO_VERIFY + NEW_TABLES:
        if t in pg_tables:
            print(f"  OK {t}")
        else:
            print(f"  FAIL {t} MISSING in Postgres")
            failures.append(f"table missing: {t}")

    # ---------- 2. Rowcount parity ----------
    # `prices` is intentionally truncated to the last N days (see
    # migrate_to_supabase.MIGRATE_PRICE_HISTORY_DAYS). We expect the Postgres
    # count to be smaller than DuckDB's by exactly the rows older than the
    # cutoff — so we re-count DuckDB rows inside the same window and compare
    # against that filtered count instead of the full 10-year table.
    history_days = int(os.getenv("MIGRATE_PRICE_HISTORY_DAYS", "1827"))
    print("\n--- Rowcount parity (DuckDB vs Postgres) ---")
    print(f"  prices is filtered to last {history_days} days "
          "(set MIGRATE_PRICE_HISTORY_DAYS=0 to compare full table)\n")
    print(f"  {'table':30s} {'duck':>10s} {'postgres':>10s} {'diff':>8s}")
    for table in TABLES_TO_VERIFY:
        try:
            if table == "prices" and history_days > 0:
                duck_count = duck_conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE date >= CURRENT_DATE - INTERVAL '{history_days} days'"
                ).fetchone()[0]
            else:
                duck_count = duck_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
        except Exception:
            duck_count = 0
        try:
            with pg_conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                pg_count = cur.fetchone()[0]
        except Exception as e:
            print(f"  {table:30s} ERROR querying Postgres: {e}")
            failures.append(f"pg count failed: {table}")
            continue

        diff = pg_count - duck_count
        flag = "OK" if duck_count == pg_count else "FAIL"
        print(f"  {flag} {table:30s} {duck_count:>10,} {pg_count:>10,} {diff:>+8,}")
        if duck_count != pg_count:
            failures.append(f"count mismatch on {table}: duck={duck_count} pg={pg_count}")

    # ---------- 3. Per-ticker spot check on prices ----------
    # Same as above: compare DuckDB within the truncation window so the
    # intentional 5-year cutoff doesn't show as a failure.
    print("\n--- Per-ticker price coverage spot check ---")
    print(f"  {'ticker':8s} {'duck rows':>10s} {'pg rows':>10s} {'min date match':>16s} {'max date match':>16s}")
    for t in SPOT_CHECK_TICKERS:
        try:
            if history_days > 0:
                duck_row = duck_conn.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) FROM prices "
                    "WHERE ticker = ? AND date >= CURRENT_DATE - INTERVAL '%d days'" % history_days,
                    [t]
                ).fetchone()
            else:
                duck_row = duck_conn.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) FROM prices WHERE ticker = ?", [t]
                ).fetchone()
            duck_count, duck_min, duck_max = duck_row
        except Exception:
            duck_count, duck_min, duck_max = 0, None, None

        try:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) FROM prices WHERE ticker = %s", [t]
                )
                pg_row = cur.fetchone()
                pg_count, pg_min, pg_max = pg_row
        except Exception as e:
            print(f"  {t:8s} ERROR: {e}")
            continue

        min_ok = str(duck_min) == str(pg_min)
        max_ok = str(duck_max) == str(pg_max)
        cnt_ok = duck_count == pg_count
        flag = "OK" if (min_ok and max_ok and cnt_ok) else "FAIL"
        print(f"  {flag} {t:6s} {duck_count:>10,} {pg_count:>10,} {str(duck_min) + '==' + str(pg_min) if min_ok else 'NO':>16s} {str(duck_max) + '==' + str(pg_max) if max_ok else 'NO':>16s}")
        if not (min_ok and max_ok and cnt_ok):
            failures.append(f"spot-check failed for {t}")

    duck_conn.close()
    pg_conn.close()

    # ---------- Summary ----------
    print("\n" + "=" * 70)
    if failures:
        print(f"  {len(failures)} verification failure(s):")
        for f in failures[:25]:
            print(f"    - {f}")
        if len(failures) > 25:
            print(f"    ... and {len(failures) - 25} more")
        print("=" * 70)
        return 1
    print("  All checks passed OK")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
