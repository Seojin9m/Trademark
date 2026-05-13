"""Backend-agnostic helpers for the four legacy non-DuckDB state sources.

Each function chooses Postgres or local file based on DB_BACKEND so the
rest of the codebase can stop caring about where state lives:

  - load_portfolio_state / save_portfolio_state
        portfolio_state.json   <->   portfolio_state (JSONB singleton)
  - load_universe_df
        config/universe.csv    <->   universe table
  - load_factor_weights_state / save_factor_weights_state
        config/factor_weights.json (currently unused; kept for future)

The legacy file path is the source of truth in DB_BACKEND=duckdb mode and
the fallback if the Postgres table is empty (so first-time migration is
graceful). In DB_BACKEND=postgres mode the table is authoritative.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from config.settings import settings


def _backend() -> str:
    return (os.getenv("DB_BACKEND") or "duckdb").lower()


# ============================================================================
# Portfolio state
# ============================================================================

_DEFAULT_PORTFOLIO: dict[str, Any] = {
    "as_of_date": None,
    "cash": 100_000.0,
    "currency": "CAD",
    "positions": [],
}


def load_portfolio_state() -> dict[str, Any]:
    """Read the singleton portfolio_state JSON document.

    Postgres: SELECT state FROM portfolio_state WHERE id = 1.
    DuckDB / fallback: read data/portfolio_state.json.
    On either path, if no row/file exists, return the default $100k empty
    portfolio (matches the bootstrap behavior in main.py).
    """
    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT state FROM portfolio_state WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        # psycopg2 returns JSONB as already-parsed dict
                        return _normalize_portfolio(row[0])
            finally:
                conn.close()
        except Exception as e:
            print(f"  WARNING: portfolio_state Postgres read failed ({e}), falling back to file")
        # Fallthrough to file read

    return _load_portfolio_state_from_file()


def save_portfolio_state(state: dict[str, Any]) -> None:
    """Write the singleton portfolio_state JSON document.

    In Postgres mode we still write the JSON file too, so a roll-back to
    DB_BACKEND=duckdb stays current. Removing the dual-write is a Phase 3
    cleanup once we trust Postgres in production.
    """
    state = _normalize_portfolio(state)

    # Always write the file so DuckDB fallback stays usable.
    settings.paths.portfolio_state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.paths.portfolio_state_path, "w") as f:
        json.dump(state, f, indent=2)

    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO portfolio_state (id, state, updated_at)
                        VALUES (1, %s::jsonb, now())
                        ON CONFLICT (id) DO UPDATE SET
                            state = EXCLUDED.state,
                            updated_at = now()
                        """,
                        (json.dumps(state),),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"  WARNING: portfolio_state Postgres write failed ({e}); file write succeeded")


def _load_portfolio_state_from_file() -> dict[str, Any]:
    path = settings.paths.portfolio_state_path
    if not path.exists():
        return dict(_DEFAULT_PORTFOLIO)
    with open(path) as f:
        return _normalize_portfolio(json.load(f))


def _normalize_portfolio(state: dict[str, Any]) -> dict[str, Any]:
    """Match the in-memory shape the rest of the app expects.

    Strips internal-only fields and ticker-normalizes positions, since
    several upstream sources (SnapTrade) can return whitespace or
    lowercase tickers depending on the brokerage.
    """
    state = dict(state)  # avoid mutating caller's dict
    state.pop("_comment", None)
    for pos in state.get("positions", []) or []:
        t = pos.get("ticker")
        if isinstance(t, str):
            pos["ticker"] = t.strip().upper()
    return state


# ============================================================================
# Universe
# ============================================================================

def load_universe_df() -> pd.DataFrame:
    """Return the active universe as a DataFrame.

    Columns: ticker, name, sub_sector, market_cap_tier, risk_tier. Matches
    the universe.csv on-disk schema. risk_tier was added by main as a
    classifier for trading-risk profile (standard / moderate_risk /
    high_risk) — callers that don't care about it can just ignore the
    column.
    """
    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT ticker, name, sub_sector, market_cap_tier, risk_tier FROM universe"
                    )
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                df = pd.DataFrame(rows, columns=cols)
                if not df.empty:
                    return df
            finally:
                conn.close()
        except Exception as e:
            print(f"  WARNING: universe Postgres read failed ({e}), falling back to CSV")

    return pd.read_csv(settings.paths.universe_path)


# ============================================================================
# Factor weights (currently dormant — kept for symmetry / future use)
# ============================================================================

def load_factor_weights_state() -> dict[str, float] | None:
    """Read the singleton factor weights document, or None if not set.

    Returns None instead of the settings default so callers can decide
    whether to fall back to settings.strategy.factor_weights.
    """
    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT weights FROM factor_weights_state WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0]:
                        return dict(row[0])
            finally:
                conn.close()
        except Exception:
            pass

    path = settings.paths.factor_weights_path
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def save_factor_weights_state(weights: dict[str, float]) -> None:
    path = settings.paths.factor_weights_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(weights, f, indent=2)

    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO factor_weights_state (id, weights, updated_at)
                        VALUES (1, %s::jsonb, now())
                        ON CONFLICT (id) DO UPDATE SET
                            weights = EXCLUDED.weights,
                            updated_at = now()
                        """,
                        (json.dumps(weights),),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
