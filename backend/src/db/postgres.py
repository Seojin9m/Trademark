"""Postgres connection helpers for the Supabase backend.

This module is the Postgres half of the dual-backend transition. The main
`src/db/schema.py:get_connection()` reads an env var and routes to either
DuckDB (legacy) or Postgres (this module).

Connection strings come from Supabase's project settings. The recommended
pattern is:
    - SUPABASE_DB_URL_POOLED   -> use for app traffic (PgBouncer-pooled, port 6543)
    - SUPABASE_DB_URL_DIRECT   -> use for migrations only (port 5432)

We expose two helpers because PgBouncer transaction mode (Supabase default)
doesn't support session-scoped features like prepared statements or
`SET LOCAL` — anything that mutates schema needs the direct connection.
"""

from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

try:
    import psycopg2
    from psycopg2.extensions import connection as PGConnection
except ImportError:
    psycopg2 = None  # Module imports cleanly even if psycopg2 isn't installed yet
    PGConnection = object  # type: ignore


# ============================================================================
# DuckDB-compatible adapter
# ============================================================================
# The codebase has ~281 callsites that use DuckDB's chained API:
#     con.execute(sql).fetchdf()
#     con.execute(sql, [params]).fetchone()
#     con.execute(sql, [params]).fetchall()
# psycopg2's API requires getting a cursor first:
#     cur = con.cursor(); cur.execute(...); cur.fetchall()
# Rather than refactor every callsite, we wrap the psycopg2 connection in
# an adapter that exposes the DuckDB surface. App code stays unchanged;
# only the migration script (which still uses raw psycopg2 via .cursor())
# and the ingestion COPY paths bypass the adapter.


# DuckDB uses both ? and $1/$2 placeholders. Postgres uses %s. Translate.
_PLACEHOLDER_RE = re.compile(r"\?|\$\d+")
_DOLLAR_N_RE = re.compile(r"\$(\d+)")
_HAS_DOLLAR_RE = re.compile(r"\$\d+")


def _translate_sql_and_params(sql: str, params):
    """Translate DuckDB-style placeholders to psycopg2 %s, reordering params.

    DuckDB / Postgres `$N` placeholders are POSITIONAL by INDEX: `$2` always
    means "the 2nd parameter" regardless of where it appears in the SQL,
    and the same `$N` can appear multiple times. psycopg2's `%s` is
    POSITIONAL BY OCCURRENCE: each `%s` consumes the next param in order.
    We bridge the two semantics by walking each `$N` occurrence and
    rewriting the params list so they appear in the same order as the
    `%s` placeholders in the translated SQL.

    `?` placeholders behave like `%s` (one param per occurrence in order),
    so when the SQL uses only `?` we just swap the syntax and leave params
    alone. Mixed `?` and `$N` in the same query is not used in this
    codebase and is intentionally unsupported here.
    """
    if not params:
        return _PLACEHOLDER_RE.sub("%s", sql), params

    if not _HAS_DOLLAR_RE.search(sql):
        # Pure `?` style — positional, no reordering needed.
        return sql.replace("?", "%s"), list(params)

    reordered: list = []

    def _sub(m: re.Match) -> str:
        n = int(m.group(1))
        try:
            reordered.append(params[n - 1])
        except IndexError:
            raise IndexError(
                f"SQL references $${n} but only {len(params)} params provided: {sql[:120]}"
            )
        return "%s"

    translated = _DOLLAR_N_RE.sub(_sub, sql)
    return translated, reordered


def _translate_placeholders(sql: str) -> str:
    """Legacy helper kept for callers that don't need param reordering.

    Use _translate_sql_and_params for any execute() path that passes
    parameters — it preserves $N positional semantics.
    """
    return _PLACEHOLDER_RE.sub("%s", sql)


class _PgResult:
    """DuckDB-compatible result wrapper for a psycopg2 cursor.

    Mirrors DuckDB's chainable .fetchdf() / .fetchone() / .fetchall() so
    callers can write `con.execute(sql).fetchdf()` and have it just work.
    Closes the cursor after the first fetch to avoid resource leaks.
    """

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchdf(self) -> pd.DataFrame:
        rows = self._cursor.fetchall()
        cols = (
            [d[0] for d in self._cursor.description]
            if self._cursor.description
            else []
        )
        df = pd.DataFrame(rows, columns=cols)
        self._cursor.close()
        return df

    def fetchone(self):
        row = self._cursor.fetchone()
        self._cursor.close()
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        self._cursor.close()
        return rows


class PgConnectionAdapter:
    """psycopg2 connection wearing a DuckDB-shaped suit.

    Designed so existing call sites work unchanged:
        con = get_connection()
        df = con.execute("SELECT ... WHERE ticker = ?", [t]).fetchdf()
        con.close()
    Autocommit is on by default because most app queries are read-only,
    and the write paths (store_prices, store_fundamentals) have their own
    Postgres branches that use the underlying raw connection.
    """

    def __init__(self, pg_conn: PGConnection):
        self._conn = pg_conn
        # Match DuckDB's "implicit autocommit" semantics for app queries.
        # Migration scripts use the raw psycopg2 conn (get_pg_connection)
        # and manage their own transactions.
        self._conn.autocommit = True

    def execute(self, sql: str, params=None) -> _PgResult:
        cursor = self._conn.cursor()
        try:
            if params is None:
                cursor.execute(_translate_placeholders(sql))
            else:
                sql_pg, params_pg = _translate_sql_and_params(sql, params)
                cursor.execute(sql_pg, params_pg)
        except Exception:
            cursor.close()
            raise
        return _PgResult(cursor)

    def register(self, name, df):
        """DuckDB lets you register a DataFrame as a virtual table.

        Postgres has no equivalent. Anywhere we hit this in app code, the
        right fix is to add a Postgres branch that uses COPY FROM. We
        raise NotImplementedError so the failure is loud rather than
        silent data corruption.
        """
        raise NotImplementedError(
            f"PgConnectionAdapter.register({name!r}) is not supported. "
            "Use psycopg2 COPY or pandas.to_sql() in a Postgres code path."
        )

    def close(self) -> None:
        self._conn.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def cursor(self):
        """Escape hatch: get the raw psycopg2 cursor for code that needs
        copy_expert, executemany, or other psycopg2-specific features."""
        return self._conn.cursor()

    @property
    def raw(self):
        """The underlying psycopg2 connection."""
        return self._conn


def _read_dsn(role: str) -> str:
    """Read the Postgres connection string for `role` ('pooled' | 'direct')."""
    if role == "pooled":
        dsn = os.getenv("SUPABASE_DB_URL_POOLED") or os.getenv("SUPABASE_DB_URL")
    elif role == "direct":
        dsn = os.getenv("SUPABASE_DB_URL_DIRECT") or os.getenv("SUPABASE_DB_URL")
    else:
        raise ValueError(f"Unknown role: {role}")
    if not dsn:
        raise RuntimeError(
            f"No Postgres DSN configured for role={role!r}. "
            "Set SUPABASE_DB_URL_POOLED (or SUPABASE_DB_URL as fallback) in your .env."
        )
    return dsn


def get_pg_connection(role: str = "pooled", max_retries: int = 5, retry_delay: float = 0.5) -> PGConnection:
    """Open a Postgres connection with retry on transient network errors.

    `role`: "pooled" for app queries (port 6543 via PgBouncer), "direct" for
    DDL / migrations (port 5432). Pooled connections are required when running
    on serverless platforms; the direct one is for migration scripts.
    """
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 not installed. Run: pip install psycopg2-binary"
        )

    dsn = _read_dsn(role)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return psycopg2.connect(dsn, connect_timeout=10)
        except psycopg2.OperationalError as exc:
            last_exc = exc
            # Backoff: 0.5s, 1s, 2s, 4s, 8s
            time.sleep(retry_delay * (2 ** attempt))
    raise RuntimeError(
        f"Could not connect to Postgres after {max_retries} retries: {last_exc}"
    )


@contextmanager
def pg_cursor(role: str = "pooled") -> Iterator:
    """Context-managed cursor that commits on exit, rolls back on exception."""
    conn = get_pg_connection(role=role)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations(migrations_dir: str) -> None:
    """Apply all *.sql files in `migrations_dir` in lexicographic order.

    Idempotent if the SQL files use `CREATE TABLE IF NOT EXISTS` / `CREATE
    INDEX IF NOT EXISTS` patterns (which our migrations do). Records applied
    migrations in `_schema_migrations` so re-runs are fast no-ops.
    """
    from pathlib import Path

    conn = get_pg_connection(role="direct")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS _schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            conn.commit()

            cur.execute("SELECT name FROM _schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

            files = sorted(Path(migrations_dir).glob("*.sql"))
            for f in files:
                if f.name in applied:
                    print(f"  Skipping {f.name} (already applied)")
                    continue
                print(f"  Applying {f.name}...")
                # Force utf-8: pathlib default on Windows is cp1252 / cp949,
                # which chokes on UTF-8 em-dashes in our SQL comments.
                cur.execute(f.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO _schema_migrations (name) VALUES (%s)", (f.name,)
                )
                conn.commit()
                print(f"    Done.")
    finally:
        conn.close()
