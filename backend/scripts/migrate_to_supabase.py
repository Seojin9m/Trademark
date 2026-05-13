"""One-time data migration: DuckDB -> Supabase Postgres.

Strategy
--------
For each table:
  1. Read from DuckDB into a pandas DataFrame
  2. Stream to Postgres via psycopg2's COPY FROM CSV (fastest bulk path)
  3. Commit each table independently so a partial failure doesn't lose
     all progress

JSON columns get json-encoded for Postgres' JSONB ingestion.
Date / timestamp columns get pandas-coerced.

Prereqs
-------
- Set SUPABASE_DB_URL_DIRECT (or SUPABASE_DB_URL) in your .env
- pip install psycopg2-binary
- Run schema init first:
    DB_BACKEND=postgres python -m src.db.schema

Run
---
    cd backend && python -u -m scripts.migrate_to_supabase

Tunables via env vars:
    MIGRATE_TABLES               comma-separated table allowlist (default: all)
    MIGRATE_DRY_RUN              if set, prints row counts but doesn't write to Postgres
    MIGRATE_PRICE_HISTORY_DAYS   limit `prices` table to most-recent N days
                                  (default 1827 = 5 years; set 0 for no limit).
                                  Required on Supabase free tier (500MB ceiling)
                                  because 10y of all-US-equity OHLCV won't fit.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


# Tables to migrate, in dependency order (none of these have FKs, but the
# order keeps logs readable: data tables first, then operational state).
# Each entry: (table_name, column_list_in_postgres_order, json_columns)
TABLES_TO_MIGRATE: list[tuple[str, Sequence[str], Sequence[str]]] = [
    # Market data
    ("prices",
     ["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"],
     []),
    ("fundamentals_pit",
     ["ticker", "fiscal_period_end", "report_date",
      "revenue", "gross_profit", "operating_income", "net_income",
      "eps_diluted", "shares_outstanding",
      "fiscal_year", "fiscal_quarter", "source"],
     []),
    ("macro_data",
     ["series_id", "date", "value"],
     []),
    # Computed signals
    ("factor_scores",
     ["ticker", "date", "momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy",
      "gross_margin_trend", "relative_valuation", "composite_score", "score_decile"],
     []),
    ("stock_quality_assessment",
     ["ticker", "date", "is_good_stock", "quality_score", "quality_reasons",
      "per_ratio", "per_vs_peer", "per_absolute_pass", "per_relative_pass",
      "price_opportunity_score"],
     ["quality_reasons"]),
    ("stock_metrics",
     ["ticker", "metric_name", "raw_value", "user_value", "source", "as_of_date"],
     []),
    # Trading state
    ("trade_proposals",
     ["proposal_id", "run_id", "created_at", "ticker", "action", "shares",
      "signal_data", "constraint_check", "status", "judge_response",
      "human_decision", "human_notes", "reason"],
     ["signal_data", "constraint_check", "judge_response"]),
    ("simulated_positions",
     ["ticker", "shares", "avg_cost_basis", "last_updated"],
     []),
    ("trade_executions",
     ["execution_id", "proposal_id", "run_id", "ticker", "action", "shares",
      "execution_price", "total_value", "execution_source",
      "pre_cash", "post_cash", "pre_position_shares", "post_position_shares",
      "success", "failure_reason", "executed_at"],
     []),
    ("portfolio_snapshots",
     ["snapshot_id", "snapshot_date", "total_value", "cash", "positions_value",
      "n_positions", "total_cost_basis", "unrealized_pnl", "total_return_pct",
      "benchmark_value", "benchmark_return_pct", "snapshot_source",
      "positions_detail", "created_at"],
     ["positions_detail"]),
    # Learning
    ("decision_outcomes",
     ["proposal_id", "execution_id", "ticker", "action", "decision_date",
      "entry_price", "shares", "composite_score", "score_decile", "prior_decile",
      "judge_verdict", "judge_confidence", "sector", "sub_sector", "factor_snapshot",
      "return_1w", "return_1m", "return_3m",
      "benchmark_return_1w", "benchmark_return_1m", "benchmark_return_3m",
      "excess_return_1w", "excess_return_1m", "excess_return_3m",
      "outcome_1m", "proposal_status",
      "measured_at_1w", "measured_at_1m", "measured_at_3m",
      "created_at", "updated_at"],
     ["factor_snapshot"]),
    ("decision_patterns",
     ["pattern_id", "dimension", "dimension_value", "sample_size",
      "win_rate", "avg_excess_return_1m", "avg_excess_return_3m",
      "best_ticker", "worst_ticker", "is_alert", "alert_message", "computed_at"],
     []),
    ("news_research",
     ["ticker", "research_date", "headlines", "ai_summary", "sentiment",
      "binary_events", "risk_factors", "opportunities", "data_sources",
      "confidence", "created_at"],
     ["headlines", "binary_events", "risk_factors", "opportunities", "data_sources"]),
    ("ingestion_log",
     ["data_type", "last_ingested_at", "record_count", "notes"],
     []),
]


def _duckdb_table_exists(con, table: str) -> bool:
    rows = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchall()
    return bool(rows)


def _read_duckdb_table(con, table: str, columns: Sequence[str]) -> pd.DataFrame:
    if not _duckdb_table_exists(con, table):
        return pd.DataFrame(columns=list(columns))
    # Get column list that actually exists in DuckDB — some new columns from
    # our Postgres schema (e.g. fiscal_year, fiscal_quarter, source on
    # fundamentals_pit) may be missing on older DuckDB databases.
    actual_cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()}
    selected = [c for c in columns if c in actual_cols]

    # Restrict `prices` (and any other date-partitionable table) to a recent
    # window so the migration fits under the Supabase free-tier 500MB ceiling.
    # 5 years (1827 days) of history is plenty for the 12-month momentum
    # factor and gives 4-5x headroom for future signal expansion. Older
    # history stays in the local DuckDB archive.
    where_clause = ""
    history_days = int(os.getenv("MIGRATE_PRICE_HISTORY_DAYS", "1827"))
    if table == "prices" and "date" in actual_cols and history_days > 0:
        where_clause = f" WHERE date >= CURRENT_DATE - INTERVAL '{history_days} days'"

    df = con.execute(
        f"SELECT {', '.join(selected)} FROM {table}{where_clause}"
    ).fetchdf()
    # Add missing columns as NaN so downstream COPY has the right shape
    for c in columns:
        if c not in df.columns:
            df[c] = None
    return df[list(columns)]


def _encode_json_columns(df: pd.DataFrame, json_cols: Sequence[str]) -> pd.DataFrame:
    """Postgres COPY needs JSONB columns as serialized JSON strings."""
    if df.empty or not json_cols:
        return df
    df = df.copy()
    for c in json_cols:
        if c in df.columns:
            df[c] = df[c].apply(
                lambda v: json.dumps(v) if not (v is None or (isinstance(v, float) and pd.isna(v))) else None
            )
    return df


def migrate_table(pg_conn, duck_conn, table: str, columns: Sequence[str], json_cols: Sequence[str], dry_run: bool) -> tuple[int, float]:
    t0 = time.time()
    df = _read_duckdb_table(duck_conn, table, columns)
    n = len(df)
    if n == 0:
        print(f"  {table:30s} (empty, skipping)")
        return 0, 0.0

    if dry_run:
        print(f"  {table:30s} {n:>10,} rows (DRY RUN)")
        return n, time.time() - t0

    df = _encode_json_columns(df, json_cols)
    # Write CSV to in-memory buffer for COPY FROM STDIN
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    with pg_conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table}")
        cur.copy_expert(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
            buf,
        )
    pg_conn.commit()
    elapsed = time.time() - t0
    print(f"  {table:30s} {n:>10,} rows  ({elapsed:.1f}s)")
    return n, elapsed


def migrate_universe_csv(pg_conn, dry_run: bool) -> None:
    """Port config/universe.csv into the new `universe` table."""
    csv_path = settings.paths.universe_path
    if not csv_path.exists():
        print(f"  universe (CSV not found at {csv_path}, skipping)")
        return

    df = pd.read_csv(csv_path)
    if df.empty:
        print("  universe (CSV empty, skipping)")
        return

    # Universe table columns (see 0001_initial_schema.sql)
    cols = ["ticker", "name", "sub_sector", "market_cap_tier",
            "median_dollar_volume", "quarters_available"]
    payload = df.reindex(columns=cols).copy()

    n = len(payload)
    if dry_run:
        print(f"  {'universe':30s} {n:>10,} rows (DRY RUN)")
        return

    buf = io.StringIO()
    payload.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    with pg_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE universe")
        cur.copy_expert(
            f"COPY universe ({', '.join(cols)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
            buf,
        )
    pg_conn.commit()
    print(f"  {'universe':30s} {n:>10,} rows  (from CSV)")


def migrate_portfolio_state(pg_conn, dry_run: bool) -> None:
    """Port data/portfolio_state.json into the singleton `portfolio_state` row."""
    state_path = settings.paths.portfolio_state_path
    if not state_path.exists():
        print(f"  portfolio_state (file not found, skipping)")
        return

    with open(state_path) as f:
        state = json.load(f)

    if dry_run:
        print(f"  portfolio_state              singleton (DRY RUN)")
        return

    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO portfolio_state (id, state, updated_at)
            VALUES (1, %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET
                state = EXCLUDED.state,
                updated_at = now()
        """, [json.dumps(state)])
    pg_conn.commit()
    print(f"  portfolio_state              singleton row")


def migrate_factor_weights(pg_conn, dry_run: bool) -> None:
    """Port config/factor_weights.json into the singleton `factor_weights_state` row."""
    fw_path = settings.paths.factor_weights_path
    if not fw_path.exists():
        print(f"  factor_weights_state (file not found, skipping)")
        return

    with open(fw_path) as f:
        weights = json.load(f)

    if dry_run:
        print(f"  factor_weights_state         singleton (DRY RUN)")
        return

    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO factor_weights_state (id, weights, updated_at)
            VALUES (1, %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET
                weights = EXCLUDED.weights,
                updated_at = now()
        """, [json.dumps(weights)])
    pg_conn.commit()
    print(f"  factor_weights_state         singleton row")


def main() -> None:
    dry_run = bool(os.getenv("MIGRATE_DRY_RUN"))
    allowlist_raw = os.getenv("MIGRATE_TABLES", "").strip()
    allowlist = set(t.strip() for t in allowlist_raw.split(",") if t.strip())

    print("=" * 70)
    print(f"  DuckDB -> Supabase Postgres migration {'(DRY RUN)' if dry_run else ''}")
    print("=" * 70)

    # DuckDB source
    import duckdb
    duck_path = str(settings.paths.duckdb_path)
    print(f"\nSource: DuckDB at {duck_path}")
    duck_conn = duckdb.connect(duck_path, read_only=True)

    # Postgres destination
    pg_conn = None
    if not dry_run:
        from src.db.postgres import get_pg_connection
        print(f"Destination: Supabase Postgres (direct connection for DDL)\n")
        pg_conn = get_pg_connection(role="direct")
    else:
        print()

    total_rows = 0
    total_seconds = 0.0
    print("--- Tables ---")
    for table, cols, json_cols in TABLES_TO_MIGRATE:
        if allowlist and table not in allowlist:
            continue
        try:
            n, t = migrate_table(pg_conn, duck_conn, table, cols, json_cols, dry_run)
            total_rows += n
            total_seconds += t
        except Exception as e:
            print(f"  {table:30s} FAILED: {e}")

    if not allowlist or "universe" in allowlist:
        print("\n--- Config files -> tables ---")
        try:
            migrate_universe_csv(pg_conn, dry_run)
        except Exception as e:
            print(f"  universe FAILED: {e}")
        try:
            migrate_portfolio_state(pg_conn, dry_run)
        except Exception as e:
            print(f"  portfolio_state FAILED: {e}")
        try:
            migrate_factor_weights(pg_conn, dry_run)
        except Exception as e:
            print(f"  factor_weights_state FAILED: {e}")

    duck_conn.close()
    if pg_conn is not None:
        pg_conn.close()

    print(f"\nMigration complete: {total_rows:,} rows in {total_seconds:.1f}s")
    if dry_run:
        print("\n(DRY RUN -- no data was written to Postgres.)")


if __name__ == "__main__":
    main()
