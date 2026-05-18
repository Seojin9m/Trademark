"""SnapTrade brokerage integration — per-user.

Every function takes the Supabase user UUID as the first argument and
reads/writes credentials in the ``brokerage_connections`` table. The legacy
single-user JSON-file storage (``backend/data/snaptrade_state.json``) is
gone; users connect their own brokerage during onboarding.

Flow:
1. ``register_user(user_id)`` — one-time SnapTrade-side registration. We
   derive a stable per-user SnapTrade id from the Supabase UUID so that a
   given user always lands on the same SnapTrade account.
2. ``get_connect_url(user_id, broker)`` — returns the SnapTrade Connection
   Portal URL the user opens in a popup to log into their brokerage.
3. ``sync_portfolio(user_id, account_id=None)`` — fetches positions +
   balances → writes per-user ``portfolio_state`` row.

Notes on SnapTrade limits:
  Personal / free SnapTrade API keys allow only ONE registered user per
  Client ID. To support multi-user, the SnapTrade subscription must be
  upgraded so multiple ``register_user`` calls don't collide.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection


def _snaptrade_error_body(exc: BaseException) -> dict:
    """Best-effort parse of SnapTrade SDK error payload."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    return {}


def _get_client():
    from snaptrade_client import SnapTrade

    client_id = settings.api_keys.snaptrade_client_id
    consumer_key = settings.api_keys.snaptrade_consumer_key

    if not client_id or not consumer_key:
        raise ValueError(
            "SnapTrade credentials not configured. "
            "Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY in backend/.env"
        )

    return SnapTrade(consumer_key=consumer_key, client_id=client_id)


def _snaptrade_user_id_for(user_id: str) -> str:
    """Build a stable SnapTrade-side user id from the Supabase UUID.

    SnapTrade ids are opaque strings; we prefix to make them human-recognizable
    in their dashboard.
    """
    return f"trademark-{user_id}"


# ============================================================================
# Connection state — backed by brokerage_connections table
# ============================================================================


def _load_connection(user_id: str, broker: str | None = None) -> Optional[dict]:
    """Return the user's active brokerage connection row (or None)."""
    con = get_connection()
    try:
        if broker:
            row = con.execute(
                """
                SELECT id, user_id, broker, snaptrade_user_id, snaptrade_user_secret,
                       status, selected_account_ids, last_sync_at
                FROM brokerage_connections
                WHERE user_id = CAST($1 AS UUID) AND broker = $2
                LIMIT 1
                """,
                [user_id, broker],
            ).fetchone()
        else:
            row = con.execute(
                """
                SELECT id, user_id, broker, snaptrade_user_id, snaptrade_user_secret,
                       status, selected_account_ids, last_sync_at
                FROM brokerage_connections
                WHERE user_id = CAST($1 AS UUID)
                ORDER BY connected_at DESC
                LIMIT 1
                """,
                [user_id],
            ).fetchone()
    finally:
        con.close()

    if not row:
        return None

    return {
        "id": row[0],
        "user_id": row[1],
        "broker": row[2],
        "snaptrade_user_id": row[3],
        "snaptrade_user_secret": row[4],
        "status": row[5],
        "selected_account_ids": row[6] or [],
        "last_sync_at": row[7],
    }


def _upsert_connection(
    user_id: str,
    broker: str,
    snaptrade_user_id: str,
    snaptrade_user_secret: str,
) -> None:
    """Create or update a brokerage_connections row for this (user, broker)."""
    con = get_connection()
    try:
        con.execute(
            """
            INSERT INTO brokerage_connections
                (user_id, broker, snaptrade_user_id, snaptrade_user_secret, status)
            VALUES (CAST($1 AS UUID), $2, $3, $4, 'active')
            ON CONFLICT (user_id, broker) DO UPDATE
                SET snaptrade_user_secret = EXCLUDED.snaptrade_user_secret,
                    status = 'active'
            """,
            [user_id, broker, snaptrade_user_id, snaptrade_user_secret],
        )
    finally:
        con.close()


def _mark_synced(connection_id: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "UPDATE brokerage_connections SET last_sync_at = now() WHERE id = CAST($1 AS UUID)",
            [str(connection_id)],
        )
    finally:
        con.close()


# ============================================================================
# Public API — every function takes user_id
# ============================================================================


def register_user(user_id: str, broker: str = "WEALTHSIMPLETRADE") -> dict:
    """Register a SnapTrade user for the given Supabase user.

    No-op (returns the existing record) if the user already has a connection
    for this broker.
    """
    existing = _load_connection(user_id, broker)
    if existing:
        return {"status": "already_registered", "snaptrade_user_id": existing["snaptrade_user_id"]}

    snaptrade_uid = _snaptrade_user_id_for(user_id)
    client = _get_client()
    try:
        response = client.authentication.register_snap_trade_user(
            body={"userId": snaptrade_uid}
        )
    except Exception as exc:
        err = _snaptrade_error_body(exc)
        code = str(err.get("code") or "")
        detail = str(err.get("detail") or "")
        if code == "1012" or "Personal keys can only register one user" in detail:
            raise ValueError(
                "SnapTrade rejected registration: your SnapTrade plan allows only one user. "
                "Upgrade the SnapTrade subscription to enable multi-user, or delete the existing "
                "SnapTrade user in their dashboard."
            ) from exc
        raise

    secret = response.body.get("userSecret")
    if not secret:
        raise ValueError(f"Registration failed: {response.body}")

    _upsert_connection(user_id, broker, snaptrade_uid, secret)
    return {"status": "registered", "snaptrade_user_id": snaptrade_uid}


def get_connect_url(user_id: str, broker: str = "WEALTHSIMPLETRADE") -> dict:
    """Return the SnapTrade Connection Portal URL for the given user + broker."""
    conn = _load_connection(user_id, broker)
    if not conn:
        register_user(user_id, broker)
        conn = _load_connection(user_id, broker)
        if not conn:
            raise ValueError("Failed to create brokerage_connections row after registration")

    client = _get_client()
    body: dict = {
        "darkMode": True,
        "customRedirect": "http://localhost:5173/brokerage/callback",
    }
    if broker:
        body["broker"] = broker

    response = client.authentication.login_snap_trade_user(
        query_params={
            "userId": conn["snaptrade_user_id"],
            "userSecret": conn["snaptrade_user_secret"],
        },
        body=body,
    )

    login_url = None
    if hasattr(response, "body"):
        login_url = response.body.get("redirectURI") or response.body.get("loginLink")

    if not login_url:
        raise ValueError(f"Failed to generate login URL: {response}")

    return {"url": login_url, "broker": broker}


def get_connection_status(user_id: str) -> dict:
    """Inspect a user's brokerage connection: which accounts SnapTrade sees, sync status, balances."""
    conn = _load_connection(user_id)
    if not conn:
        return {"connected": False, "status": "not_registered", "accounts": []}

    try:
        client = _get_client()
        accounts = client.account_information.list_user_accounts(
            user_id=conn["snaptrade_user_id"],
            user_secret=conn["snaptrade_user_secret"],
        )

        import json as _json
        account_list = []
        for acc in accounts.body:
            try:
                acc_plain = _json.loads(_json.dumps(dict(acc), default=str))
            except Exception:
                acc_plain = dict(acc)

            sync = acc_plain.get("sync_status") or {}
            holdings_sync = sync.get("holdings") or {}
            synced = bool(holdings_sync.get("initial_sync_completed", False))
            last_sync = str(holdings_sync.get("last_successful_sync") or "")
            meta = acc_plain.get("meta") or {}
            balance = acc_plain.get("balance") or {}
            balance_total = balance.get("total") or {}
            account_list.append({
                "id": str(acc_plain.get("id") or ""),
                "name": str(acc_plain.get("name") or ""),
                "number": str(acc_plain.get("number") or ""),
                "institution": str(acc_plain.get("institution_name") or ""),
                "account_type": str(meta.get("unifiedAccountType") or acc_plain.get("raw_type") or ""),
                "status": str(acc_plain.get("status") or "unknown"),
                "sync_status": "synced" if synced else "pending",
                "last_sync": last_sync[:10] if last_sync else "",
                "balance": float(balance_total.get("amount") or 0),
                "currency": str(balance_total.get("currency") or "CAD"),
            })

        return {
            "connected": len(account_list) > 0,
            "status": "connected" if account_list else "registered_no_accounts",
            "accounts": account_list,
            "user_id": conn["snaptrade_user_id"],
        }
    except Exception as e:
        return {"connected": False, "status": f"error: {e}", "accounts": []}


def sync_portfolio(user_id: str, account_id: str | None = None) -> dict:
    """Fetch positions + balances from the user's brokerage and persist to portfolio_state."""
    conn = _load_connection(user_id)
    if not conn:
        raise ValueError("No SnapTrade connection. Connect your brokerage first.")

    client = _get_client()
    snap_user = conn["snaptrade_user_id"]
    snap_secret = conn["snaptrade_user_secret"]

    if not account_id:
        accounts = client.account_information.list_user_accounts(
            user_id=snap_user, user_secret=snap_secret,
        )
        if not accounts.body:
            raise ValueError("No brokerage accounts found. Connect your brokerage first.")
        best = max(
            accounts.body,
            key=lambda a: float((a.get("balance") or {}).get("total", {}).get("amount", 0) or 0),
        )
        account_id = best.get("id")

    # Balances
    balances_resp = client.account_information.get_user_account_balance(
        user_id=snap_user, user_secret=snap_secret, account_id=account_id,
    )
    cash = 0.0
    currency = "CAD"
    for bal in balances_resp.body:
        cur = bal.get("currency", {})
        code = cur.get("code", "CAD") if isinstance(cur, dict) else "CAD"
        cash_val = bal.get("cash", 0) or 0
        if isinstance(cash_val, dict):
            cash_val = cash_val.get("amount", 0)
        cash += float(cash_val)
        currency = code

    # Positions
    positions_resp = client.account_information.get_user_account_positions(
        user_id=snap_user, user_secret=snap_secret, account_id=account_id,
    )

    # Preserve first_seen_at across syncs (hold-window protection). Pull
    # existing per-user portfolio_state row first.
    backdated_iso = (datetime.now() - timedelta(days=365)).isoformat()
    existing_first_seen: dict[str, str] = {}
    try:
        from src.db.state import load_portfolio_state as _load_portfolio
        _existing = _load_portfolio(user_id=user_id)
        _existing_positions = _existing.get("positions", [])
        _ts_counts: dict[str, int] = {}
        for _p in _existing_positions:
            _fs = _p.get("first_seen_at")
            if _fs:
                _ts_counts[_fs] = _ts_counts.get(_fs, 0) + 1
        _suspect_batch_ts = {ts for ts, n in _ts_counts.items() if n >= 3}

        for _p in _existing_positions:
            _t = _p.get("ticker")
            if not _t:
                continue
            _fs = _p.get("first_seen_at")
            if not _fs:
                existing_first_seen[_t] = backdated_iso
            elif _fs in _suspect_batch_ts:
                existing_first_seen[_t] = backdated_iso
            else:
                existing_first_seen[_t] = _fs
    except Exception:
        pass

    import json as _json
    now_iso = datetime.now().isoformat()
    positions = []
    for pos in positions_resp.body:
        try:
            pos_plain = _json.loads(_json.dumps(dict(pos), default=str))
        except Exception:
            pos_plain = dict(pos)

        symbol_info = pos_plain.get("symbol") or {}
        if isinstance(symbol_info, dict):
            ticker = symbol_info.get("symbol") or symbol_info.get("raw_symbol") or ""
            if isinstance(ticker, dict):
                ticker = ticker.get("symbol") or ticker.get("raw_symbol") or ""
        else:
            ticker = str(symbol_info)
        ticker = str(ticker).split(".")[0] if ticker else ""
        _TICKER_MAP = {"GOOG": "GOOGL"}
        ticker = _TICKER_MAP.get(ticker, ticker)

        units = pos_plain.get("units") or 0
        avg_cost = pos_plain.get("average_purchase_price") or 0
        current_price = pos_plain.get("price") or 0
        if isinstance(units, dict): units = units.get("amount", 0)
        if isinstance(avg_cost, dict): avg_cost = avg_cost.get("amount", 0)
        if isinstance(current_price, dict): current_price = current_price.get("amount", 0)
        units, avg_cost, current_price = float(units), float(avg_cost), float(current_price)

        if units <= 0 or not ticker:
            continue

        first_seen = existing_first_seen.get(ticker, now_iso)
        positions.append({
            "ticker": ticker,
            "shares": int(units) if units == int(units) else units,
            "cost_basis_per_share": round(avg_cost, 2),
            "last_price": round(current_price, 4) if current_price > 0 else None,
            "date_acquired": "synced",
            "first_seen_at": first_seen,
        })

    portfolio = {
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "cash": round(cash, 2),
        "currency": currency,
        "positions": positions,
        "synced_from": "snaptrade",
        "synced_at": datetime.now().isoformat(),
        "account_id": account_id,
    }

    from src.db.state import save_portfolio_state
    save_portfolio_state(portfolio, user_id=user_id)
    _mark_synced(conn["id"])

    return {
        "status": "synced",
        "positions": len(positions),
        "cash": cash,
        "currency": currency,
        "account_id": account_id,
    }


def disconnect(user_id: str, broker: str | None = None) -> dict:
    """Mark all (or one) of the user's brokerage connections as revoked.

    We deliberately don't call SnapTrade's delete_snap_trade_user here because
    other users on the same SnapTrade plan would lose access. Use the SnapTrade
    dashboard to fully terminate the SnapTrade side.
    """
    con = get_connection()
    try:
        if broker:
            con.execute(
                "UPDATE brokerage_connections SET status = 'revoked' WHERE user_id = CAST($1 AS UUID) AND broker = $2",
                [user_id, broker],
            )
        else:
            con.execute(
                "UPDATE brokerage_connections SET status = 'revoked' WHERE user_id = CAST($1 AS UUID)",
                [user_id],
            )
    finally:
        con.close()
    return {"status": "disconnected"}


def get_partner_info() -> dict:
    """Fetch SnapTrade partner info (allowed brokerages). Diagnostic only — not per-user."""
    client = _get_client()
    try:
        response = client.reference_data.get_partner_info()
        body = response.body if hasattr(response, "body") else {}
        allowed = body.get("allowed_brokerages", [])
        return {
            "company": body.get("company", ""),
            "allowed_brokerages": [
                b.get("slug", b) if isinstance(b, dict) else b
                for b in allowed
            ],
            "raw": body,
        }
    except Exception as e:
        return {"error": str(e)}
