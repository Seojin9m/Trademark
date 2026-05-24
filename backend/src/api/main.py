"""FastAPI backend serving all dashboard data + pipeline streaming."""

import asyncio
import json
import logging
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.auth import AuthUser, get_current_user
from src.db.schema import get_connection, init_db
from src.db.state import load_universe_df
from src.signals.portfolio_engine import (
    load_portfolio_state,
    get_current_prices,
    compute_portfolio_weights,
    compute_portfolio_value,
)
from src.simulation.pnl import compute_pnl
from src.judge.client import get_judge_log


# ─── In-memory caches (avoids repeated yfinance network calls) ────────────────
_PRICE_CACHE: dict[str, tuple[float, float]] = {}  # ticker → (price, monotonic_ts)
_PRICE_TTL = 60.0  # seconds — refresh prices at most once per minute

_usdcad_ts: float = 0.0
_usdcad_val: float = 1.38
_USDCAD_TTL = 300.0  # 5 minutes — FX rate doesn't change fast
# ─────────────────────────────────────────────────────────────────────────────


def get_live_prices(tickers: list[str], portfolio: dict | None = None) -> dict[str, float]:
    """Get current prices with per-ticker 60 s cache.

    Priority: Wealthsimple stored price → in-memory cache → yfinance → DuckDB.
    """
    if not tickers:
        return {}

    now = time.monotonic()
    prices: dict[str, float] = {}

    # 1. Wealthsimple stored prices (always fresh from last sync, skip cache)
    if portfolio:
        for pos in portfolio.get("positions", []):
            lp = pos.get("last_price")
            if lp and lp > 0 and pos["ticker"] in tickers:
                prices[pos["ticker"]] = lp

    # 2. In-memory cache for tickers not covered by Wealthsimple
    cache_hits: list[str] = []
    for t in tickers:
        if t in prices:
            continue
        entry = _PRICE_CACHE.get(t)
        if entry and (now - entry[1]) < _PRICE_TTL:
            prices[t] = entry[0]
            cache_hits.append(t)

    # 3. yfinance for any remaining misses
    missing = [t for t in tickers if t not in prices]
    if missing:
        try:
            import yfinance as yf
            data = yf.download(
                missing, period="2d", progress=False, auto_adjust=True, threads=True
            )
            close = data["Close"] if len(missing) > 1 else data[["Close"]]
            row = close.dropna(how="all").iloc[-1]
            for t in missing:
                if t in row and not pd.isna(row[t]):
                    p = float(row[t])
                    prices[t] = p
                    _PRICE_CACHE[t] = (p, now)  # populate cache
        except Exception:
            pass

    # 4. Final fallback: DuckDB
    still_missing = [t for t in tickers if t not in prices]
    if still_missing:
        db_prices = get_current_prices(still_missing)
        for t, p in db_prices.items():
            prices[t] = p
            _PRICE_CACHE[t] = (p, now)

    return prices

logger = logging.getLogger("trademark")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from contextlib import asynccontextmanager

def _scheduled_fundamentals_check() -> None:
    """Weekly job: re-ingest fundamentals if the cooldown has elapsed.

    Runs inside the FastAPI process via APScheduler. Honors the existing
    `fundamentals_cooldown_days` setting, so this fires harmlessly if data
    is fresh. The same `ingest_fundamentals` path the manual button used
    to call is reused — only the trigger has moved from "user click" to
    "scheduler". On the first deployment after Phase 4, the universe
    rebuild job will live next to this one.
    """
    try:
        from src.ingest.fundamentals import should_ingest_fundamentals, ingest_fundamentals
        should_ingest, reason = should_ingest_fundamentals()
        if should_ingest:
            logger.info(f"[cron] fundamentals refresh: {reason}")
            ingest_fundamentals()
            logger.info("[cron] fundamentals refresh complete")
        else:
            logger.info(f"[cron] fundamentals up-to-date: {reason}")
    except Exception as e:
        logger.error(f"[cron] fundamentals refresh failed: {e}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()

    # Embedded scheduler — fires when the backend is running (always, for
    # this app). Wrapped in try/except because:
    #   1. APScheduler's BackgroundScheduler can interact poorly with uvicorn's
    #      --reload watcher (threads sometimes survive reload and conflict).
    #   2. A scheduler-startup failure should NEVER block the HTTP server.
    # If start fails, we log and continue — the manual CLI fallback
    # `python -m src.ingest.fundamentals` still works.
    scheduler = None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(
            timezone=settings.schedule.timezone,
            daemon=True,  # die with the process; survives reload churn cleanly
        )
        # Weekly Monday 06:00 ET. The cooldown gate inside the job makes
        # ingestion a no-op when data is fresh — weekly heartbeat is the
        # right cadence since SimFin pushes data ~weekly.
        scheduler.add_job(
            _scheduled_fundamentals_check,
            CronTrigger(day_of_week="mon", hour=6, minute=0,
                        timezone=settings.schedule.timezone),
            id="fundamentals_check",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[cron] scheduler started: fundamentals_check (weekly Mon 06:00 ET)")
    except Exception as e:
        logger.warning(f"[cron] scheduler failed to start ({e}); continuing without it")
        scheduler = None

    try:
        yield
    finally:
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
                logger.info("[cron] scheduler stopped")
            except Exception:
                pass

app = FastAPI(title="Trademark API", version="2.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return structured JSON errors."""
    tb = traceback.format_exc()
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "detail": tb.split("\n")[-3:] if tb else [],
            "path": str(request.url.path),
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    # Allow the static app-token header on cross-origin requests so deployed
    # frontends on a different domain can still pass auth.
    allow_headers=["*", "X-App-Token"],
)

# Static app-token guard. Runs before route handlers; rejects any /api/*
# request that doesn't carry the shared secret in X-App-Token (header) or
# app_token (query string fallback for SSE).
from src.auth.app_token import AppTokenMiddleware
app.add_middleware(AppTokenMiddleware)

# Pipeline run state: run_id -> list of events
_pipeline_runs: dict[str, list[dict]] = {}
_pipeline_locks: dict[str, threading.Event] = {}

# Auto-mode and review-mode are per-user, stored in the ``user_settings`` JSONB
# row. The helpers below provide get/set with sensible defaults; the API
# endpoints and pipeline thread read through them so the in-process module
# dicts can disappear. Defaults: auto_mode=false (safe), review_mode=true.

def _get_user_setting(user_id: str, key: str, default):
    con = get_connection()
    try:
        row = con.execute(
            "SELECT settings FROM user_settings WHERE user_id = CAST($1 AS UUID)",
            [user_id],
        ).fetchone()
    finally:
        con.close()
    if not row or row[0] is None:
        return default
    settings_blob = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return settings_blob.get(key, default)


def _set_user_setting(user_id: str, key, value) -> None:
    con = get_connection()
    try:
        row = con.execute(
            "SELECT settings FROM user_settings WHERE user_id = CAST($1 AS UUID)",
            [user_id],
        ).fetchone()
        existing = {}
        if row and row[0] is not None:
            existing = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        existing[key] = value
        con.execute(
            """
            INSERT INTO user_settings (user_id, settings, updated_at)
            VALUES (CAST($1 AS UUID), CAST($2 AS JSONB), now())
            ON CONFLICT (user_id) DO UPDATE SET
                settings = EXCLUDED.settings,
                updated_at = now()
            """,
            [user_id, json.dumps(existing)],
        )
    finally:
        con.close()


def _is_auto_mode(user_id: str) -> bool:
    return bool(_get_user_setting(user_id, "auto_mode", False))


def _is_review_mode(user_id: str) -> bool:
    return bool(_get_user_setting(user_id, "review_mode", True))

# Gate state: run_id -> {gate_name -> {"data": ..., "event": Event, "response": ...}}
_pipeline_gates: dict[str, dict[str, dict]] = {}

# NB: user_notes was previously an in-memory module dict. It now lives in the
# per-user `user_notes` table — see _load_user_notes / _save_user_notes below.
# judge/client.py:_get_user_notes_data still imports the legacy name; once the
# pipeline is per-user refactored, that helper should take a user_id and read
# from the table directly.


# ============================================================
# Brokerage integration endpoints (SnapTrade)
# ============================================================

@app.get("/api/brokerage/status")
def brokerage_status(user: AuthUser = Depends(get_current_user)):
    """Brokerage connection status for the signed-in user."""
    try:
        from src.ingest.brokerage import get_connection_status
        return get_connection_status(user.id)
    except Exception as e:
        logger.error(f"Brokerage status check failed: {e}")
        return {"connected": False, "status": f"error: {e}", "accounts": []}


@app.post("/api/brokerage/connect")
def brokerage_connect(
    broker: str = "WEALTHSIMPLETRADE",
    user: AuthUser = Depends(get_current_user),
):
    """Generate a SnapTrade Connection Portal URL for the signed-in user."""
    try:
        from src.ingest.brokerage import get_connect_url
        return get_connect_url(user.id, broker)
    except ValueError as e:
        logger.warning(f"Brokerage connect rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Brokerage connect failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/brokerage/sync")
def brokerage_sync(
    account_id: str | None = None,
    user: AuthUser = Depends(get_current_user),
):
    """Fetch positions + balances from the user's brokerage and update portfolio_state."""
    try:
        from src.ingest.brokerage import sync_portfolio
        return sync_portfolio(user.id, account_id)
    except Exception as e:
        logger.error(f"Brokerage sync failed: {e}", exc_info=True)
        err = str(e)
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            code = body.get("code") or body.get("status_code")
            detail = body.get("detail", "")
        else:
            code = None
            detail = err
        status = int(getattr(e, "status", 500) or 500)
        if status == 503 or code == "1149":
            raise HTTPException(status_code=503, detail="SnapTrade is under maintenance. Please try again later.")
        raise HTTPException(status_code=status, detail=detail or err)


@app.get("/api/brokerage/partner-info")
def brokerage_partner_info():
    """SnapTrade partner-level info (allowed brokerages). Not per-user — diagnostic only."""
    try:
        from src.ingest.brokerage import get_partner_info
        return get_partner_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/brokerage/disconnect")
def brokerage_disconnect(user: AuthUser = Depends(get_current_user)):
    """Mark the user's brokerage connections as revoked."""
    try:
        from src.ingest.brokerage import disconnect
        return disconnect(user.id)
    except Exception as e:
        logger.error(f"Brokerage disconnect failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Auto mode / reset endpoints
# ============================================================

@app.post("/api/reset")
def reset_trading_data(
    keep_prices: bool = True,
    user: AuthUser = Depends(get_current_user),
):
    """Reset the signed-in user's trading data: proposals, outcomes, executions,
    snapshots, judge log entries, portfolio state.

    Market data (prices, fundamentals, factor_scores, macro) and global signals
    (decision_patterns, news_research) are NOT touched — they're shared across
    users and expensive to re-fetch. ``keep_prices=False`` is a no-op now for
    that reason; if you really want a global wipe, do it by SQL.
    """
    con = get_connection()

    # Per-user tables — DELETE scoped to user_id.
    per_user_tables = [
        "trade_executions",
        "portfolio_snapshots",
        "trade_proposals",
        "decision_outcomes",
        "simulated_positions",
        "judge_log",
        "analyst_reviews",
    ]
    cleared: list[str] = []
    for table in per_user_tables:
        try:
            count = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = CAST($1 AS UUID)",
                [user.id],
            ).fetchone()[0]
            con.execute(
                f"DELETE FROM {table} WHERE user_id = CAST($1 AS UUID)",
                [user.id],
            )
            cleared.append(f"{table} ({count} rows)")
        except Exception:
            pass
    con.close()

    # Reset portfolio state — prefer a fresh brokerage sync if the user is connected.
    portfolio_reset_msg = "portfolio_state (reset to $0 cash, no positions)"
    try:
        from src.ingest.brokerage import sync_portfolio, get_connection_status
        if get_connection_status(user.id).get("connected"):
            sync_portfolio(user.id)
            portfolio_reset_msg = "portfolio_state (re-synced from brokerage)"
        else:
            raise RuntimeError("not connected")
    except Exception:
        from src.db.state import save_portfolio_state as _save_state
        _save_state({
            "as_of_date": datetime.now().strftime("%Y-%m-%d"),
            "cash": 0.00,
            "positions": [],
        }, user_id=user.id)
    cleared.append(portfolio_reset_msg)

    logger.warning(f"RESET for {user.email}: Cleared {len(cleared)} data stores: {', '.join(cleared)}")
    return {
        "status": "reset_complete",
        "cleared": cleared,
        "kept_prices": keep_prices,
    }


@app.get("/api/auto-mode")
def get_auto_mode(user: AuthUser = Depends(get_current_user)):
    """Current auto-mode state for the signed-in user."""
    return {"enabled": _is_auto_mode(user.id)}


@app.post("/api/auto-mode")
def set_auto_mode(enabled: bool, user: AuthUser = Depends(get_current_user)):
    """Toggle the signed-in user's auto-mode. Pipeline auto-approves judge-approved trades."""
    _set_user_setting(user.id, "auto_mode", enabled)
    logger.warning(f"AUTO MODE {'ENABLED' if enabled else 'DISABLED'} for {user.email}")
    return {"enabled": enabled}


# ============================================================
# Review mode + gate endpoints
# ============================================================

@app.get("/api/review-mode")
def get_review_mode(user: AuthUser = Depends(get_current_user)):
    """Current review-mode state for the signed-in user."""
    return {"enabled": _is_review_mode(user.id)}


@app.post("/api/review-mode")
def set_review_mode(enabled: bool, user: AuthUser = Depends(get_current_user)):
    """Toggle the signed-in user's review mode. When ON, pipeline pauses at gates."""
    _set_user_setting(user.id, "review_mode", enabled)
    logger.info(f"REVIEW MODE {'ENABLED' if enabled else 'DISABLED'} for {user.email}")
    return {"enabled": enabled}


@app.get("/api/pipeline/gate")
def get_pipeline_gate(run_id: str):
    """Get the currently active (unresolved) gate for a pipeline run."""
    gates = _pipeline_gates.get(run_id, {})
    for gate_name, gate_info in gates.items():
        if not gate_info["event"].is_set():
            return {
                "gate_name": gate_name,
                "data": gate_info["data"],
                "created_at": gate_info["created_at"],
            }
    return {"gate_name": None}


@app.post("/api/pipeline/gate/respond")
async def respond_to_gate(request: Request):
    """Submit a review response to an active gate, unblocking the pipeline."""
    body = await request.json()
    run_id = body.get("run_id")
    gate_name = body.get("gate_name")
    action = body.get("action", "continue")
    overrides = body.get("overrides", {})

    if not run_id or not gate_name:
        raise HTTPException(400, "run_id and gate_name are required")

    gate_info = _pipeline_gates.get(run_id, {}).get(gate_name)
    if not gate_info:
        raise HTTPException(404, "Gate not found")

    gate_info["response"] = {"action": action, "overrides": overrides}
    gate_info["event"].set()

    return {"status": "ok", "gate_name": gate_name, "action": action}


# ============================================================
# User notes endpoints
# ============================================================

def _load_user_notes(user_id: str) -> dict:
    con = get_connection()
    try:
        row = con.execute(
            "SELECT text, images, updated_at FROM user_notes WHERE user_id = CAST($1 AS UUID)",
            [user_id],
        ).fetchone()
    finally:
        con.close()
    if not row:
        return {"text": "", "images": [], "updated_at": None}
    return {
        "text": row[0] or "",
        "images": row[1] or [],
        "updated_at": row[2].isoformat() if row[2] else None,
    }


def _save_user_notes(user_id: str, text: str, images: list) -> None:
    con = get_connection()
    try:
        con.execute(
            """
            INSERT INTO user_notes (user_id, text, images, updated_at)
            VALUES (CAST($1 AS UUID), $2, CAST($3 AS JSONB), now())
            ON CONFLICT (user_id) DO UPDATE SET
                text = EXCLUDED.text,
                images = EXCLUDED.images,
                updated_at = now()
            """,
            [user_id, text, json.dumps(images)],
        )
    finally:
        con.close()


@app.get("/api/user-notes")
def get_user_notes(user: AuthUser = Depends(get_current_user)):
    """Read the signed-in user's pipeline context notes."""
    return _load_user_notes(user.id)


@app.post("/api/user-notes")
async def set_user_notes(request: Request, user: AuthUser = Depends(get_current_user)):
    """Persist user notes (and optional images) for the next pipeline run."""
    body = await request.json()
    text = (body.get("text") or "").strip()
    images = (body.get("images") or [])[:5]
    _save_user_notes(user.id, text, images)
    return _load_user_notes(user.id)


@app.delete("/api/user-notes")
def clear_user_notes(user: AuthUser = Depends(get_current_user)):
    """Clear the signed-in user's notes."""
    con = get_connection()
    try:
        con.execute("DELETE FROM user_notes WHERE user_id = CAST($1 AS UUID)", [user.id])
    finally:
        con.close()
    return {"text": "", "images": [], "updated_at": None}


# ============================================================
# Portfolio endpoints
# ============================================================

def _get_usdcad_rate() -> float:
    """Fetch live USD/CAD rate, cached for 5 minutes. Returns 1.38 as fallback."""
    global _usdcad_ts, _usdcad_val
    now = time.monotonic()
    if (now - _usdcad_ts) < _USDCAD_TTL:
        return _usdcad_val
    try:
        import yfinance as yf
        hist = yf.Ticker("USDCAD=X").history(period="1d")
        if not hist.empty:
            _usdcad_val = float(hist["Close"].iloc[-1])
            _usdcad_ts = now
            return _usdcad_val
    except Exception:
        pass
    _usdcad_ts = now  # cache the fallback too so we don't retry immediately
    return _usdcad_val


@app.get("/api/portfolio")
def get_portfolio(user: AuthUser = Depends(get_current_user)):
    """Current portfolio state with P&L for the signed-in user.

    Refreshes from the user's connected brokerage on every call so the
    dashboard reflects live positions/prices. SnapTrade errors are non-fatal:
    we'd rather show slightly stale data than break the page when SnapTrade
    is slow or under maintenance.
    """
    try:
        from src.ingest.brokerage import sync_portfolio, get_connection_status
        if get_connection_status(user.id).get("connected"):
            sync_portfolio(user.id)
    except Exception as sync_err:
        logger.debug(f"Brokerage sync skipped on portfolio fetch: {sync_err}")

    try:
        portfolio = load_portfolio_state(user.id)

        if portfolio.get("currency") == "CAD" and portfolio.get("cash", 0) > 0:
            rate = _get_usdcad_rate()
            portfolio = {**portfolio, "cash": round(portfolio["cash"] / rate, 2)}

        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_live_prices(tickers, portfolio)
        pnl = compute_pnl(portfolio, prices)
        weights = compute_portfolio_weights(portfolio, prices)

        return {
            "portfolio": portfolio,
            "pnl": pnl,
            "weights": weights,
            "portfolio_value": pnl["total_portfolio_value"],
        }
    except Exception as e:
        logger.error(f"Portfolio endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scores")
def get_scores(limit: int = 100):
    """Latest factor scores for all tickers."""
    try:
        con = get_connection()
        df = con.execute("""
            SELECT * FROM factor_scores
            WHERE date = (SELECT MAX(date) FROM factor_scores)
            ORDER BY composite_score DESC
            LIMIT ?
        """, [limit]).fetchdf()
        con.close()
        # Convert via JSON to safely handle NaN → null
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        return records
    except Exception as e:
        logger.error(f"Scores endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Rankings page endpoints (Phase 9)
# ============================================================
# The Rankings page is the new homepage — global, read-only, fed by the EOD
# pipeline. Every endpoint here joins factor_scores (per-ticker signal),
# universe (name + sector), and prices (1d change). Per-period scaling is
# done on the API side rather than in SQL because the alpha_pct stored in
# sector_signals is monthly-equivalent.


@app.get("/api/rankings/overall")
def get_rankings_overall(limit: int = 8, factor: str = "composite"):
    """Top N tickers across the universe for the latest scoring date.

    Joins factor_scores ← universe (name, sector) ← prices (latest two
    closes for 1d change %). `factor` lets the UI tab between composite /
    momentum / quality; momentum and quality sort by the underlying factor
    instead of composite, but the same row shape is returned.
    """
    sort_col = {
        "composite": "f.composite_score",
        "momentum": "f.momentum_12m1m",
        "quality": "q.quality_score",
    }.get(factor, "f.composite_score")

    try:
        con = get_connection()
        df = con.execute(
            f"""
            WITH latest AS (SELECT MAX(date) AS d FROM factor_scores),
            latest_prices AS (
                SELECT p.ticker, p.close,
                    LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
                    ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
                FROM prices p
                WHERE p.date >= (SELECT d FROM latest) - INTERVAL '7 days'
            )
            SELECT
                f.ticker,
                u.name,
                u.sector,
                f.composite_score AS composite,
                f.score_decile   AS decile,
                f.momentum_12m1m AS momentum,
                q.quality_score  AS quality,
                lp.close         AS price,
                CASE WHEN lp.prev_close > 0
                     THEN (lp.close - lp.prev_close) / lp.prev_close * 100.0
                     ELSE 0 END  AS change_pct
            FROM factor_scores f
            JOIN universe u ON u.ticker = f.ticker
            LEFT JOIN latest_prices lp ON lp.ticker = f.ticker AND lp.rn = 1
            LEFT JOIN stock_quality_assessment q
                ON q.ticker = f.ticker AND q.date = f.date
            WHERE f.date = (SELECT d FROM latest)
              AND u.sector IS NOT NULL
            ORDER BY {sort_col} DESC NULLS LAST
            LIMIT ?
            """,
            [limit],
        ).fetchdf()
        con.close()
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception as e:
        logger.error(f"Rankings overall failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rankings/sectors")
def get_rankings_sectors(period: str = "monthly", per_sector: int = 4):
    """11-sector view: alpha + action for each sector, plus top-N names inside.

    `period` scales the stored monthly alpha down for the 'daily' toggle on
    the page; we don't recompute, we just present a daily-equivalent number.
    """
    period_factor = 0.22 if period == "daily" else 1.0
    try:
        con = get_connection()

        # Latest date that has sector_signals — fall back to factor_scores' date
        # if the EOD script hasn't run yet today.
        date_row = con.execute("SELECT MAX(date) FROM sector_signals").fetchone()
        if not date_row or date_row[0] is None:
            con.close()
            return {"date": None, "sectors": []}
        as_of = str(date_row[0])

        sectors_df = con.execute(
            """
            SELECT sector, date, alpha_pct, breadth_top, total_names, action
            FROM sector_signals
            WHERE date = CAST(? AS DATE)
            ORDER BY alpha_pct DESC NULLS LAST
            """,
            [as_of],
        ).fetchdf()

        # Per-sector top-N names — single query, then bucket client-side.
        top_df = con.execute(
            """
            WITH ranked AS (
                SELECT
                    u.sector, f.ticker, u.name, f.composite_score AS composite,
                    f.score_decile AS decile,
                    ROW_NUMBER() OVER (
                        PARTITION BY u.sector ORDER BY f.composite_score DESC
                    ) AS rn
                FROM factor_scores f
                JOIN universe u ON u.ticker = f.ticker
                WHERE f.date = CAST(? AS DATE)
                  AND u.sector IS NOT NULL
            )
            SELECT sector, ticker, name, composite, decile
            FROM ranked
            WHERE rn <= ?
            """,
            [as_of, per_sector],
        ).fetchdf()
        con.close()

        # Recompute action + alpha for the requested period.
        sectors_df["alpha_pct"] = (sectors_df["alpha_pct"] * period_factor).round(2)
        sectors_df["action"] = sectors_df["alpha_pct"].apply(
            lambda a: "BUY" if a >= 0 else "SELL"
        )

        # Bucket top names under their sector
        tops: dict[str, list[dict]] = {s: [] for s in sectors_df["sector"]}
        for r in top_df.itertuples():
            tops.setdefault(r.sector, []).append({
                "ticker": r.ticker,
                "name": r.name,
                "composite": float(r.composite) if r.composite is not None else None,
                "decile": int(r.decile) if r.decile is not None else None,
            })

        sectors_payload = []
        for r in sectors_df.itertuples():
            sectors_payload.append({
                "sector": r.sector,
                "alpha_pct": float(r.alpha_pct) if r.alpha_pct is not None else 0.0,
                "breadth_top": int(r.breadth_top) if r.breadth_top is not None else 0,
                "total_names": int(r.total_names) if r.total_names is not None else 0,
                "action": r.action,
                "top": tops.get(r.sector, []),
            })

        return {"date": as_of, "period": period, "sectors": sectors_payload}
    except Exception as e:
        logger.error(f"Rankings sectors failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rankings/market-summary")
def get_rankings_market_summary():
    """Latest stored market summary + a 30-day SPX spark series for the card."""
    try:
        con = get_connection()
        summary_row = con.execute(
            """
            SELECT date, stance, spx_close, spx_change, vix,
                   buy_sectors, sell_sectors, narrative
            FROM market_summary
            ORDER BY date DESC
            LIMIT 1
            """,
        ).fetchone()

        spark_df = con.execute(
            """
            SELECT date, close
            FROM prices
            WHERE ticker = 'SPY'
            ORDER BY date DESC
            LIMIT 30
            """,
        ).fetchdf()
        con.close()

        if not summary_row:
            return {"summary": None, "spx_spark": []}

        return {
            "summary": {
                "date": str(summary_row[0]),
                "stance": summary_row[1],
                "spx_close": summary_row[2],
                "spx_change": summary_row[3],
                "vix": summary_row[4],
                "buy_sectors": summary_row[5],
                "sell_sectors": summary_row[6],
                "narrative": summary_row[7] or "",
            },
            "spx_spark": (
                [float(c) for c in reversed(spark_df["close"].tolist())]
                if not spark_df.empty else []
            ),
        }
    except Exception as e:
        logger.error(f"Rankings market summary failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/proposals")
def get_proposals(
    status: str | None = None,
    limit: int = 50,
    user: AuthUser = Depends(get_current_user),
):
    """Trade proposals for the signed-in user, optionally filtered by status."""
    con = get_connection()
    if status:
        df = con.execute("""
            SELECT * FROM trade_proposals
            WHERE user_id = CAST(? AS UUID) AND status = ?
            ORDER BY created_at DESC LIMIT ?
        """, [user.id, status, limit]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM trade_proposals
            WHERE user_id = CAST(? AS UUID)
            ORDER BY created_at DESC LIMIT ?
        """, [user.id, limit]).fetchdf()
    con.close()
    return df.to_dict(orient="records")


@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: str,
    notes: str = "",
    user: AuthUser = Depends(get_current_user),
):
    """Human approves a proposal for self-learning tracking. Scoped to the
    signed-in user so one user can't approve another user's proposal.
    """
    con = get_connection()
    row = con.execute(
        "SELECT proposal_id FROM trade_proposals WHERE proposal_id = ? AND user_id = CAST(? AS UUID)",
        [proposal_id, user.id],
    ).fetchone()
    if not row:
        con.close()
        return {"status": "not_found", "proposal_id": proposal_id}

    con.execute("""
        UPDATE trade_proposals
        SET status = 'APPROVED', human_decision = 'APPROVED', human_notes = ?
        WHERE proposal_id = ? AND user_id = CAST(? AS UUID)
    """, [notes or "Human approved", proposal_id, user.id])
    con.execute("""
        UPDATE decision_outcomes
        SET proposal_status = 'APPROVED'
        WHERE proposal_id = ? AND user_id = CAST(? AS UUID)
    """, [proposal_id, user.id])
    con.close()

    return {"status": "approved", "proposal_id": proposal_id}


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: str,
    notes: str = "",
    user: AuthUser = Depends(get_current_user),
):
    """Human rejects a proposal — scoped to the signed-in user."""
    con = get_connection()
    con.execute("""
        UPDATE trade_proposals
        SET status = 'REJECTED', human_decision = 'REJECTED', human_notes = ?
        WHERE proposal_id = ? AND user_id = CAST(? AS UUID)
    """, [notes, proposal_id, user.id])
    con.execute("""
        UPDATE decision_outcomes
        SET proposal_status = 'REJECTED'
        WHERE proposal_id = ? AND user_id = CAST(? AS UUID)
    """, [proposal_id, user.id])
    con.close()
    return {"status": "rejected", "proposal_id": proposal_id}


@app.delete("/api/proposals/run/{run_id}")
def delete_run_proposals(run_id: str, user: AuthUser = Depends(get_current_user)):
    """Permanently delete all proposals for a pipeline run owned by the user."""
    con = get_connection()
    proposal_ids = [r[0] for r in con.execute(
        "SELECT proposal_id FROM trade_proposals WHERE run_id = ? AND user_id = CAST(? AS UUID)",
        [run_id, user.id],
    ).fetchall()]
    if not proposal_ids:
        con.close()
        raise HTTPException(status_code=404, detail="No proposals found for this run")
    # decision_outcomes is per-user too — the proposal_id filter is enough to
    # be unique, but we double-scope by user_id to defend against any future
    # collision (and to make the intent obvious in the query).
    con.execute(
        "DELETE FROM decision_outcomes WHERE proposal_id = ANY($1) AND user_id = CAST($2 AS UUID)",
        [proposal_ids, user.id],
    )
    con.execute(
        "DELETE FROM trade_proposals WHERE run_id = ? AND user_id = CAST(? AS UUID)",
        [run_id, user.id],
    )
    con.close()
    return {"status": "deleted", "run_id": run_id, "deleted_count": len(proposal_ids)}


@app.get("/api/judge-log")
def get_judge_log_endpoint(limit: int = 50, user: AuthUser = Depends(get_current_user)):
    """Recent LLM judge decisions for the signed-in user."""
    return get_judge_log(limit, user_id=user.id)


@app.get("/api/judge/portfolio-review")
def get_portfolio_review(user: AuthUser = Depends(get_current_user)):
    """Get the latest portfolio review from the user's judge log."""
    logs = get_judge_log(20, user_id=user.id)
    for log in logs:
        if log.get("action") == "REVIEW" and log.get("ticker") == "PORTFOLIO":
            try:
                import json
                return json.loads(log.get("output_payload", "{}"))
            except Exception:
                return log
    return {"message": "No portfolio review yet. Run the pipeline."}


@app.get("/api/executions")
def get_executions(limit: int = 100, user: AuthUser = Depends(get_current_user)):
    """Trade execution history for the signed-in user."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT * FROM trade_executions
            WHERE user_id = CAST($1 AS UUID)
            ORDER BY executed_at DESC
            LIMIT $2
        """, [user.id, limit]).fetchdf()
        con.close()
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception:
        con.close()
        return []


@app.get("/api/portfolio/history")
def get_portfolio_history(days: int = 90, user: AuthUser = Depends(get_current_user)):
    """Per-user portfolio value time series from portfolio_snapshots."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT snapshot_date, total_value, cash, positions_value,
                   n_positions, unrealized_pnl, total_return_pct,
                   benchmark_value, positions_detail
            FROM portfolio_snapshots
            WHERE snapshot_source = 'pipeline'
              AND user_id = CAST($1 AS UUID)
            ORDER BY snapshot_date DESC
            LIMIT $2
        """, [user.id, days]).fetchdf()
        con.close()
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception:
        con.close()
        return []


@app.get("/api/portfolio/holding-times")
def get_holding_times(user: AuthUser = Depends(get_current_user)):
    """Per-position holding time data for the signed-in user: buy date, days held, status."""
    try:
        portfolio = load_portfolio_state(user.id)
        pos_tickers = [p["ticker"] for p in portfolio["positions"]]
        if not pos_tickers:
            return []

        con = get_connection()

        # Get earliest active buy for each current position (scoped to the user
        # so two users holding the same ticker don't see each other's history).
        executions = con.execute("""
            WITH ranked AS (
                SELECT
                    ticker,
                    action,
                    executed_at,
                    shares,
                    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY executed_at DESC) as rn
                FROM trade_executions
                WHERE ticker = ANY($1)
                  AND action IN ('BUY', 'ADD')
                  AND success = TRUE
                  AND user_id = CAST($2 AS UUID)
            )
            SELECT ticker, executed_at, shares
            FROM ranked
            WHERE rn = 1
        """, [pos_tickers, user.id]).fetchdf()

        # Get quality from stock_quality_assessment and decile from factor_scores
        quality_df = con.execute("""
            SELECT ticker, quality_score, is_good_stock
            FROM (
                SELECT ticker, quality_score, is_good_stock,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM stock_quality_assessment
                WHERE ticker = ANY($1)
            ) sub WHERE rn = 1
        """, [pos_tickers]).fetchdf()

        decile_df = con.execute("""
            SELECT ticker, score_decile
            FROM (
                SELECT ticker, score_decile,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM factor_scores
                WHERE ticker = ANY($1)
            ) sub WHERE rn = 1
        """, [pos_tickers]).fetchdf()
        con.close()

        min_hold = settings.strategy.min_holding_days
        now = datetime.now()
        quality_map = {}
        if not quality_df.empty:
            for _, row in quality_df.iterrows():
                quality_map[row["ticker"]] = {
                    "quality_score": float(row["quality_score"]) if pd.notna(row["quality_score"]) else 0,
                    "is_good_stock": bool(row["is_good_stock"]) if pd.notna(row["is_good_stock"]) else False,
                }
        if not decile_df.empty:
            for _, row in decile_df.iterrows():
                entry = quality_map.setdefault(row["ticker"], {"quality_score": 0, "is_good_stock": False})
                entry["score_decile"] = int(row["score_decile"]) if pd.notna(row["score_decile"]) else 5

        results = []
        exec_map = {}
        if not executions.empty:
            for _, row in executions.iterrows():
                exec_map[row["ticker"]] = row["executed_at"]

        # Hold-status thresholds based on |P&L %|. Rationale: a freshly bought
        # position sits at ~0% P&L because price hasn't diverged from cost
        # yet; established positions almost always have moved meaningfully.
        # Using P&L magnitude as the freshness signal sidesteps the need for
        # accurate buy-date tracking on brokerage-synced positions.
        PROTECTED_PNL_THRESHOLD = 0.015  # < 1.5% absolute → PROTECTED
        TRADEABLE_PNL_THRESHOLD = 0.05   # ≥ 5% absolute → TRADEABLE

        for pos in portfolio["positions"]:
            ticker = pos["ticker"]
            last_buy = exec_map.get(ticker)
            q = quality_map.get(ticker, {})

            # buy_date / days_held are kept for tooltip context only; they no
            # longer drive hold_status.
            if last_buy is not None:
                last_buy_dt = datetime.fromisoformat(last_buy) if isinstance(last_buy, str) else last_buy
                days_held = (now - last_buy_dt).days
                buy_date = last_buy_dt.strftime("%Y-%m-%d")
            else:
                first_seen_str = pos.get("first_seen_at")
                if first_seen_str:
                    try:
                        first_seen_dt = datetime.fromisoformat(first_seen_str)
                        days_held = (now - first_seen_dt).days
                        buy_date = first_seen_dt.strftime("%Y-%m-%d")
                    except Exception:
                        days_held = None
                        buy_date = None
                else:
                    days_held = None
                    buy_date = None

            decile = q.get("score_decile", 5)
            is_good = q.get("is_good_stock", False)
            if is_good and decile >= 8:
                recommended_days = min_hold + 20
            elif is_good:
                recommended_days = min_hold + 10
            else:
                recommended_days = min_hold

            # Compute |P&L %| from cost basis vs last price.
            cost_per_share = float(pos.get("cost_basis_per_share") or 0)
            last_price = float(pos.get("last_price") or 0)
            if cost_per_share > 0 and last_price > 0:
                pnl_pct = (last_price - cost_per_share) / cost_per_share
            else:
                pnl_pct = 0.0
            abs_pnl = abs(pnl_pct)

            if abs_pnl < PROTECTED_PNL_THRESHOLD:
                hold_status = "protected"
            elif abs_pnl < TRADEABLE_PNL_THRESHOLD:
                hold_status = "maturing"
            else:
                hold_status = "tradeable"

            # 0..1 progress toward TRADEABLE — the frontend uses this to size
            # the hold-status bar without needing to know thresholds.
            hold_progress = min(abs_pnl / TRADEABLE_PNL_THRESHOLD, 1.0)

            results.append({
                "ticker": ticker,
                "buy_date": buy_date,
                "days_held": days_held,
                "min_hold_days": min_hold,
                "recommended_hold_days": recommended_days,
                "hold_status": hold_status,
                "hold_pnl_pct": round(pnl_pct, 4),
                "hold_progress": round(hold_progress, 4),
                "hold_tradeable_threshold_pct": TRADEABLE_PNL_THRESHOLD,
                "is_good_stock": is_good,
                "score_decile": decile,
            })

        return results
    except Exception as e:
        logger.error(f"Holding times endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Analyst endpoints
# ============================================================

@app.post("/api/analyst/review")
def request_analyst_review(user: AuthUser = Depends(get_current_user)):
    """Run an on-demand portfolio review for the signed-in user."""
    try:
        from src.analyst.review import run_analyst_review
        portfolio = load_portfolio_state(user.id)
        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_live_prices(tickers, portfolio)

        if portfolio.get("currency") == "CAD" and portfolio.get("cash", 0) > 0:
            rate = _get_usdcad_rate()
            portfolio = {**portfolio, "cash": round(portfolio["cash"] / rate, 2)}

        from src.simulation.pnl import compute_pnl
        pnl = compute_pnl(portfolio, prices)

        scores_df = None
        try:
            con = get_connection()
            scores_df = con.execute("""
                WITH latest AS (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                    FROM factor_scores
                )
                SELECT * FROM latest WHERE rn = 1 ORDER BY composite_score DESC
            """).fetchdf()
            con.close()
        except Exception:
            pass

        regime = {}
        try:
            from src.learning.adaptive import AdaptiveStrategyEngine
            engine = AdaptiveStrategyEngine()
            state = engine.load_state()
            if state and state.get("regime"):
                regime = state["regime"]
        except Exception:
            pass

        return run_analyst_review(portfolio, pnl, user_id=user.id, scores_df=scores_df, regime=regime)
    except Exception as e:
        logger.error(f"Analyst review failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analyst/review")
def get_analyst_review(user: AuthUser = Depends(get_current_user)):
    """Most recent analyst review for the signed-in user."""
    try:
        from src.analyst.review import load_review
        review = load_review(user.id)
        return {"review": review or None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyst/apply")
def apply_analyst_review(apply: bool = True, user: AuthUser = Depends(get_current_user)):
    """Mark the user's latest analyst review as applied (or unapplied) for the next pipeline run."""
    try:
        from src.analyst.review import set_apply_to_pipeline
        review = set_apply_to_pipeline(apply, user_id=user.id)
        return {"apply_to_pipeline": review["apply_to_pipeline"], "review_id": review["review_id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exchange-rate")
def get_exchange_rate(from_currency: str = "USD", to_currency: str = "CAD"):
    """Get current exchange rate using yfinance."""
    try:
        import yfinance as yf
        pair = f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="1d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            return {"from": from_currency, "to": to_currency, "rate": round(rate, 4)}
        return {"from": from_currency, "to": to_currency, "rate": 1.38}  # fallback
    except Exception:
        return {"from": from_currency, "to": to_currency, "rate": 1.38}


@app.get("/api/risk")
def get_risk_metrics(user: AuthUser = Depends(get_current_user)):
    """Current risk metrics for the signed-in user: drawdown, concentration, sector weights."""
    try:
        portfolio = load_portfolio_state(user.id)
        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_current_prices(tickers)
        weights = compute_portfolio_weights(portfolio, prices)
        pnl = compute_pnl(portfolio, prices)

        universe = load_universe_df()

        sector_weights = {}
        for ticker, weight in weights.items():
            sector = universe.loc[universe["ticker"] == ticker, "sub_sector"]
            if not sector.empty:
                s = sector.iloc[0]
                sector_weights[s] = sector_weights.get(s, 0) + weight

        return {
            "portfolio_value": pnl["total_portfolio_value"],
            "total_return_pct": pnl["total_return_pct"],
            "unrealized_pnl": pnl["total_unrealized_pnl"],
            "cash_pct": pnl["cash"] / pnl["total_portfolio_value"] if pnl["total_portfolio_value"] > 0 else 0,
            "n_positions": len(portfolio["positions"]),
            "sector_weights": sector_weights,
            "drawdown_alert_level": settings.strategy.max_portfolio_drawdown_alert,
            "drawdown_halt_level": settings.strategy.max_portfolio_drawdown_halt,
        }
    except Exception as e:
        logger.error(f"Risk endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/universe")
def get_universe():
    """Universe with sub-sector tags."""
    df = load_universe_df()
    return df.to_dict(orient="records")


@app.get("/api/research")
def get_research(ticker: str | None = None, limit: int = 20):
    """Recent news research, optionally filtered by ticker."""
    try:
        con = get_connection()
        if ticker:
            df = con.execute("""
                SELECT * FROM news_research
                WHERE ticker = ?
                ORDER BY research_date DESC LIMIT ?
            """, [ticker, limit]).fetchdf()
        else:
            df = con.execute("""
                SELECT * FROM news_research
                WHERE research_date = (SELECT MAX(research_date) FROM news_research)
                ORDER BY confidence DESC LIMIT ?
            """, [limit]).fetchdf()
        con.close()
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        return records
    except Exception as e:
        logger.error(f"Research endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Learning endpoints (Phase 7)
# ============================================================

# Learning endpoints. The first two (outcomes / summary) are per-user because
# they aggregate decision_outcomes, which is per-user after the multi-user
# migration. The remaining six (patterns / alerts / adaptive / signal-quality /
# factor-ic-history / factor-decay) read globally-aggregated tables — they
# still require auth so we can know who's calling, but the response is the
# same for everyone. Per-user aggregation of these is a future iteration.


@app.get("/api/learning/outcomes")
def get_learning_outcomes(limit: int = 100, user: AuthUser = Depends(get_current_user)):
    """Decision outcomes with measured returns for the signed-in user."""
    try:
        from src.learning.outcome_tracker import get_outcomes
        return get_outcomes(user.id, limit)
    except Exception as e:
        logger.error(f"Learning outcomes endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/summary")
def get_learning_summary(user: AuthUser = Depends(get_current_user)):
    """High-level outcome summary for the signed-in user."""
    try:
        from src.learning.outcome_tracker import get_outcome_summary
        return get_outcome_summary(user.id)
    except Exception as e:
        logger.error(f"Learning summary endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/patterns")
def get_learning_patterns(_: AuthUser = Depends(get_current_user)):
    """Detected decision patterns (globally aggregated for now)."""
    try:
        from src.learning.pattern_detector import get_patterns
        return get_patterns()
    except Exception as e:
        logger.error(f"Learning patterns endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/alerts")
def get_learning_alerts(_: AuthUser = Depends(get_current_user)):
    """Alerting patterns (low win rate with sufficient sample size)."""
    try:
        from src.learning.pattern_detector import get_alerts
        return get_alerts()
    except Exception as e:
        logger.error(f"Learning alerts endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/adaptive")
def get_adaptive_state_endpoint(_: AuthUser = Depends(get_current_user)):
    """Current adaptive strategy state (global): regime, IC analysis, constraints."""
    try:
        from src.learning.adaptive import get_adaptive_state
        state = get_adaptive_state()
        return state or {"message": "No adaptive state computed yet. Run the pipeline."}
    except Exception as e:
        logger.error(f"Adaptive state endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/signal-quality")
def get_signal_quality_dashboard(_: AuthUser = Depends(get_current_user)):
    """Full signal quality dashboard (global): rolling IC, hit rates, decay alerts."""
    try:
        from src.learning.signal_quality import compute_quality_dashboard
        return compute_quality_dashboard()
    except Exception as e:
        logger.error(f"Signal quality dashboard failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/factor-ic-history")
def get_factor_ic_history(lookback_days: int = 180, _: AuthUser = Depends(get_current_user)):
    """Rolling IC time series for each factor (global)."""
    try:
        from src.learning.signal_quality import compute_rolling_factor_ic
        return compute_rolling_factor_ic(lookback_days=lookback_days)
    except Exception as e:
        logger.error(f"Factor IC history failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/factor-decay")
def get_factor_decay_alerts(_: AuthUser = Depends(get_current_user)):
    """Factors losing predictive power (global)."""
    try:
        from src.learning.signal_quality import detect_factor_decay
        return detect_factor_decay()
    except Exception as e:
        logger.error(f"Factor decay detection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Stock metrics & fundamentals endpoints
# ============================================================

@app.get("/api/stock-metrics")
def get_stock_metrics():
    """Return editable stock metrics grid: ticker rows × metric columns."""
    try:
        con = get_connection()
        # Get latest metrics with user overrides
        df = con.execute("""
            SELECT ticker, metric_name,
                   raw_value, user_value,
                   COALESCE(user_value, raw_value) as effective_value,
                   source, as_of_date, updated_at
            FROM stock_metrics
            WHERE as_of_date = (SELECT MAX(as_of_date) FROM stock_metrics)
            ORDER BY ticker, metric_name
        """).fetchdf()
        con.close()

        if df.empty:
            return {"as_of_date": None, "tickers": [], "metrics": []}

        as_of_date = str(df["as_of_date"].iloc[0])
        metrics = sorted(df["metric_name"].unique().tolist())
        tickers = sorted(df["ticker"].unique().tolist())

        # Pivot into grid format: {ticker: {metric: {raw, user, effective}}}
        grid = {}
        for _, row in df.iterrows():
            t = row["ticker"]
            if t not in grid:
                grid[t] = {}
            grid[t][row["metric_name"]] = {
                "raw_value": row["raw_value"],
                "user_value": row["user_value"] if pd.notna(row["user_value"]) else None,
                "effective_value": row["effective_value"],
            }

        return {
            "as_of_date": as_of_date,
            "tickers": tickers,
            "metrics": metrics,
            "grid": grid,
        }
    except Exception as e:
        logger.error(f"Stock metrics endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/stock-metrics/{ticker}/{metric_name}")
async def update_stock_metric(ticker: str, metric_name: str, request: Request):
    """User corrects a metric value. Sets user_value override."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_value = body.get("user_value")
    if user_value is None:
        raise HTTPException(status_code=400, detail="user_value required")

    try:
        from datetime import datetime
        now = datetime.now().isoformat()
        con = get_connection()
        row = con.execute("SELECT MAX(as_of_date) FROM stock_metrics").fetchone()
        if not row or not row[0]:
            con.close()
            raise HTTPException(status_code=404, detail="No metrics data found")
        as_of_date = row[0]

        existing = con.execute("""
            SELECT 1 FROM stock_metrics
            WHERE ticker = $1 AND metric_name = $2 AND as_of_date = $3
        """, [ticker, metric_name, str(as_of_date)]).fetchone()

        if existing:
            con.execute("""
                UPDATE stock_metrics
                SET user_value = $1, updated_at = $5
                WHERE ticker = $2 AND metric_name = $3 AND as_of_date = $4
            """, [float(user_value), ticker, metric_name, str(as_of_date), now])
        else:
            con.execute("""
                INSERT INTO stock_metrics (ticker, metric_name, raw_value, user_value, source, as_of_date, updated_at)
                VALUES ($1, $2, NULL, $3, 'manual', $4, $5)
            """, [ticker, metric_name, float(user_value), str(as_of_date), now])

        con.close()
        return {"status": "updated", "ticker": ticker, "metric": metric_name, "user_value": user_value}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stock metric update failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/stock-metrics/{ticker}/{metric_name}")
def clear_stock_metric_override(ticker: str, metric_name: str):
    """Remove user override, reverting to raw computed value."""
    try:
        con = get_connection()
        con.execute("""
            UPDATE stock_metrics SET user_value = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE ticker = $1 AND metric_name = $2
        """, [ticker, metric_name])
        con.close()
        return {"status": "cleared", "ticker": ticker, "metric": metric_name}
    except Exception as e:
        logger.error(f"Stock metric clear failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/stock-metrics")
def clear_all_stock_metric_overrides():
    """Remove all user overrides, reverting every metric to raw computed values."""
    try:
        con = get_connection()
        result = con.execute("""
            SELECT COUNT(*) FROM stock_metrics WHERE user_value IS NOT NULL
        """).fetchone()
        count = result[0] if result else 0
        con.execute("""
            UPDATE stock_metrics SET user_value = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE user_value IS NOT NULL
        """)
        con.close()
        return {"status": "cleared", "overrides_removed": count}
    except Exception as e:
        logger.error(f"Clear all overrides failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fundamentals/status")
def get_fundamentals_status():
    """Check when fundamentals were last ingested and if refresh is needed."""
    try:
        from src.ingest.fundamentals import should_ingest_fundamentals
        should_ingest, reason = should_ingest_fundamentals()

        con = get_connection()
        row = con.execute("""
            SELECT last_ingested_at, record_count, notes
            FROM ingestion_log WHERE data_type = 'fundamentals'
        """).fetchone()
        con.close()

        return {
            "should_ingest": should_ingest,
            "reason": reason,
            "last_ingested_at": str(row[0]) if row else None,
            "record_count": row[1] if row else 0,
            "notes": row[2] if row else None,
        }
    except Exception as e:
        logger.error(f"Fundamentals status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fundamentals/ingest")
def trigger_fundamentals_ingest():
    """Manually trigger quarterly fundamentals refresh."""
    try:
        from src.ingest.fundamentals import ingest_fundamentals
        ingest_fundamentals()
        return {"status": "completed", "message": "Fundamentals ingestion finished"}
    except Exception as e:
        logger.error(f"Fundamentals ingest failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fundamentals/quarterly")
def get_quarterly_fundamentals(ticker: str | None = None):
    """Quarterly fundamentals with YoY growth for a ticker or all portfolio tickers."""
    try:
        con = get_connection()
        if ticker:
            df = con.execute("""
                SELECT ticker, fiscal_period_end, report_date,
                       revenue, gross_profit, operating_income, net_income,
                       eps_diluted, shares_outstanding
                FROM fundamentals_pit
                WHERE ticker = $1
                ORDER BY fiscal_period_end ASC
            """, [ticker]).fetchdf()
        else:
            portfolio = load_portfolio_state()
            tickers = [p["ticker"] for p in portfolio["positions"]]
            if not tickers:
                con.close()
                return []
            df = con.execute("""
                SELECT ticker, fiscal_period_end, report_date,
                       revenue, gross_profit, operating_income, net_income,
                       eps_diluted, shares_outstanding
                FROM fundamentals_pit
                WHERE ticker = ANY($1)
                ORDER BY ticker, fiscal_period_end ASC
            """, [tickers]).fetchdf()
        con.close()

        if df.empty:
            return []

        records = []
        for t in df["ticker"].unique():
            tdf = df[df["ticker"] == t].sort_values("fiscal_period_end").reset_index(drop=True)
            for i, row in tdf.iterrows():
                r = {
                    "ticker": row["ticker"],
                    "fiscal_period_end": str(row["fiscal_period_end"]),
                    "report_date": str(row["report_date"]),
                    "revenue": float(row["revenue"]) if pd.notna(row["revenue"]) else None,
                    "gross_profit": float(row["gross_profit"]) if pd.notna(row["gross_profit"]) else None,
                    "operating_income": float(row["operating_income"]) if pd.notna(row["operating_income"]) else None,
                    "net_income": float(row["net_income"]) if pd.notna(row["net_income"]) else None,
                    "eps_diluted": float(row["eps_diluted"]) if pd.notna(row["eps_diluted"]) else None,
                }
                # YoY growth: compare with 4 quarters ago
                if i >= 4:
                    prev = tdf.iloc[i - 4]
                    for field in ("revenue", "net_income", "eps_diluted", "gross_profit", "operating_income"):
                        cur_val = row[field]
                        prev_val = prev[field]
                        if pd.notna(cur_val) and pd.notna(prev_val) and prev_val != 0:
                            r[f"{field}_yoy"] = round((float(cur_val) - float(prev_val)) / abs(float(prev_val)), 4)
                        else:
                            r[f"{field}_yoy"] = None
                else:
                    for field in ("revenue", "net_income", "eps_diluted", "gross_profit", "operating_income"):
                        r[f"{field}_yoy"] = None

                records.append(r)

        return records
    except Exception as e:
        logger.error(f"Quarterly fundamentals endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quality-assessments")
def get_quality_assessments():
    """Get latest quality assessments (good-stock filter results)."""
    try:
        con = get_connection()
        df = con.execute("""
            SELECT * FROM stock_quality_assessment
            WHERE date = (SELECT MAX(date) FROM stock_quality_assessment)
            ORDER BY quality_score DESC
        """).fetchdf()
        con.close()
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception as e:
        logger.error(f"Quality assessments endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Pipeline streaming endpoints
# ============================================================

def _sanitize_for_sse(obj):
    """Recursively convert numpy/pandas types to JSON-safe Python types."""
    import math
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize_for_sse(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_sse(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, np.ndarray):
        return [_sanitize_for_sse(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


def _emit(run_id: str, step: str, status: str, message: str, **extra: object) -> None:
    """Push an event to the pipeline run log."""
    event = _sanitize_for_sse({"step": step, "status": status, "message": message, **extra})
    _pipeline_runs.setdefault(run_id, []).append(event)
    log_fn = logger.error if status == "error" else logger.info
    log_fn(f"[pipeline:{run_id}] [{step}] {status}: {message}")


def _wait_for_gate(run_id: str, gate_name: str, step: str, message: str, data: dict, user_id: str) -> dict | None:
    """Pause pipeline at a gate and wait for the user's review.

    Returns user's response dict (may contain overrides), or None if aborted.
    If the user has review mode disabled, emits the data as a 'data' event and
    returns immediately without blocking.
    """
    safe_data = _sanitize_for_sse(data)

    if not _is_review_mode(user_id):
        _emit(run_id, step, "data", message, gate_data=safe_data, gate_name=gate_name)
        return {}

    gate_event = threading.Event()
    _pipeline_gates.setdefault(run_id, {})[gate_name] = {
        "data": safe_data,
        "event": gate_event,
        "response": None,
        "created_at": datetime.now().isoformat(),
    }

    _emit(run_id, step, "gate", message, gate_data=safe_data, gate_name=gate_name)

    gate_event.wait(timeout=1800)

    gate_info = _pipeline_gates.get(run_id, {}).get(gate_name, {})
    response = gate_info.get("response")

    if response and response.get("action") == "abort":
        _emit(run_id, "complete", "error", f"Pipeline aborted by user at {gate_name}")
        _pipeline_locks[run_id].set()
        return None

    return response or {}


def _run_pipeline_thread(run_id: str, user_id: str, sub_sector_filter: str | None = None, risk_level: int = 3) -> None:
    """Execute the full pipeline for ``user_id`` in a background thread, emitting SSE events."""
    from datetime import datetime
    import pytz

    tz = pytz.timezone(settings.schedule.timezone)
    now = datetime.now(tz)
    _emit(run_id, "ingestion", "running", f"Starting EOD pipeline at {now.strftime('%H:%M:%S ET')}...")

    init_db()

    # Step 1: Data ingestion (skip if today's data already exists)
    try:
        from src.ingest.prices import load_universe, fetch_polygon_eod, store_prices, check_eod_data_exists
        tickers = load_universe()
        benchmarks = [settings.primary_benchmark, settings.secondary_benchmark]
        all_tickers = tickers + [b for b in benchmarks if b not in tickers]

        already_exists, existing_count, latest_date = check_eod_data_exists()
        if already_exists:
            _emit(run_id, "ingestion", "done", f"Skipped — already have {existing_count} tickers for {latest_date}")
        else:
            eod_df = fetch_polygon_eod(all_tickers)
            if not eod_df.empty:
                store_prices(eod_df)
                _emit(run_id, "ingestion", "done", f"Ingested {len(eod_df)} EOD prices")
            else:
                _emit(run_id, "ingestion", "done", "No new EOD prices (market may be closed)")
    except Exception as e:
        _emit(run_id, "ingestion", "done", f"Price ingestion skipped: {e}")

    # Step 1b: Quarterly fundamentals ingestion (only if cooldown expired)
    try:
        from src.ingest.fundamentals import should_ingest_fundamentals, ingest_fundamentals
        should_ingest, reason = should_ingest_fundamentals()
        if should_ingest:
            _emit(run_id, "fundamentals", "running", f"Refreshing quarterly fundamentals: {reason}")
            ingest_fundamentals()
            _emit(run_id, "fundamentals", "done", "Quarterly fundamentals refreshed")
        else:
            _emit(run_id, "fundamentals", "skipped", f"Fundamentals up-to-date: {reason}")
    except Exception as e:
        _emit(run_id, "fundamentals", "done", f"Fundamentals ingestion skipped: {e}")

    # Step 1c was forward_estimates ingestion. Removed when the
    # forward_estimate_revision factor was dropped (Polygon Starter lacks
    # analyst data, yfinance unreliable). Re-introduce here if you ever
    # wire in Polygon Advanced or FMP Premium for analyst estimates.

    # Step 2: Scoring (uses prior run's learned factor weights if available)
    _emit(run_id, "scoring", "running", "Computing factor scores...")
    try:
        from src.signals.ranker import rank_universe, store_scores, get_prior_deciles
        from src.learning.adaptive import get_adaptive_state

        prior_adaptive = get_adaptive_state()
        learned_weights = prior_adaptive.get("recommended_factor_weights") if prior_adaptive else None
        if learned_weights:
            weights_msg = ", ".join(f"{k}: {v:.0%}" for k, v in learned_weights.items())
            _emit(run_id, "scoring", "running", f"Using learned factor weights: {weights_msg}")

        scores = rank_universe(factor_weights=learned_weights)
        if scores.empty:
            _emit(run_id, "scoring", "error", "No scores computed")
            _emit(run_id, "complete", "error", "Pipeline failed at scoring")
            _pipeline_locks[run_id].set()
            return

        store_scores(scores)
        as_of_date = str(scores["date"].iloc[0])
        top5 = scores.head(5)["ticker"].tolist()

        # Gate: Scoring Review
        score_cols = ["ticker", "composite_score", "score_decile", "momentum_12m1m",
                      "eps_growth_yoy", "revenue_growth_yoy", "gross_margin_trend",
                      "relative_valuation", "is_good_stock", "quality_score"]
        available_cols = [c for c in score_cols if c in scores.columns]
        scores_preview = json.loads(scores[available_cols].head(30).to_json(orient="records"))
        gate_resp = _wait_for_gate(run_id, "scoring_review", "scoring",
            f"Scored {len(scores)} tickers as of {as_of_date}. Top 5: {', '.join(top5)}",
            {"scores": scores_preview, "total_count": len(scores), "as_of_date": as_of_date},
            user_id=user_id)
        if gate_resp is None:
            return

        # Apply user overrides: exclude tickers, override deciles
        if gate_resp.get("overrides"):
            excluded = set(gate_resp["overrides"].get("exclude_tickers", []))
            if excluded:
                scores = scores[~scores["ticker"].isin(excluded)]
                _emit(run_id, "scoring", "running", f"Excluded {len(excluded)} tickers: {', '.join(excluded)}")
            for ov in gate_resp["overrides"].get("decile_overrides", []):
                mask = scores["ticker"] == ov["ticker"]
                if mask.any():
                    scores.loc[mask, "score_decile"] = ov["new_decile"]

        # Apply sub_sector filter if running in sector mode
        if sub_sector_filter:
            universe_df = pd.read_csv(settings.paths.universe_path)
            sector_tickers = set(universe_df[universe_df["sub_sector"] == sub_sector_filter]["ticker"].tolist())
            scores = scores[scores["ticker"].isin(sector_tickers)]
            _emit(run_id, "scoring", "running", f"Sector filter: {sub_sector_filter} → {len(scores)} tickers")

        _emit(run_id, "scoring", "done", f"Scored {len(scores)} tickers as of {as_of_date}. Top 5: {', '.join(top5)}")
    except Exception as e:
        _emit(run_id, "scoring", "error", f"Scoring failed: {e}")
        _emit(run_id, "complete", "error", "Pipeline failed at scoring")
        _pipeline_locks[run_id].set()
        return

    # Step 3: Adaptive analysis (regime detection, factor IC, constraint tuning)
    adaptive_params = None
    _emit(run_id, "adaptive", "running", "Running adaptive strategy analysis...")
    try:
        from src.learning.adaptive import run_adaptive_analysis
        adaptive_result = run_adaptive_analysis()
        adaptive_params = adaptive_result.get("adaptive_constraints", {})
        regime = adaptive_result.get("regime", {})
        ic = adaptive_result.get("ic_analysis", {})

        regime_msg = f"{regime.get('vol_regime', '?')} vol ({regime.get('realized_vol', 0):.0%}), {regime.get('momentum_regime', '?')} trend"
        weights_msg = ", ".join(f"{k}: {v:.0%}" for k, v in ic.get("shrunk_weights", {}).items())
        _emit(run_id, "adaptive", "done",
              f"Regime: {regime_msg} | Decile threshold: {adaptive_params.get('min_decile_change', '?')} | "
              f"Size scalar: {adaptive_params.get('position_size_scalar', 1):.0%} | Weights: {weights_msg}",
              gate_data={
                  "regime": regime,
                  "constraints": adaptive_params,
                  "ic_analysis": {k: v for k, v in ic.items() if k != "raw_ics"},
                  "recommended_weights": ic.get("shrunk_weights", {}),
                  "rationale": adaptive_result.get("rationale", []),
              })
    except Exception as e:
        _emit(run_id, "adaptive", "done", f"Adaptive analysis skipped: {e}")

    # Step 3b: Universe auto-refresh (promote high-scoring discoveries, flag weak tickers)
    try:
        from src.discovery.screener import auto_promote_candidates, flag_weak_universe_tickers
        promoted = auto_promote_candidates()
        flagged = flag_weak_universe_tickers()
        parts = []
        if promoted:
            parts.append(f"promoted {len(promoted)}: {', '.join(promoted)}")
        if flagged:
            parts.append(f"flagged {len(flagged)} weak")
        if parts:
            _emit(run_id, "universe_refresh", "done", "Universe refresh: " + " | ".join(parts))
        else:
            _emit(run_id, "universe_refresh", "done", "Universe stable — no promotions or flags")
    except Exception as e:
        _emit(run_id, "universe_refresh", "done", f"Universe refresh skipped: {e}")

    # Step 4: Signal generation
    _emit(run_id, "signals", "running", "Generating signals...")
    try:
        from src.signals.decision_rules import generate_signals, filter_actionable_signals, get_recent_trades

        portfolio = load_portfolio_state(user_id)
        pos_tickers = [pos["ticker"] for pos in portfolio["positions"]]
        all_t = list(set(pos_tickers + scores["ticker"].tolist()))
        prices = get_current_prices(all_t)
        current_weights = compute_portfolio_weights(portfolio, prices)
        portfolio_value = compute_portfolio_value(portfolio, prices)
        prior_deciles = get_prior_deciles(as_of_date)

        pnl = compute_pnl(portfolio, prices)
        drawdown = pnl["total_return_pct"] if pnl["total_return_pct"] < 0 else 0.0

        recent_trades = get_recent_trades()
        signals = generate_signals(scores, current_weights, prior_deciles, drawdown, adaptive_params=adaptive_params, recent_trades=recent_trades, risk_level=risk_level)
        actionable = filter_actionable_signals(signals)

        # Gate: Signal Review
        def _signal_to_dict(s):
            return {k: (v if not isinstance(v, pd.Series) else v.tolist()) for k, v in s.items()}

        signals_data = [_signal_to_dict(s) for s in actionable]
        hold_signals = [_signal_to_dict(s) for s in signals if s["action"] == "HOLD"]
        action_summary = ", ".join(f"{s['action']} {s['ticker']}" for s in actionable[:5])
        gate_msg = f"{len(actionable)} actionable signals: {action_summary}" if actionable else f"{len(signals)} signals, 0 actionable"

        gate_resp = _wait_for_gate(run_id, "signals_review", "signals", gate_msg, {
            "actionable_signals": signals_data,
            "hold_signals": hold_signals[:20],
            "total_signals": len(signals),
        }, user_id=user_id)
        if gate_resp is None:
            return

        # Apply overrides: remove signals or change actions
        if gate_resp.get("overrides"):
            removed = set(gate_resp["overrides"].get("remove_tickers", []))
            if removed:
                actionable = [s for s in actionable if s["ticker"] not in removed]
                _emit(run_id, "signals", "running", f"Removed {len(removed)} signals: {', '.join(removed)}")
            for ao in gate_resp["overrides"].get("action_overrides", []):
                for s in actionable:
                    if s["ticker"] == ao["ticker"]:
                        s["action"] = ao["new_action"]

        if len(actionable) == 0:
            _emit(run_id, "signals", "done", f"{len(signals)} signals, 0 actionable - no trades recommended today")
        else:
            _emit(run_id, "signals", "done", f"{len(actionable)} actionable signals: {action_summary}")
    except Exception as e:
        _emit(run_id, "signals", "error", f"Signal generation failed: {e}")
        _emit(run_id, "complete", "error", "Pipeline failed at signal generation")
        _pipeline_locks[run_id].set()
        return

    # Step 4: Trade proposals
    _emit(run_id, "proposals", "running", "Building trade proposals...")
    try:
        from src.signals.portfolio_engine import build_trade_proposals, store_proposals
        universe = load_universe_df()
        proposals = build_trade_proposals(actionable, portfolio, prices, universe, adaptive_params=adaptive_params, risk_level=risk_level)
        for p in proposals:
            p["run_id"] = run_id
        store_proposals(proposals, user_id)

        passed = [p for p in proposals if p["constraint_check"]["passed"]]
        blocked = [p for p in proposals if not p["constraint_check"]["passed"]]

        if len(proposals) == 0:
            # Store a synthetic "STAY" record so it shows in the trade history
            stay_proposal = {
                "proposal_id": str(uuid.uuid4())[:8],
                "run_id": run_id,
                "created_at": datetime.now().isoformat(),
                "ticker": "PORTFOLIO",
                "action": "STAY",
                "shares": 0,
                "signal_data": json.dumps({"reason": "No actionable signals — all positions held"}),
                "constraint_check": json.dumps({"passed": True, "violations": []}),
                "status": "NO_ACTION",
                "human_decision": None,
                "human_notes": None,
            }
            try:
                con = get_connection()
                con.execute("""
                    INSERT INTO trade_proposals
                    (proposal_id, user_id, run_id, created_at, ticker, action, shares,
                     signal_data, constraint_check, status, human_decision, human_notes, reason)
                    VALUES ($1, CAST($2 AS UUID), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """, [
                    stay_proposal["proposal_id"], user_id, stay_proposal["run_id"],
                    stay_proposal["created_at"], stay_proposal["ticker"],
                    stay_proposal["action"], stay_proposal["shares"],
                    stay_proposal["signal_data"], stay_proposal["constraint_check"],
                    stay_proposal["status"], stay_proposal["human_decision"],
                    stay_proposal["human_notes"],
                    "No actionable signals — all positions held",
                ])
                con.close()
            except Exception:
                pass
            _emit(run_id, "proposals", "done", "No proposals created — holding all positions")
        else:
            # Gate: Proposals Review
            def _proposal_to_dict(p):
                d = {}
                for k, v in p.items():
                    if isinstance(v, (str, int, float, bool, type(None))):
                        d[k] = v
                    elif isinstance(v, dict):
                        d[k] = v
                    elif isinstance(v, list):
                        d[k] = v
                    else:
                        d[k] = str(v)
                return d

            proposals_data = [_proposal_to_dict(p) for p in proposals]
            gate_resp = _wait_for_gate(run_id, "proposals_review", "proposals",
                f"{len(passed)} proposals passed constraints, {len(blocked)} blocked",
                {"proposals": proposals_data, "passed_count": len(passed), "blocked_count": len(blocked)},
                user_id=user_id)
            if gate_resp is None:
                return

            # Apply overrides: remove proposals, edit shares, force through blocked
            if gate_resp.get("overrides"):
                ov = gate_resp["overrides"]
                removed_ids = set(ov.get("remove_proposal_ids", []))
                if removed_ids:
                    proposals = [p for p in proposals if p["proposal_id"] not in removed_ids]
                    _emit(run_id, "proposals", "running", f"Removed {len(removed_ids)} proposals")
                for so in ov.get("shares_overrides", []):
                    for p in proposals:
                        if p["proposal_id"] == so["proposal_id"]:
                            p["shares"] = so["new_shares"]
                for force_id in ov.get("force_through_ids", []):
                    for p in proposals:
                        if p["proposal_id"] == force_id:
                            p["constraint_check"] = {"passed": True, "violations": [], "human_override": True}
                passed = [p for p in proposals if p["constraint_check"]["passed"]]
                blocked = [p for p in proposals if not p["constraint_check"]["passed"]]

            _emit(run_id, "proposals", "done", f"{len(passed)} proposals passed constraints, {len(blocked)} blocked")
    except Exception as e:
        _emit(run_id, "proposals", "error", f"Proposal generation failed: {e}")
        proposals = []
        passed = []

    # Step 5: News research + competitive intelligence
    passed_proposals = passed if 'passed' in dir() else []
    research_map: dict = {}  # ticker -> NewsResearch
    sector_intel_map: dict = {}  # ticker -> sector intelligence

    # Include watchlist tickers in research
    watchlist_tickers = []
    try:
        con = get_connection()
        rows = con.execute("SELECT ticker FROM watchlist").fetchall()
        con.close()
        watchlist_tickers = [r[0] for r in rows]
    except Exception:
        pass

    research_tickers_list = list(set(
        [p["ticker"] for p in passed_proposals]
        + [pos["ticker"] for pos in portfolio["positions"]]
        + watchlist_tickers
    ))[:30]

    if research_tickers_list:
        _emit(run_id, "research", "running", f"Researching news for {len(research_tickers_list)} tickers...")
        try:
            from src.research.news_agent import collect_news_batch, get_cached_news
            from src.research.summarizer import research_tickers as summarize_batch, store_research

            news_data = collect_news_batch(research_tickers_list, max_per_ticker=6)

            # Blend with cached historical articles
            cached_news_map = {}
            for t in research_tickers_list:
                try:
                    cached = get_cached_news(t, days=30)
                    if cached:
                        cached_news_map[t] = cached
                except Exception:
                    pass

            # Build competitive intelligence per sub_sector
            try:
                _emit(run_id, "research", "running", "Building competitive intelligence...")
                from src.research.competitive_intel import get_sector_peers, collect_competitor_news, detect_earnings_spillover, compare_peer_fundamentals, build_sector_intelligence
                universe_df = pd.read_csv(settings.paths.universe_path)
                sector_cache: dict[str, dict] = {}  # sub_sector -> intel (avoid duplicate Claude calls)

                for t in research_tickers_list:
                    match = universe_df[universe_df["ticker"] == t]
                    sub_sector = match.iloc[0]["sub_sector"] if not match.empty else None
                    if not sub_sector:
                        continue
                    if sub_sector in sector_cache:
                        sector_intel_map[t] = sector_cache[sub_sector]
                        continue
                    peers = get_sector_peers(t, sub_sector, limit=4)
                    if not peers:
                        continue
                    peer_tickers = [p["ticker"] for p in peers]
                    peer_news = collect_competitor_news(t, peer_tickers, max_per_peer=2)
                    spillover = detect_earnings_spillover(peer_tickers, days=14)
                    fundamentals = compare_peer_fundamentals(t, peer_tickers)
                    intel = build_sector_intelligence(t, sub_sector, peer_news, spillover, fundamentals)
                    sector_cache[sub_sector] = intel
                    sector_intel_map[t] = intel

                if sector_intel_map:
                    _emit(run_id, "research", "running", f"Competitive intel built for {len(sector_intel_map)} tickers ({len(sector_cache)} sectors)")
            except Exception as e:
                _emit(run_id, "research", "running", f"Competitive intel skipped: {e}")

            research_results = summarize_batch(
                research_tickers_list, news_data,
                sector_intel_map=sector_intel_map,
                cached_news_map=cached_news_map,
            )
            store_research(research_results)

            research_map = {r.ticker: r for r in research_results}
            with_news = sum(1 for r in research_results if r.confidence > 0)

            # Gate: News Research Review
            research_data = []
            for r in research_results:
                research_data.append({
                    "ticker": r.ticker,
                    "headlines": r.headlines if hasattr(r, "headlines") else [],
                    "ai_summary": r.summary if hasattr(r, "summary") else getattr(r, "ai_summary", ""),
                    "sentiment": r.sentiment if hasattr(r, "sentiment") else "",
                    "binary_events": [e.__dict__ if hasattr(e, "__dict__") else e for e in (r.binary_events if hasattr(r, "binary_events") else [])],
                    "risk_factors": r.risk_factors if hasattr(r, "risk_factors") else [],
                    "opportunities": r.opportunities if hasattr(r, "opportunities") else [],
                    "confidence": r.confidence if hasattr(r, "confidence") else 0,
                    "data_sources": r.data_sources if hasattr(r, "data_sources") else [],
                })
            gate_resp = _wait_for_gate(run_id, "research_review", "research",
                f"Researched {len(research_results)} tickers ({with_news} with news)",
                {"research": research_data, "total_tickers": len(research_tickers_list)},
                user_id=user_id)
            if gate_resp is None:
                return

            # Apply overrides: user can add custom context per ticker
            if gate_resp.get("overrides"):
                user_context = gate_resp["overrides"].get("user_context", {})
                for ticker, notes in user_context.items():
                    if ticker in research_map:
                        r = research_map[ticker]
                        existing = r.summary if hasattr(r, "summary") else getattr(r, "ai_summary", "")
                        if hasattr(r, "summary"):
                            r.summary = f"{existing}\n\n[User context]: {notes}"
                        elif hasattr(r, "ai_summary"):
                            r.ai_summary = f"{existing}\n\n[User context]: {notes}"

            _emit(run_id, "research", "done", f"Researched {len(research_results)} tickers ({with_news} with news)")
        except Exception as e:
            _emit(run_id, "research", "done", f"News research skipped: {e}")
    else:
        _emit(run_id, "research", "skipped", "No tickers to research")

    # Step 6: Judge evaluation — ALWAYS runs
    # If there are proposals: evaluate each one (approve/reject)
    # If no proposals: run a full portfolio review (agree/disagree with HOLDs)
    judge_results = []
    portfolio_review = None

    # Check if analyst guidance is active, log it, then auto-clear after this run
    _analyst_guidance_was_active = False
    try:
        from src.analyst.review import get_pipeline_guidance
        guidance = get_pipeline_guidance(user_id)
        if guidance:
            _analyst_guidance_was_active = True
            _emit(run_id, "judge", "running", "Analyst guidance active — injecting into judge prompts...")
    except Exception:
        pass
    # Inject market regime into proposals so the judge can see it
    regime_data = regime if 'regime' in dir() else {}
    if regime_data:
        for p in passed_proposals:
            p["market_regime"] = regime_data

    if len(passed_proposals) > 0:
        _emit(run_id, "judge", "running", f"Evaluating {len(passed_proposals)} proposals with LLM judge...")
        try:
            from src.judge.client import evaluate_all_proposals
            judge_results = evaluate_all_proposals(
                passed_proposals, portfolio_value, pnl, research_map,
                recent_trades=recent_trades,
                sector_intel_map=sector_intel_map,
                risk_level=risk_level,
                user_id=user_id,
            )

            # Persist judge verdicts to DB
            try:
                con = get_connection()
                for proposal, output in judge_results:
                    con.execute(
                        """
                        UPDATE trade_proposals
                        SET judge_response = $1, status = $2
                        WHERE proposal_id = $3
                        """,
                        [
                            output.model_dump_json(),
                            proposal.get("status", "NEEDS_REVIEW"),
                            proposal.get("proposal_id"),
                        ],
                    )
                con.close()
            except Exception as e:
                _emit(run_id, "judge", "running", f"Judge persist warning: {e}")

            # Gate: Judge Review
            judge_review_data = []
            for proposal, output in judge_results:
                judge_review_data.append({
                    "proposal_id": proposal.get("proposal_id"),
                    "ticker": proposal["ticker"],
                    "action": proposal["action"],
                    "shares": proposal.get("shares", 0),
                    "verdict": output.verdict.value,
                    "confidence": output.confidence,
                    "reasons": output.reasons,
                    "risk_flags": output.risk_flags,
                    "violated_rules": getattr(output, "violated_rules", []),
                    "binary_event_warning": getattr(output, "binary_event_warning", None),
                    "follow_up_checks": getattr(output, "follow_up_checks", []),
                    "status": proposal.get("status", "NEEDS_REVIEW"),
                })
            approved_count = sum(1 for d in judge_review_data if d["verdict"] == "approve")
            rejected_count = sum(1 for d in judge_review_data if d["verdict"] == "reject")

            gate_resp = _wait_for_gate(run_id, "judge_review", "judge",
                f"Judge evaluated {len(judge_results)} proposals: {approved_count} approved, {rejected_count} rejected",
                {"judge_results": judge_review_data}, user_id=user_id)
            if gate_resp is None:
                return

            # Apply verdict overrides
            if gate_resp.get("overrides"):
                for vo in gate_resp["overrides"].get("verdict_overrides", []):
                    for proposal, output in judge_results:
                        if proposal.get("proposal_id") == vo["proposal_id"]:
                            new_verdict = vo["new_verdict"]
                            if new_verdict == "approve":
                                proposal["status"] = "JUDGE_APPROVED"
                                proposal["human_decision"] = "OVERRIDE_APPROVED"
                            elif new_verdict == "reject":
                                proposal["status"] = "JUDGE_REJECTED"
                                proposal["human_decision"] = "OVERRIDE_REJECTED"
                            proposal["human_notes"] = vo.get("notes", "")
                            # Also update DB
                            try:
                                con = get_connection()
                                con.execute("""
                                    UPDATE trade_proposals SET status = $1, human_decision = $2, human_notes = $3
                                    WHERE proposal_id = $4
                                """, [proposal["status"], proposal.get("human_decision"), proposal.get("human_notes"), proposal["proposal_id"]])
                                con.close()
                            except Exception:
                                pass

            _emit(run_id, "judge", "done", f"Judge evaluated {len(judge_results)} proposals: {approved_count} approved, {rejected_count} rejected")

            # Re-budget surviving proposals. The initial allocation in
            # build_trade_proposals allocates by composite-score, so rejected
            # high-score buys can starve lower-score survivors. After the judge
            # culls, we redistribute the freed cash so the remaining proposals
            # see realistic sizing and accurate "Budget exhausted" flags.
            try:
                from src.signals.portfolio_engine import reallocate_budget_after_judge
                newly_cleared = reallocate_budget_after_judge(user_id, run_id, portfolio, prices, risk_level=risk_level)
            except Exception as e:
                _emit(run_id, "judge", "done", f"Budget reallocation skipped: {e}")
                newly_cleared = []

            # Re-judge proposals that flipped from passed=False (budget
            # exhausted at initial allocation, judge skipped them) to
            # passed=True after reallocation. Without this they'd display
            # "Judge verdict not available" forever, even though they were
            # only skipped due to a phantom budget claim that no longer exists.
            if newly_cleared:
                try:
                    from src.judge.client import evaluate_proposal
                    from src.judge.schema import Verdict
                    _emit(run_id, "judge", "running",
                          f"Re-judging {len(newly_cleared)} proposals that freed up after reallocation...")
                    # Pull the freshened proposal rows so the judge sees the
                    # post-reallocation share counts and clean constraint check.
                    re_con = get_connection()
                    try:
                        df = re_con.execute(
                            """
                            SELECT proposal_id, ticker, action, shares, signal_data,
                                   constraint_check, status
                            FROM trade_proposals
                            WHERE proposal_id = ANY($1) AND user_id = CAST($2 AS UUID)
                            """,
                            [newly_cleared, user_id],
                        ).fetchdf()
                    finally:
                        re_con.close()

                    re_judged = 0
                    for row in df.itertuples():
                        signal_data = row.signal_data if isinstance(row.signal_data, dict) else {}
                        if isinstance(row.signal_data, str):
                            try:
                                signal_data = json.loads(row.signal_data)
                            except Exception:
                                signal_data = {}
                        constraint_check = row.constraint_check if isinstance(row.constraint_check, dict) else {}
                        if isinstance(row.constraint_check, str):
                            try:
                                constraint_check = json.loads(row.constraint_check)
                            except Exception:
                                constraint_check = {}
                        price = prices.get(row.ticker, 0)
                        estimated_value = int(row.shares) * price if price > 0 else 0
                        proposal_dict = {
                            "proposal_id": row.proposal_id,
                            "ticker": row.ticker,
                            "action": row.action,
                            "shares": int(row.shares),
                            "signal_data": signal_data,
                            "constraint_check": constraint_check,
                            "estimated_value": estimated_value,
                            "current_weight": signal_data.get("current_weight", 0),
                            "target_weight": signal_data.get("target_weight", 0),
                            "prior_decile": signal_data.get("prior_decile", 5),
                        }
                        try:
                            news = research_map.get(row.ticker)
                            intel = sector_intel_map.get(row.ticker)
                            output = evaluate_proposal(
                                proposal_dict, portfolio_value, pnl,
                                news=news, sector_intel=intel,
                                risk_level=risk_level, user_id=user_id,
                            )
                        except Exception as exc:
                            logger.exception(f"Re-judge of {row.ticker} failed: {exc}")
                            continue

                        if output.verdict == Verdict.APPROVE:
                            new_status = "JUDGE_APPROVED"
                        elif output.verdict == Verdict.REJECT:
                            new_status = "JUDGE_REJECTED"
                        else:
                            new_status = "NEEDS_REVIEW"

                        upd_con = get_connection()
                        try:
                            upd_con.execute(
                                """
                                UPDATE trade_proposals
                                SET judge_response = CAST($1 AS JSONB),
                                    status = $2
                                WHERE proposal_id = $3 AND user_id = CAST($4 AS UUID)
                                """,
                                [output.model_dump_json(), new_status, row.proposal_id, user_id],
                            )
                        finally:
                            upd_con.close()
                        re_judged += 1
                    _emit(run_id, "judge", "done",
                          f"Re-judged {re_judged} freshly-cleared proposals")
                except Exception as e:
                    logger.exception(f"Re-judge step failed: {e}")
                    _emit(run_id, "judge", "done", f"Re-judge step skipped: {e}")
        except Exception as e:
            _emit(run_id, "judge", "done", f"Judge evaluation skipped: {e}")
    else:
        _emit(run_id, "judge", "running", "No proposals — running full portfolio review...")
        try:
            from src.judge.client import evaluate_portfolio_review
            portfolio_review = evaluate_portfolio_review(
                portfolio, scores, pnl, portfolio_value,
                research_map=research_map, regime=regime_data or None,
                user_id=user_id,
            )
            verdict = portfolio_review.get("overall_verdict", "?")
            confidence = portfolio_review.get("confidence", 0)
            assessment = portfolio_review.get("market_assessment", "")
            holdings = portfolio_review.get("holdings_review", [])
            missed = portfolio_review.get("missed_opportunities", [])
            risks = portfolio_review.get("risk_flags", [])

            # Build summary message
            actions = [h for h in holdings if h.get("action") != "hold"]
            msg_parts = [f"Judge {verdict}s with model ({confidence:.0%} confidence)"]
            if assessment:
                msg_parts.append(assessment)
            if actions:
                action_str = ", ".join(f"{a['action'].upper()} {a['ticker']}" for a in actions[:3])
                msg_parts.append(f"Suggests: {action_str}")
            if missed:
                miss_str = ", ".join(f"BUY {m['ticker']}" for m in missed[:3])
                msg_parts.append(f"Missed: {miss_str}")
            if risks:
                msg_parts.append(f"Risks: {', '.join(risks[:2])}")

            _emit(run_id, "judge", "done", " | ".join(msg_parts))

            # Update the STAY record with the judge's portfolio review
            try:
                con = get_connection()
                con.execute("""
                    UPDATE trade_proposals
                    SET judge_response = $1
                    WHERE run_id = $2 AND action = 'STAY'
                """, [json.dumps(portfolio_review, default=str), run_id])
                con.close()
            except Exception:
                pass
        except Exception as e:
            _emit(run_id, "judge", "done", f"Portfolio review skipped: {e}")

    # Auto-clear analyst guidance now that it's been consumed by this pipeline run
    if _analyst_guidance_was_active:
        try:
            from src.analyst.review import set_apply_to_pipeline
            set_apply_to_pipeline(False, user_id=user_id)
        except Exception:
            pass

    if portfolio_review and portfolio_review.get("overall_verdict") == "disagree":
        # Judge disagrees with HOLD — create proposals from suggestions
        try:
            from src.simulation.executor import execute_trade, save_portfolio_state
            from src.signals.portfolio_engine import store_proposals

            portfolio = load_portfolio_state(user_id)
            all_tickers = list(set(
                [pos["ticker"] for pos in portfolio["positions"]]
                + [h["ticker"] for h in portfolio_review.get("holdings_review", []) if h.get("action") != "hold"]
                + [m["ticker"] for m in portfolio_review.get("missed_opportunities", [])]
            ))
            exec_prices = get_current_prices(all_tickers)

            judge_proposals = []

            # Process holdings suggestions (sell/trim)
            for h in portfolio_review.get("holdings_review", []):
                if h.get("action") in ("sell", "trim") and h.get("conviction", 0) >= 0.6:
                    ticker = h["ticker"]
                    price = exec_prices.get(ticker, 0)
                    if price <= 0:
                        continue

                    pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
                    if not pos:
                        continue

                    if h["action"] == "sell":
                        shares = pos["shares"]
                    else:  # trim
                        shares = max(1, pos["shares"] // 3)

                    judge_proposals.append({
                        "proposal_id": f"judge-{ticker}-{uuid.uuid4().hex[:6]}",
                        "run_id": run_id,
                        "ticker": ticker,
                        "action": h["action"].upper(),
                        "shares": shares,
                        "status": "APPROVED" if _is_auto_mode(user_id) else "NEEDS_REVIEW",
                        "signal_data": {"source": "judge_review", "reason": h.get("reason", ""), "conviction": h.get("conviction", 0)},
                        "constraint_check": {"passed": True},
                        "reason": f"Judge review: {h.get('reason', '')}",
                        "human_decision": "JUDGE_INITIATED" if _is_auto_mode(user_id) else None,
                        "human_notes": f"Judge portfolio review: {h.get('reason', '')}",
                        "created_at": datetime.now().isoformat(),
                    })

            # Process missed opportunities (buy)
            # Distribute available cash across all buy suggestions proportionally by conviction
            buy_candidates = [
                m for m in portfolio_review.get("missed_opportunities", [])
                if m.get("conviction", 0) >= 0.6
            ]
            # Start with current cash, plus estimated proceeds from any sell/trim proposals
            sell_proceeds = sum(
                p["shares"] * exec_prices.get(p["ticker"], 0)
                for p in judge_proposals if p["action"] in ("SELL", "TRIM")
            )
            remaining_cash = portfolio["cash"] + sell_proceeds

            for m in buy_candidates:
                if remaining_cash < 10:
                    break

                ticker = m["ticker"]
                price = exec_prices.get(ticker, 0)
                if price <= 0:
                    continue

                # Allocate cash: split evenly across remaining candidates, deploy all of it
                candidates_left = len(buy_candidates) - buy_candidates.index(m)
                alloc = remaining_cash / candidates_left
                shares = max(1, int(alloc / price))
                cost = shares * price
                if cost > remaining_cash:
                    shares = int(remaining_cash / price)
                if shares <= 0:
                    continue
                remaining_cash -= shares * price

                judge_proposals.append({
                    "proposal_id": f"judge-{ticker}-{uuid.uuid4().hex[:6]}",
                    "run_id": run_id,
                    "ticker": ticker,
                    "action": "BUY",
                    "shares": shares,
                    "status": "APPROVED" if _is_auto_mode(user_id) else "NEEDS_REVIEW",
                    "signal_data": {"source": "judge_review", "reason": m.get("reason", ""), "conviction": m.get("conviction", 0)},
                    "constraint_check": {"passed": True},
                    "reason": f"Judge review: {m.get('reason', '')}",
                    "human_decision": "JUDGE_INITIATED" if _is_auto_mode(user_id) else None,
                    "human_notes": f"Judge portfolio review: {m.get('reason', '')}",
                    "created_at": datetime.now().isoformat(),
                })

            # Store all proposals — first remove any conflicting pipeline
            # proposals for the same tickers in this run (the judge's view
            # supersedes the pipeline's constraint-failed proposals).
            if judge_proposals:
                judge_tickers = {p["ticker"] for p in judge_proposals}
                try:
                    con = get_connection()
                    for t in judge_tickers:
                        con.execute(
                            "DELETE FROM trade_proposals WHERE run_id = $1 AND ticker = $2 AND user_id = CAST($3 AS UUID)",
                            [run_id, t, user_id],
                        )
                    con.execute(
                        "DELETE FROM trade_proposals WHERE run_id = $1 AND action = 'STAY' AND user_id = CAST($2 AS UUID)",
                        [run_id, user_id],
                    )
                    con.close()
                except Exception:
                    pass
                store_proposals(judge_proposals, user_id)
                proposals_str = ", ".join(f"{p['action']} {p['shares']} {p['ticker']}" for p in judge_proposals)

            # Gate: Execution Review (only when auto-mode is on and there are trades)
            if _is_auto_mode(user_id) and judge_proposals:
                exec_data = [{
                    "proposal_id": p["proposal_id"], "ticker": p["ticker"],
                    "action": p["action"], "shares": p["shares"],
                    "estimated_value": p["shares"] * exec_prices.get(p["ticker"], 0),
                    "price": exec_prices.get(p["ticker"], 0),
                } for p in judge_proposals]

                gate_resp = _wait_for_gate(run_id, "execution_review", "execution",
                    f"Ready to execute {len(judge_proposals)} judge-initiated trades",
                    {"trades": exec_data, "auto_mode": True}, user_id=user_id)
                if gate_resp is None:
                    return

                # Apply overrides: remove trades from execution
                if gate_resp.get("overrides"):
                    removed_ids = set(gate_resp["overrides"].get("remove_proposal_ids", []))
                    if removed_ids:
                        judge_proposals = [p for p in judge_proposals if p["proposal_id"] not in removed_ids]

                _emit(run_id, "execution", "running", "AUTO MODE: Executing judge-initiated trades...")
                executed_trades = []
                for proposal in judge_proposals:
                    ticker = proposal["ticker"]
                    price = exec_prices.get(ticker, 0)
                    if price > 0:
                        portfolio = execute_trade(portfolio, proposal, price, "judge_initiated", run_id)
                        executed_trades.append(f"{proposal['action']} {proposal['shares']} {ticker} @ ${price:.2f}")

                if executed_trades:
                    save_portfolio_state(portfolio)
                    trades_str = ", ".join(executed_trades)
                    _emit(run_id, "execution", "done",
                          f"AUTO MODE (judge-initiated): {len(executed_trades)} trades executed: {trades_str} | "
                          f"Cash: ${portfolio['cash']:,.2f}, Positions: {len(portfolio['positions'])}")
                else:
                    _emit(run_id, "execution", "done",
                          "AUTO MODE: Judge disagreed but no trades could be executed")
            elif judge_proposals:
                _emit(run_id, "execution", "done",
                      f"Judge disagrees — {len(judge_proposals)} proposals created for review: {proposals_str}")
            else:
                _emit(run_id, "execution", "done",
                      "Judge disagreed but no trades met conviction threshold (>=60%)")
        except Exception as e:
            _emit(run_id, "execution", "error", f"Judge-initiated proposals failed: {e}")
    elif _is_auto_mode(user_id):
        _emit(run_id, "execution", "skipped", "AUTO MODE: Judge agrees with model — no trades needed")

    # Steps 7 + 7b: P&L report and portfolio snapshot — share the same portfolio/prices
    _emit(run_id, "pnl", "running", "Computing P&L...")
    pnl_data = {"total_return_pct": 0}
    try:
        from src.simulation.pnl import compute_pnl as pnl_compute
        from src.simulation.executor import snapshot_portfolio

        snap_portfolio = load_portfolio_state(user_id)
        # Convert CAD cash → USD once, used for both P&L and snapshot
        if snap_portfolio.get("currency") == "CAD" and snap_portfolio.get("cash", 0) > 0:
            snap_rate = _get_usdcad_rate()
            snap_portfolio = {**snap_portfolio, "cash": round(snap_portfolio["cash"] / snap_rate, 2)}

        snap_tickers = [pos["ticker"] for pos in snap_portfolio["positions"]]
        # Live prices: Wealthsimple → yfinance → DuckDB
        snap_prices = get_live_prices(snap_tickers, snap_portfolio)

        pnl_data = pnl_compute(snap_portfolio, snap_prices)

        # Data display: P&L
        positions_data = []
        for pos in pnl_data.get("positions", []):
            positions_data.append({
                "ticker": pos.get("ticker"),
                "shares": pos.get("shares"),
                "current_price": pos.get("current_price"),
                "market_value": pos.get("market_value"),
                "unrealized_pnl": pos.get("unrealized_pnl"),
                "unrealized_pct": pos.get("unrealized_pct"),
                "weight": pos.get("weight"),
            })
        _emit(
            run_id, "pnl", "done",
            f"Portfolio value: ${pnl_data['total_portfolio_value']:,.2f}, "
            f"P&L: ${pnl_data['total_unrealized_pnl']:,.2f} ({pnl_data['total_return_pct']:.1%})",
            gate_data={
                "total_value": pnl_data.get("total_portfolio_value"),
                "unrealized_pnl": pnl_data.get("total_unrealized_pnl"),
                "total_return_pct": pnl_data.get("total_return_pct"),
                "cash": pnl_data.get("cash"),
                "positions": positions_data,
            }
        )

        snapshot_portfolio(snap_portfolio, pnl_data, snap_prices, source="pipeline", user_id=user_id)
    except Exception as e:
        _emit(run_id, "pnl", "done", f"P&L report skipped: {e}")
        logger.warning(f"P&L / snapshot failed: {e}")

    # Step 8: Self-Learning — outcome tracking + pattern detection + signal quality
    _emit(run_id, "learning", "running", "Running self-learning analysis...")
    try:
        from src.learning.outcome_tracker import run_outcome_tracking
        from src.learning.pattern_detector import detect_patterns

        outcome_result = run_outcome_tracking(user_id)
        patterns = detect_patterns()

        seeded = outcome_result["seeded"]
        summary = outcome_result["summary"]
        alerts = [p for p in patterns if p.get("is_alert")]

        msg_parts = [f"Tracked {seeded} new proposals"]
        if summary.get("classified", 0) > 0:
            msg_parts.append(f"signal win rate: {summary['win_rate']:.0%} ({summary['good']}W/{summary['bad']}L/{summary['neutral']}N)")
        msg_parts.append(f"{len(patterns)} patterns detected")
        if alerts:
            msg_parts.append(f"{len(alerts)} alerts")

        # Signal quality analysis
        try:
            from src.learning.signal_quality import compute_quality_dashboard, detect_factor_decay, log_signal_quality
            quality = compute_quality_dashboard()
            decaying = detect_factor_decay()

            if quality.get("overall_hit_rate"):
                msg_parts.append(f"hit rate: {quality['overall_hit_rate']:.0%}")
            if decaying:
                msg_parts.append(f"ALERT: {len(decaying)} factors decaying")

            if 'as_of_date' in dir():
                log_signal_quality(as_of_date)
        except Exception as sq_e:
            logger.warning(f"Signal quality analysis skipped: {sq_e}")

        _emit(run_id, "learning", "done", " | ".join(msg_parts),
              gate_data={
                  "seeded": seeded,
                  "measurements": outcome_result.get("measurements", {}),
                  "summary": summary,
                  "patterns_count": len(patterns),
                  "alerts": [{"dimension": a.get("dimension"), "dimension_value": a.get("dimension_value"),
                              "alert_message": a.get("alert_message"), "win_rate": a.get("win_rate")}
                             for a in alerts],
              })
    except Exception as e:
        _emit(run_id, "learning", "done", f"Self-learning skipped: {e}")

    # Complete
    _emit(run_id, "complete", "done", "Pipeline finished successfully", summary={
        "signals_total": len(signals) if 'signals' in dir() else 0,
        "signals_actionable": len(actionable) if 'actionable' in dir() else 0,
        "proposals_passed": len(passed_proposals),
    })
    _pipeline_locks[run_id].set()


@app.post("/api/pipeline/run")
async def trigger_pipeline(request: Request, user: AuthUser = Depends(get_current_user)):
    """Start a pipeline run for the signed-in user in a background thread.

    Returns a run_id for SSE streaming. Body (all optional):
        mode: "full" | "sector" | default "full"
        sub_sector: required when mode="sector"
        risk_level: 1-5, default 3

    Concurrency guard: in-memory _pipeline_locks holds one entry per active
    run regardless of user. We could scope by user_id to allow multiple users
    to run concurrently, but for the single-machine local setup a global guard
    is simpler and prevents two users from saturating SnapTrade rate limits.
    """
    in_flight = [rid for rid, lock in _pipeline_locks.items() if not lock.is_set()]
    if in_flight:
        existing = in_flight[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pipeline_already_running",
                "run_id": existing,
                "message": f"Pipeline run {existing} is already in progress. "
                           "Re-subscribe to its SSE stream instead of starting a new one.",
            },
        )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    mode = body.get("mode", "full")
    sub_sector = body.get("sub_sector")
    risk_level = max(1, min(5, int(body.get("risk_level", 3))))

    run_id = str(uuid.uuid4())[:8]
    _pipeline_runs[run_id] = []
    _pipeline_locks[run_id] = threading.Event()
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(run_id, user.id),
        kwargs={"sub_sector_filter": sub_sector if mode == "sector" else None, "risk_level": risk_level},
        daemon=True,
    )
    thread.start()
    return {"run_id": run_id, "mode": mode, "risk_level": risk_level}


@app.get("/api/pipeline/status")
async def pipeline_status(run_id: str):
    """SSE stream of pipeline events for a given run_id."""
    if run_id not in _pipeline_runs:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    async def event_stream():
        sent = 0
        while True:
            events = _pipeline_runs.get(run_id, [])
            while sent < len(events):
                yield f"data: {json.dumps(events[sent])}\n\n"
                sent += 1

            # Check if pipeline is done
            if _pipeline_locks.get(run_id, threading.Event()).is_set() and sent >= len(events):
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ============================================================
# Discovery endpoints
# ============================================================

@app.post("/api/discovery/scan")
def trigger_discovery_scan():
    """Trigger a discovery scan for new stock candidates."""
    from src.discovery.screener import should_run_discovery, run_discovery_scan

    should_run, reason = should_run_discovery()
    if not should_run:
        return {"status": "skipped", "reason": reason}

    def _scan():
        try:
            run_discovery_scan()
        except Exception as e:
            logger.error(f"Discovery scan failed: {e}")

    thread = threading.Thread(target=_scan, daemon=True)
    thread.start()
    return {"status": "started", "reason": reason}


@app.get("/api/discovery/candidates")
def get_discovery_candidates(status: str | None = None, limit: int = 50):
    """List discovery candidates, optionally filtered by status."""
    from src.discovery.screener import get_candidates
    return get_candidates(status=status, limit=limit)


@app.put("/api/discovery/candidates/{ticker}/status")
async def update_discovery_status(ticker: str, request: Request):
    """Update a candidate's status (new → analyzed | promoted | dismissed)."""
    body = await request.json()
    new_status = body.get("status", "dismissed")
    from src.discovery.screener import update_candidate_status
    update_candidate_status(ticker, new_status)
    return {"ticker": ticker, "status": new_status}


@app.post("/api/discovery/candidates/{ticker}/promote")
async def promote_discovery_candidate(ticker: str, request: Request):
    """Promote a discovered ticker to the main universe."""
    body = await request.json()
    sub_sector = body.get("sub_sector", "")
    company_name = body.get("company_name", "")
    if not sub_sector:
        raise HTTPException(status_code=400, detail="sub_sector is required")

    from src.discovery.screener import promote_to_universe
    promote_to_universe(ticker, sub_sector, company_name)
    return {"ticker": ticker, "status": "promoted", "sub_sector": sub_sector}


@app.get("/api/universe/health")
def get_universe_health():
    """Universe health: risk tier distribution, weak tickers, promotion candidates."""
    import pandas as _pd
    universe = _pd.read_csv(settings.paths.universe_path)
    tier_col = universe.get("risk_tier", _pd.Series(["standard"] * len(universe)))
    tier_counts = tier_col.value_counts().to_dict()

    from src.discovery.screener import get_candidates
    weak = get_candidates(status="flagged_weak", limit=20)
    pending = get_candidates(status="new", limit=20)

    return {
        "total_tickers": len(universe),
        "risk_tier_distribution": tier_counts,
        "flagged_weak": weak,
        "pending_candidates": pending,
    }


@app.post("/api/universe/auto-refresh")
def trigger_universe_refresh():
    """Manually trigger auto-promote and auto-demote cycle."""
    from src.discovery.screener import auto_promote_candidates, flag_weak_universe_tickers
    promoted = auto_promote_candidates()
    flagged = flag_weak_universe_tickers()
    return {
        "promoted": promoted,
        "flagged_weak": [f["ticker"] for f in flagged],
    }


# ============================================================
# Watchlist endpoints
# ============================================================

@app.get("/api/watchlist")
def get_watchlist():
    """List all watchlist tickers enriched with latest scores, news, and earnings."""
    try:
        con = get_connection()
        rows = con.execute("""
            SELECT ticker, company_name, sub_sector, added_at, notes, priority
            FROM watchlist ORDER BY priority DESC, added_at DESC
        """).fetchall()
        con.close()
    except Exception:
        return []

    items = []
    for r in rows:
        item = {
            "ticker": r[0],
            "company_name": r[1],
            "sub_sector": r[2],
            "added_at": str(r[3]) if r[3] else None,
            "notes": r[4],
            "priority": r[5],
        }

        # Enrich with latest score
        try:
            con = get_connection()
            score = con.execute("""
                SELECT composite_score, score_decile, quality_score
                FROM factor_scores WHERE ticker = $1
                ORDER BY date DESC LIMIT 1
            """, [r[0]]).fetchone()
            con.close()
            if score:
                item["composite_score"] = round(float(score[0]), 3) if score[0] is not None else None
                item["score_decile"] = int(score[1]) if score[1] is not None else None
                item["quality_score"] = round(float(score[2]), 3) if score[2] is not None else None
        except Exception:
            pass

        # Enrich with latest news sentiment
        try:
            con = get_connection()
            news = con.execute("""
                SELECT sentiment, confidence FROM news_research
                WHERE ticker = $1 ORDER BY research_date DESC LIMIT 1
            """, [r[0]]).fetchone()
            con.close()
            if news:
                item["sentiment"] = news[0]
                item["news_confidence"] = float(news[1]) if news[1] is not None else 0
        except Exception:
            pass

        # Enrich with upcoming earnings
        try:
            from src.ingest.earnings_calendar import get_upcoming_earnings
            upcoming = get_upcoming_earnings([r[0]], days_ahead=30)
            if r[0] in upcoming:
                item["upcoming_earnings"] = upcoming[r[0]]
        except Exception:
            pass

        items.append(item)

    return items


@app.post("/api/watchlist")
async def add_to_watchlist(request: Request):
    """Add a ticker to the watchlist."""
    body = await request.json()
    ticker = body.get("ticker", "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    notes = body.get("notes", "")
    priority = int(body.get("priority", 1))
    company_name = body.get("company_name", "")
    sub_sector = body.get("sub_sector", "")

    # Auto-resolve metadata if not provided
    if not company_name:
        try:
            universe = pd.read_csv(settings.paths.universe_path)
            match = universe[universe["ticker"] == ticker]
            if not match.empty:
                company_name = match.iloc[0].get("name", "")
                sub_sector = sub_sector or match.iloc[0].get("sub_sector", "")
        except Exception:
            pass

    con = get_connection()
    # ON CONFLICT uses EXCLUDED.column rather than re-binding $4/$5 —
    # see the same note on portfolio_snapshots in src/simulation/executor.py.
    con.execute("""
        INSERT INTO watchlist (ticker, company_name, sub_sector, notes, priority)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (ticker) DO UPDATE SET notes = EXCLUDED.notes, priority = EXCLUDED.priority
    """, [ticker, company_name, sub_sector, notes, priority])
    con.close()

    return {"ticker": ticker, "status": "added"}


@app.delete("/api/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    """Remove a ticker from the watchlist."""
    con = get_connection()
    con.execute("DELETE FROM watchlist WHERE ticker = $1", [ticker.upper()])
    con.close()
    return {"ticker": ticker.upper(), "status": "removed"}


@app.put("/api/watchlist/{ticker}")
async def update_watchlist_item(ticker: str, request: Request):
    """Update notes or priority for a watchlist ticker."""
    body = await request.json()
    con = get_connection()
    if "notes" in body:
        con.execute("UPDATE watchlist SET notes = $1 WHERE ticker = $2", [body["notes"], ticker.upper()])
    if "priority" in body:
        con.execute("UPDATE watchlist SET priority = $1 WHERE ticker = $2", [int(body["priority"]), ticker.upper()])
    con.close()
    return {"ticker": ticker.upper(), "status": "updated"}


# ============================================================
# Universe / Sectors endpoints
# ============================================================

@app.get("/api/universe/sectors")
def get_universe_sectors():
    """List all sub_sectors with ticker counts."""
    try:
        universe = pd.read_csv(settings.paths.universe_path)
        sectors = []
        for sub_sector, group in universe.groupby("sub_sector"):
            sectors.append({
                "sub_sector": sub_sector,
                "ticker_count": len(group),
                "tickers": group["ticker"].tolist(),
            })
        sectors.sort(key=lambda s: s["ticker_count"], reverse=True)
        return sectors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Single-Ticker Analysis endpoint
# ============================================================

@app.post("/api/analyze/ticker")
async def analyze_ticker(request: Request):
    """Run AI analysis for a single ticker. Returns structured recommendation."""
    body = await request.json()
    ticker = body.get("ticker", "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    risk_level = max(1, min(5, int(body.get("risk_level", 3))))

    from src.analyst.ticker_analysis import analyze_single_ticker
    try:
        result = analyze_single_ticker(ticker, risk_level=risk_level)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


# ============================================================
# Chatbot endpoints
# ============================================================

@app.post("/api/chat")
async def chat_endpoint(request: Request, user: AuthUser = Depends(get_current_user)):
    """SSE streaming chat endpoint, scoped to the signed-in user."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = body.get("message", "").strip()
    images = body.get("images")
    if not message and not images:
        raise HTTPException(status_code=400, detail="'message' or 'images' field is required")

    session_id = body.get("session_id")

    # The chat agent's tools (portfolio context, etc.) need user_id to read
    # the right data — pass it through so the agent can scope every lookup.
    from src.chat.agent import stream_chat
    return StreamingResponse(
        stream_chat(session_id, message, images=images, user_id=user.id),
        media_type="text/event-stream",
    )


@app.delete("/api/chat/{session_id}")
def delete_chat_session(session_id: str, user: AuthUser = Depends(get_current_user)):
    """Delete a chat session and its history (no-op if the session doesn't belong to the user)."""
    from src.chat.agent import delete_session
    deleted = delete_session(session_id, user_id=user.id)
    return {"deleted": deleted, "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
