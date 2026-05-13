"""SnapTrade brokerage integration: connect Wealthsimple, fetch positions/balances.

Flow:
1. register_user() — one-time setup, creates a SnapTrade user
2. get_connect_url() — returns URL to SnapTrade Connection Portal (user logs into Wealthsimple)
3. sync_portfolio() — fetches positions + balances → updates portfolio_state.json
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings

# Persistent file for SnapTrade user credentials (userId + userSecret)
_SNAPTRADE_STATE_PATH = settings.paths.data_dir / "snaptrade_state.json"


def _snaptrade_error_body(exc: BaseException) -> dict:
    """Best-effort parse of SnapTrade SDK error payload."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    return {}


def _get_client():
    """Get a SnapTrade client instance."""
    from snaptrade_client import SnapTrade

    client_id = settings.api_keys.snaptrade_client_id
    consumer_key = settings.api_keys.snaptrade_consumer_key

    if not client_id or not consumer_key:
        raise ValueError(
            "SnapTrade credentials not configured. "
            "Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY in backend/.env"
        )

    return SnapTrade(consumer_key=consumer_key, client_id=client_id)


def _load_state() -> dict:
    """Load persisted SnapTrade user state (user_id, user_secret, accounts).

    Also accepts camelCase userId / userSecret so a hand-edited JSON matches
    SnapTrade's API field names without triggering a bogus re-register with the
    default ``trademark-user`` id.
    """
    if not _SNAPTRADE_STATE_PATH.exists():
        return {}
    with open(_SNAPTRADE_STATE_PATH) as f:
        state = json.load(f)
    if not state.get("user_id") and state.get("userId"):
        state["user_id"] = state["userId"]
    if not state.get("user_secret") and state.get("userSecret"):
        state["user_secret"] = state["userSecret"]
    return state


def _save_state(state: dict) -> None:
    """Persist SnapTrade user state."""
    with open(_SNAPTRADE_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def get_connection_status() -> dict:
    """Check current connection status."""
    state = _load_state()
    if not state.get("user_id") or not state.get("user_secret"):
        return {"connected": False, "status": "not_registered", "accounts": []}

    try:
        client = _get_client()
        accounts = client.account_information.list_user_accounts(
            user_id=state["user_id"],
            user_secret=state["user_secret"],
        )

        account_list = []
        for acc in accounts.body:
            # Convert to plain dict to avoid SnapTrade SDK object issues
            try:
                import json as _json
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

        state["accounts"] = account_list
        _save_state(state)

        return {
            "connected": len(account_list) > 0,
            "status": "connected" if account_list else "registered_no_accounts",
            "accounts": account_list,
            "user_id": state["user_id"],
        }
    except Exception as e:
        return {"connected": False, "status": f"error: {e}", "accounts": []}


def register_user(user_id: str = "trademark-user") -> dict:
    """Register a SnapTrade user (one-time setup).

    Returns the user state with userId and userSecret.
    """
    state = _load_state()

    # Already registered?
    if state.get("user_id") and state.get("user_secret"):
        return {"status": "already_registered", "user_id": state["user_id"]}

    client = _get_client()
    try:
        response = client.authentication.register_snap_trade_user(
            body={"userId": user_id}
        )
    except Exception as exc:
        err = _snaptrade_error_body(exc)
        code = str(err.get("code") or "")
        detail = str(err.get("detail") or "")
        if code == "1012" or "Personal keys can only register one user" in detail:
            raise ValueError(
                "SnapTrade rejected registration: personal/free API keys allow only one registered "
                "user per Client ID — and that user already exists on SnapTrade. Trademark only skips "
                "registration if backend/data/snaptrade_state.json contains matching user_id and "
                "user_secret. Fix: put the correct pair in that file (snake_case keys), restore it from "
                "a backup, or delete the user in the SnapTrade developer dashboard and connect again "
                "so a fresh user + secret is issued."
            ) from exc
        raise

    user_secret = response.body.get("userSecret")
    if not user_secret:
        raise ValueError(f"Registration failed: {response.body}")

    state = {
        "user_id": user_id,
        "user_secret": user_secret,
        "registered_at": datetime.now().isoformat(),
        "accounts": [],
    }
    _save_state(state)

    return {"status": "registered", "user_id": user_id}


def get_connect_url(broker: str = "WEALTHSIMPLETRADE") -> dict:
    """Generate a URL to the SnapTrade Connection Portal.

    The user opens this URL to log into their brokerage. On success,
    their accounts are automatically imported.

    Args:
        broker: Pre-select a broker slug. Use "WEALTHSIMPLETRADE" for Wealthsimple Trade.
                Pass empty string to show all allowed brokers.
    """
    state = _load_state()
    if not state.get("user_id") or not state.get("user_secret"):
        # Auto-register if not done yet
        register_user()
        state = _load_state()

    client = _get_client()
    body: dict = {
        "darkMode": True,
        "customRedirect": "http://localhost:5173/brokerage",
    }
    if broker:
        body["broker"] = broker

    response = client.authentication.login_snap_trade_user(
        query_params={
            "userId": state["user_id"],
            "userSecret": state["user_secret"],
        },
        body=body,
    )

    login_url = None
    if hasattr(response, 'body'):
        login_url = response.body.get("redirectURI") or response.body.get("loginLink")

    if not login_url:
        raise ValueError(f"Failed to generate login URL: {response}")

    return {"url": login_url, "broker": broker}


def get_reconnect_url(authorization_id: str) -> dict:
    """Generate a reconnect URL for a broken/expired connection."""
    state = _load_state()
    if not state.get("user_id") or not state.get("user_secret"):
        raise ValueError("No SnapTrade user registered")

    client = _get_client()
    response = client.authentication.login_snap_trade_user(
        query_params={
            "userId": state["user_id"],
            "userSecret": state["user_secret"],
        },
        body={
            "reconnect": authorization_id,
            "darkMode": True,
        },
    )

    login_url = None
    if hasattr(response, 'body'):
        login_url = response.body.get("redirectURI") or response.body.get("loginLink")

    return {"url": login_url, "authorization_id": authorization_id}


def sync_portfolio(account_id: str | None = None) -> dict:
    """Fetch positions and balances from brokerage → update portfolio_state.json.

    If account_id is None, uses the first connected account.

    Returns the updated portfolio state.
    """
    state = _load_state()
    if not state.get("user_id") or not state.get("user_secret"):
        raise ValueError("No SnapTrade user registered. Connect your brokerage first.")

    client = _get_client()
    user_id = state["user_id"]
    user_secret = state["user_secret"]

    # Get accounts if no specific one requested — pick highest balance
    if not account_id:
        accounts = client.account_information.list_user_accounts(
            user_id=user_id, user_secret=user_secret
        )
        if not accounts.body:
            raise ValueError("No brokerage accounts found. Connect your brokerage first.")
        best = max(
            accounts.body,
            key=lambda a: float((a.get("balance") or {}).get("total", {}).get("amount", 0) or 0),
        )
        account_id = best.get("id")

    # Fetch balances
    balances_resp = client.account_information.get_user_account_balance(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
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

    # Fetch positions
    positions_resp = client.account_information.get_user_account_positions(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
    )

    # Load existing portfolio to preserve first_seen_at across syncs. New
    # positions appearing in this sync get a fresh first_seen_at; existing
    # positions keep theirs so we don't reset their hold-window protection
    # on every refresh.
    #
    # Migrations applied here:
    # 1. Positions with no first_seen_at field (predates this feature) are
    #    backdated 1 year so they don't all flip to PROTECTED.
    # 2. Positions sharing an identical first_seen_at timestamp with 3+ other
    #    positions are treated as a sync-batch artifact (the early version of
    #    this feature wrote `now` to every position simultaneously). Real
    #    purchase events almost never share an exact-second timestamp across
    #    multiple holdings, so we backdate the whole cluster.
    backdated_iso = (datetime.now() - timedelta(days=365)).isoformat()
    existing_first_seen: dict[str, str] = {}
    try:
        # NB: aliased as _load_portfolio (not _load_state) because this file
        # already has a module-level _load_state() for SnapTrade credentials.
        # A local rebinding to _load_state inside this function would shadow
        # the module-level one and break the earlier credential lookup.
        from src.db.state import load_portfolio_state as _load_portfolio
        _existing = _load_portfolio()
        _existing_positions = _existing.get("positions", [])
        # Count timestamp occurrences to detect batch-write artifacts.
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

    now_iso = datetime.now().isoformat()

    positions = []
    for pos in positions_resp.body:
        # Convert to plain dict first to avoid SnapTrade SDK object issues
        try:
            import json as _json
            pos_plain = _json.loads(_json.dumps(dict(pos), default=str))
        except Exception:
            pos_plain = dict(pos)

        symbol_info = pos_plain.get("symbol") or {}
        # SnapTrade symbol object: {"id": "...", "symbol": "GOOG", "raw_symbol": "GOOG", ...}
        if isinstance(symbol_info, dict):
            ticker = symbol_info.get("symbol") or symbol_info.get("raw_symbol") or ""
            # If symbol is still a dict (double-nested), go deeper
            if isinstance(ticker, dict):
                ticker = ticker.get("symbol") or ticker.get("raw_symbol") or ""
        else:
            ticker = str(symbol_info)
        ticker = str(ticker).split(".")[0] if ticker else ""
        # Map brokerage tickers to universe tickers (e.g., GOOG → GOOGL)
        _TICKER_MAP = {"GOOG": "GOOGL"}
        ticker = _TICKER_MAP.get(ticker, ticker)

        units = pos_plain.get("units") or 0
        avg_cost = pos_plain.get("average_purchase_price") or 0
        current_price = pos_plain.get("price") or 0

        if isinstance(units, dict):
            units = units.get("amount", 0)
        if isinstance(avg_cost, dict):
            avg_cost = avg_cost.get("amount", 0)
        if isinstance(current_price, dict):
            current_price = current_price.get("amount", 0)

        units = float(units)
        avg_cost = float(avg_cost)
        current_price = float(current_price)

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

    # Build portfolio state
    portfolio = {
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "cash": round(cash, 2),
        "currency": currency,
        "positions": positions,
        "synced_from": "snaptrade",
        "synced_at": datetime.now().isoformat(),
        "account_id": account_id,
    }

    # Persist via state helper (writes Postgres + file in postgres mode, file-only in duckdb mode)
    from src.db.state import save_portfolio_state as _save_state
    _save_state(portfolio)

    return {
        "status": "synced",
        "positions": len(positions),
        "cash": cash,
        "currency": currency,
        "account_id": account_id,
    }


def get_partner_info() -> dict:
    """Fetch SnapTrade partner/client info including allowed brokerages.

    Useful for diagnosing why a brokerage connection fails (1066 error means
    the brokerage is not in your allowed_brokerages list).
    """
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


def delete_user() -> dict:
    """Delete the SnapTrade user and clear local state. Use for full reset."""
    state = _load_state()
    if not state.get("user_id") or not state.get("user_secret"):
        return {"status": "no_user"}

    try:
        client = _get_client()
        client.authentication.delete_snap_trade_user(
            query_params={
                "userId": state["user_id"],
            }
        )
    except Exception:
        pass  # User may already be deleted on SnapTrade's side

    # Clear local state
    if _SNAPTRADE_STATE_PATH.exists():
        _SNAPTRADE_STATE_PATH.unlink()

    return {"status": "deleted", "user_id": state.get("user_id")}
