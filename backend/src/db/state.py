"""Backend-agnostic helpers for portfolio / factor-weight state — per-user.

After the multi-user migration the per-user tables (``portfolio_state``,
``factor_weights_state``) are keyed by ``user_id`` (the Supabase UUID).
Every caller must pass ``user_id``. The legacy JSON files
(``data/portfolio_state.json``, ``config/factor_weights.json``) are no
longer written or read — they made sense in single-user mode.

The DuckDB path still works for local dev without Postgres, but the schema
mirror needed for multi-user DuckDB doesn't exist; DuckDB callers will hit
empty results until the migration adds equivalent tables there. For now,
DB_BACKEND should be ``postgres``.
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
# Portfolio state — per user
# ============================================================================

_DEFAULT_PORTFOLIO: dict[str, Any] = {
    "as_of_date": None,
    "cash": 0.0,
    "currency": "CAD",
    "positions": [],
}


def load_portfolio_state(user_id: str) -> dict[str, Any]:
    """Return the user's portfolio_state JSON document, or the empty default."""
    if not user_id:
        raise ValueError("user_id is required")

    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT state FROM portfolio_state WHERE user_id = %s::uuid",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        return _normalize_portfolio(row[0])
            finally:
                conn.close()
        except Exception as e:
            print(f"  WARNING: portfolio_state Postgres read failed ({e})")

    return dict(_DEFAULT_PORTFOLIO)


def save_portfolio_state(state: dict[str, Any], user_id: str) -> None:
    """Upsert the user's portfolio_state row."""
    if not user_id:
        raise ValueError("user_id is required")
    state = _normalize_portfolio(state)

    if _backend() != "postgres":
        # No DuckDB path in multi-user mode — log loudly and bail.
        print("  WARNING: save_portfolio_state requires DB_BACKEND=postgres; skipping")
        return

    from src.db.postgres import get_pg_connection
    conn = get_pg_connection(role="pooled")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_state (user_id, state, updated_at)
                VALUES (%s::uuid, %s::jsonb, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    updated_at = now()
                """,
                (user_id, json.dumps(state)),
            )
        conn.commit()
    finally:
        conn.close()


def _normalize_portfolio(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state.pop("_comment", None)
    for pos in state.get("positions", []) or []:
        t = pos.get("ticker")
        if isinstance(t, str):
            pos["ticker"] = t.strip().upper()
    return state


# ============================================================================
# Universe — global (unchanged)
# ============================================================================

def load_universe_df() -> pd.DataFrame:
    """Return the active universe as a DataFrame."""
    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT ticker, name, sub_sector, sector, market_cap_tier, risk_tier FROM universe"
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
# Factor weights — per user
# ============================================================================

def load_factor_weights_state(user_id: str) -> dict[str, float] | None:
    """Return the user's factor weights, or None if they haven't customized."""
    if not user_id:
        raise ValueError("user_id is required")

    if _backend() == "postgres":
        try:
            from src.db.postgres import get_pg_connection
            conn = get_pg_connection(role="pooled")
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT weights FROM factor_weights_state WHERE user_id = %s::uuid",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        return dict(row[0])
            finally:
                conn.close()
        except Exception:
            pass

    return None


def save_factor_weights_state(weights: dict[str, float], user_id: str) -> None:
    if not user_id:
        raise ValueError("user_id is required")

    if _backend() != "postgres":
        print("  WARNING: save_factor_weights_state requires DB_BACKEND=postgres; skipping")
        return

    from src.db.postgres import get_pg_connection
    conn = get_pg_connection(role="pooled")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO factor_weights_state (user_id, weights, updated_at)
                VALUES (%s::uuid, %s::jsonb, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    weights = EXCLUDED.weights,
                    updated_at = now()
                """,
                (user_id, json.dumps(weights)),
            )
        conn.commit()
    finally:
        conn.close()
