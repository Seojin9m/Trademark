"""FastAPI backend serving all dashboard data + pipeline streaming."""

import asyncio
import json
import logging
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection, init_db
from src.signals.portfolio_engine import (
    load_portfolio_state,
    get_current_prices,
    compute_portfolio_weights,
    compute_portfolio_value,
)
from src.simulation.pnl import compute_pnl
from src.judge.client import get_judge_log


def get_live_prices(tickers: list[str], portfolio: dict | None = None) -> dict[str, float]:
    """Get current prices. Priority: Wealthsimple (from last sync) → yfinance → DuckDB."""
    if not tickers:
        return {}

    prices: dict[str, float] = {}

    # 1. Use prices stored during last Wealthsimple sync
    if portfolio:
        for pos in portfolio.get("positions", []):
            lp = pos.get("last_price")
            if lp and lp > 0 and pos["ticker"] in tickers:
                prices[pos["ticker"]] = lp

    # 2. For any still missing, try yfinance
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
                    prices[t] = float(row[t])
        except Exception:
            pass

    # 3. Final fallback: DuckDB
    still_missing = [t for t in tickers if t not in prices]
    if still_missing:
        prices.update(get_current_prices(still_missing))

    return prices

logger = logging.getLogger("trade4me")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="trade4me API", version="2.0.0")


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
    allow_headers=["*"],
)

# Pipeline run state: run_id -> list of events
_pipeline_runs: dict[str, list[dict]] = {}
_pipeline_locks: dict[str, threading.Event] = {}

# Auto mode state: when enabled, pipeline auto-approves and executes judge-approved trades
_auto_mode: dict = {"enabled": False}


@app.on_event("startup")
def startup():
    init_db()


# ============================================================
# Brokerage integration endpoints (SnapTrade)
# ============================================================

@app.get("/api/brokerage/status")
def brokerage_status():
    """Check brokerage connection status."""
    try:
        from src.ingest.brokerage import get_connection_status
        return get_connection_status()
    except Exception as e:
        logger.error(f"Brokerage status check failed: {e}")
        return {"connected": False, "status": f"error: {e}", "accounts": []}


@app.post("/api/brokerage/connect")
def brokerage_connect(broker: str = "WEALTHSIMPLETRADE"):
    """Generate a connection URL for the SnapTrade Connection Portal.

    The user opens this URL in a new tab to log into their brokerage.
    """
    try:
        from src.ingest.brokerage import get_connect_url
        return get_connect_url(broker)
    except Exception as e:
        logger.error(f"Brokerage connect failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/brokerage/sync")
def brokerage_sync(account_id: str | None = None):
    """Fetch positions and balances from brokerage → update portfolio_state.json."""
    try:
        from src.ingest.brokerage import sync_portfolio
        return sync_portfolio(account_id)
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


@app.get("/api/brokerage/debug")
def brokerage_debug():
    """Raw SnapTrade account data for debugging."""
    try:
        from src.ingest.brokerage import _get_client, _load_state
        state = _load_state()
        client = _get_client()
        accounts = client.account_information.list_user_accounts(
            user_id=state["user_id"],
            user_secret=state["user_secret"],
        )
        return {"raw_accounts": [dict(acc) for acc in accounts.body]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brokerage/partner-info")
def brokerage_partner_info():
    """Check SnapTrade partner info — which brokerages are allowed for this Client ID."""
    try:
        from src.ingest.brokerage import get_partner_info
        return get_partner_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/brokerage/disconnect")
def brokerage_disconnect():
    """Disconnect brokerage and delete SnapTrade user."""
    try:
        from src.ingest.brokerage import delete_user
        return delete_user()
    except Exception as e:
        logger.error(f"Brokerage disconnect failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Auto mode / reset endpoints
# ============================================================

@app.post("/api/reset")
def reset_trading_data(keep_prices: bool = True):
    """Reset all trading data: proposals, decisions, outcomes, patterns, judge logs, portfolio.

    Keeps price/fundamental/macro data by default (expensive to re-fetch).
    Resets portfolio_state.json back to default (cash only, no positions).
    """
    import sqlite3

    con = get_connection()

    # Tables to always clear (trading activity)
    always_clear = [
        "trade_executions",
        "portfolio_snapshots",
        "trade_proposals",
        "decision_outcomes",
        "decision_patterns",
        "simulated_positions",
        "news_research",
    ]

    # Optionally clear these too
    optional_clear = ["adaptive_state"]

    cleared = []
    for table in always_clear + optional_clear:
        try:
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            con.execute(f"DELETE FROM {table}")
            cleared.append(f"{table} ({count} rows)")
        except Exception:
            pass  # Table may not exist yet

    if not keep_prices:
        for table in ["prices", "fundamentals_pit", "factor_scores", "macro_data"]:
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                con.execute(f"DELETE FROM {table}")
                cleared.append(f"{table} ({count} rows)")
            except Exception:
                pass

    con.close()

    # Clear SQLite judge log
    judge_log_path = settings.paths.judge_log_path
    judge_cleared = 0
    if judge_log_path.exists():
        try:
            jcon = sqlite3.connect(str(judge_log_path))
            judge_cleared = jcon.execute("SELECT COUNT(*) FROM judge_log").fetchone()[0]
            jcon.execute("DELETE FROM judge_log")
            jcon.commit()
            jcon.close()
            cleared.append(f"judge_log ({judge_cleared} rows)")
        except Exception:
            pass

    # Reset portfolio state to clean slate
    import json
    default_portfolio = {
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "cash": 100000.00,
        "positions": [],
    }
    with open(settings.paths.portfolio_state_path, "w") as f:
        json.dump(default_portfolio, f, indent=2)
    cleared.append("portfolio_state.json (reset to $100k cash)")

    logger.warning(f"RESET: Cleared {len(cleared)} data stores: {', '.join(cleared)}")
    return {
        "status": "reset_complete",
        "cleared": cleared,
        "kept_prices": keep_prices,
    }


@app.get("/api/auto-mode")
def get_auto_mode():
    """Get current auto mode state."""
    return _auto_mode


@app.post("/api/auto-mode")
def set_auto_mode(enabled: bool):
    """Toggle auto mode. When enabled, the pipeline will auto-approve and execute
    all judge-APPROVED trades without human review."""
    _auto_mode["enabled"] = enabled
    logger.warning(f"AUTO MODE {'ENABLED' if enabled else 'DISABLED'}")
    return _auto_mode


# ============================================================
# Portfolio endpoints
# ============================================================

def _get_usdcad_rate() -> float:
    """Fetch live USD/CAD rate. Returns 1.38 as fallback."""
    try:
        import yfinance as yf
        hist = yf.Ticker("USDCAD=X").history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1.38


@app.get("/api/portfolio")
def get_portfolio():
    """Current portfolio state with P&L."""
    try:
        portfolio = load_portfolio_state()

        # Cash from Wealthsimple TFSA is in CAD — convert to USD for P&L
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


@app.get("/api/proposals")
def get_proposals(status: str | None = None, limit: int = 50):
    """Trade proposals, optionally filtered by status."""
    con = get_connection()
    if status:
        df = con.execute("""
            SELECT * FROM trade_proposals
            WHERE status = ?
            ORDER BY created_at DESC LIMIT ?
        """, [status, limit]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM trade_proposals
            ORDER BY created_at DESC LIMIT ?
        """, [limit]).fetchdf()
    con.close()
    return df.to_dict(orient="records")


@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, notes: str = ""):
    """Human approves a proposal for self-learning tracking. Does not execute a real trade."""
    con = get_connection()
    row = con.execute(
        "SELECT * FROM trade_proposals WHERE proposal_id = ?", [proposal_id]
    ).fetchone()
    if not row:
        con.close()
        return {"status": "not_found", "proposal_id": proposal_id}

    con.execute("""
        UPDATE trade_proposals
        SET status = 'APPROVED', human_decision = 'APPROVED', human_notes = ?
        WHERE proposal_id = ?
    """, [notes or "Human approved", proposal_id])
    con.close()

    return {"status": "approved", "proposal_id": proposal_id}


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, notes: str = ""):
    """Human rejects a proposal."""
    con = get_connection()
    con.execute("""
        UPDATE trade_proposals
        SET status = 'REJECTED', human_decision = 'REJECTED', human_notes = ?
        WHERE proposal_id = ?
    """, [notes, proposal_id])
    con.close()
    return {"status": "rejected", "proposal_id": proposal_id}


@app.get("/api/judge-log")
def get_judge_log_endpoint(limit: int = 50):
    """Recent LLM judge decisions."""
    return get_judge_log(limit)


@app.get("/api/judge/portfolio-review")
def get_portfolio_review():
    """Get the latest portfolio review from the judge log."""
    logs = get_judge_log(20)
    for log in logs:
        if log.get("action") == "REVIEW" and log.get("ticker") == "PORTFOLIO":
            try:
                import json
                return json.loads(log.get("output_payload", "{}"))
            except Exception:
                return log
    return {"message": "No portfolio review yet. Run the pipeline."}


@app.get("/api/executions")
def get_executions(limit: int = 100):
    """Trade execution history — actual trades that were applied to the portfolio."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT * FROM trade_executions
            ORDER BY executed_at DESC
            LIMIT $1
        """, [limit]).fetchdf()
        con.close()
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception:
        con.close()
        return []


@app.get("/api/portfolio/history")
def get_portfolio_history(days: int = 90):
    """Portfolio value time series from snapshots."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT snapshot_date, total_value, cash, positions_value,
                   n_positions, unrealized_pnl, total_return_pct,
                   benchmark_value, positions_detail
            FROM portfolio_snapshots
            WHERE snapshot_source = 'pipeline'
            ORDER BY snapshot_date DESC
            LIMIT $1
        """, [days]).fetchdf()
        con.close()
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception:
        con.close()
        return []


# ============================================================
# Analyst endpoints
# ============================================================

@app.post("/api/analyst/review")
def request_analyst_review():
    """Run an on-demand portfolio review by the LLM quantitative analyst."""
    try:
        from src.analyst.review import run_analyst_review
        portfolio = load_portfolio_state()
        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_live_prices(tickers, portfolio)

        # Convert CAD cash to USD for consistent reporting
        if portfolio.get("currency") == "CAD" and portfolio.get("cash", 0) > 0:
            rate = _get_usdcad_rate()
            portfolio = {**portfolio, "cash": round(portfolio["cash"] / rate, 2)}

        from src.simulation.pnl import compute_pnl
        pnl = compute_pnl(portfolio, prices)

        # Load scores if available
        scores_df = None
        try:
            from src.db.schema import get_connection
            con = get_connection()
            import pandas as pd
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

        # Load regime if available
        regime = {}
        try:
            from src.learning.adaptive import AdaptiveStrategyEngine
            engine = AdaptiveStrategyEngine()
            state = engine.load_state()
            if state and state.get("regime"):
                regime = state["regime"]
        except Exception:
            pass

        review = run_analyst_review(portfolio, pnl, scores_df=scores_df, regime=regime)
        return review
    except Exception as e:
        logger.error(f"Analyst review failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analyst/review")
def get_analyst_review():
    """Get the latest analyst review."""
    try:
        from src.analyst.review import load_review
        review = load_review()
        if not review:
            return {"review": None}
        return {"review": review}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyst/apply")
def apply_analyst_review(apply: bool = True):
    """Mark the analyst review to be applied (or unapplied) in the next pipeline run."""
    try:
        from src.analyst.review import set_apply_to_pipeline
        review = set_apply_to_pipeline(apply)
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
def get_risk_metrics():
    """Current risk metrics: drawdown, concentration, beta."""
    try:
        portfolio = load_portfolio_state()
        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_current_prices(tickers)
        weights = compute_portfolio_weights(portfolio, prices)
        pnl = compute_pnl(portfolio, prices)

        universe = pd.read_csv(settings.paths.universe_path)

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
    df = pd.read_csv(settings.paths.universe_path)
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

@app.get("/api/learning/outcomes")
def get_learning_outcomes(limit: int = 100):
    """Decision outcomes with measured returns."""
    try:
        from src.learning.outcome_tracker import get_outcomes
        return get_outcomes(limit)
    except Exception as e:
        logger.error(f"Learning outcomes endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/summary")
def get_learning_summary():
    """High-level outcome summary: win rate, totals, averages."""
    try:
        from src.learning.outcome_tracker import get_outcome_summary
        return get_outcome_summary()
    except Exception as e:
        logger.error(f"Learning summary endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/patterns")
def get_learning_patterns():
    """Detected decision patterns across all dimensions."""
    try:
        from src.learning.pattern_detector import get_patterns
        return get_patterns()
    except Exception as e:
        logger.error(f"Learning patterns endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/alerts")
def get_learning_alerts():
    """Alerting patterns (low win rate with sufficient sample size)."""
    try:
        from src.learning.pattern_detector import get_alerts
        return get_alerts()
    except Exception as e:
        logger.error(f"Learning alerts endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning/adaptive")
def get_adaptive_state_endpoint():
    """Current adaptive strategy state: regime, IC analysis, constraints."""
    try:
        from src.learning.adaptive import get_adaptive_state
        state = get_adaptive_state()
        return state or {"message": "No adaptive state computed yet. Run the pipeline."}
    except Exception as e:
        logger.error(f"Adaptive state endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Pipeline streaming endpoints
# ============================================================

def _emit(run_id: str, step: str, status: str, message: str, **extra: object) -> None:
    """Push an event to the pipeline run log."""
    event = {"step": step, "status": status, "message": message, **extra}
    _pipeline_runs.setdefault(run_id, []).append(event)
    log_fn = logger.error if status == "error" else logger.info
    log_fn(f"[pipeline:{run_id}] [{step}] {status}: {message}")


def _run_pipeline_thread(run_id: str) -> None:
    """Execute the full pipeline in a background thread, emitting SSE events."""
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

        already_exists, existing_count = check_eod_data_exists()
        if already_exists:
            _emit(run_id, "ingestion", "done", f"Skipped - EOD data already exists ({existing_count} tickers)")
        else:
            eod_df = fetch_polygon_eod(all_tickers)
            if not eod_df.empty:
                store_prices(eod_df)
                _emit(run_id, "ingestion", "done", f"Ingested {len(eod_df)} EOD prices")
            else:
                _emit(run_id, "ingestion", "done", "No new EOD prices (market may be closed)")
    except Exception as e:
        _emit(run_id, "ingestion", "done", f"Price ingestion skipped: {e}")

    # Step 2: Scoring
    _emit(run_id, "scoring", "running", "Computing factor scores...")
    try:
        from src.signals.ranker import rank_universe, store_scores, get_prior_deciles
        scores = rank_universe()
        if scores.empty:
            _emit(run_id, "scoring", "error", "No scores computed")
            _emit(run_id, "complete", "error", "Pipeline failed at scoring")
            _pipeline_locks[run_id].set()
            return

        store_scores(scores)
        as_of_date = str(scores["date"].iloc[0])
        top5 = scores.head(5)["ticker"].tolist()
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
              f"Size scalar: {adaptive_params.get('position_size_scalar', 1):.0%} | Weights: {weights_msg}")
    except Exception as e:
        _emit(run_id, "adaptive", "done", f"Adaptive analysis skipped: {e}")

    # Step 4: Signal generation
    _emit(run_id, "signals", "running", "Generating signals...")
    try:
        from src.signals.decision_rules import generate_signals, filter_actionable_signals

        portfolio = load_portfolio_state()
        pos_tickers = [pos["ticker"] for pos in portfolio["positions"]]
        all_t = list(set(pos_tickers + scores["ticker"].tolist()))
        prices = get_current_prices(all_t)
        current_weights = compute_portfolio_weights(portfolio, prices)
        portfolio_value = compute_portfolio_value(portfolio, prices)
        prior_deciles = get_prior_deciles(as_of_date)

        pnl = compute_pnl(portfolio, prices)
        drawdown = pnl["total_return_pct"] if pnl["total_return_pct"] < 0 else 0.0

        signals = generate_signals(scores, current_weights, prior_deciles, drawdown, adaptive_params=adaptive_params)
        actionable = filter_actionable_signals(signals)

        if len(actionable) == 0:
            _emit(run_id, "signals", "done", f"{len(signals)} signals, 0 actionable - no trades recommended today")
        else:
            action_summary = ", ".join(f"{s['action']} {s['ticker']}" for s in actionable[:5])
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
        universe = pd.read_csv(settings.paths.universe_path)
        proposals = build_trade_proposals(actionable, portfolio, prices, universe)
        for p in proposals:
            p["run_id"] = run_id
        store_proposals(proposals)

        passed = [p for p in proposals if p["constraint_check"]["passed"]]
        blocked = [p for p in proposals if not p["constraint_check"]["passed"]]

        if len(proposals) == 0:
            _emit(run_id, "proposals", "done", "No proposals created (all positions held)")
        else:
            _emit(run_id, "proposals", "done", f"{len(passed)} proposals passed constraints, {len(blocked)} blocked")
    except Exception as e:
        _emit(run_id, "proposals", "error", f"Proposal generation failed: {e}")
        proposals = []
        passed = []

    # Step 5: News research
    passed_proposals = passed if 'passed' in dir() else []
    research_map: dict = {}  # ticker -> NewsResearch
    research_tickers_list = list(set(
        [p["ticker"] for p in passed_proposals]
        + [pos["ticker"] for pos in portfolio["positions"]]
    ))[:20]  # Limit to top 20

    if research_tickers_list:
        _emit(run_id, "research", "running", f"Researching news for {len(research_tickers_list)} tickers...")
        try:
            from src.research.news_agent import collect_news_batch
            from src.research.summarizer import research_tickers as summarize_batch, store_research

            news_data = collect_news_batch(research_tickers_list, max_per_ticker=6)
            research_results = summarize_batch(research_tickers_list, news_data)
            store_research(research_results)

            research_map = {r.ticker: r for r in research_results}
            with_news = sum(1 for r in research_results if r.confidence > 0)
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

    # Check if analyst guidance is active and log it
    try:
        from src.analyst.review import get_pipeline_guidance
        guidance = get_pipeline_guidance()
        if guidance:
            _emit(run_id, "judge", "running", "Analyst guidance active — injecting into judge prompts...")
    except Exception:
        pass
    if len(passed_proposals) > 0:
        _emit(run_id, "judge", "running", f"Evaluating {len(passed_proposals)} proposals with LLM judge...")
        try:
            from src.judge.client import evaluate_all_proposals
            judge_results = evaluate_all_proposals(passed_proposals, portfolio_value, pnl, research_map)
            _emit(run_id, "judge", "done", f"Judge evaluated {len(judge_results)} proposals")
        except Exception as e:
            _emit(run_id, "judge", "done", f"Judge evaluation skipped: {e}")
    else:
        _emit(run_id, "judge", "running", "No proposals — running full portfolio review...")
        try:
            from src.judge.client import evaluate_portfolio_review
            regime_data = adaptive_result.get("regime") if 'adaptive_result' in dir() else None
            portfolio_review = evaluate_portfolio_review(
                portfolio, scores, pnl, portfolio_value,
                research_map=research_map, regime=regime_data,
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
        except Exception as e:
            _emit(run_id, "judge", "done", f"Portfolio review skipped: {e}")

    if portfolio_review and portfolio_review.get("overall_verdict") == "disagree":
        # Judge disagrees with HOLD — create proposals from suggestions
        try:
            from src.simulation.executor import execute_trade, save_portfolio_state
            from src.signals.portfolio_engine import store_proposals

            portfolio = load_portfolio_state()
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
                        "status": "APPROVED" if _auto_mode["enabled"] else "NEEDS_REVIEW",
                        "signal_data": {"source": "judge_review", "reason": h.get("reason", ""), "conviction": h.get("conviction", 0)},
                        "constraint_check": {"passed": True},
                        "human_decision": "JUDGE_INITIATED" if _auto_mode["enabled"] else None,
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
                    "status": "APPROVED" if _auto_mode["enabled"] else "NEEDS_REVIEW",
                    "signal_data": {"source": "judge_review", "reason": m.get("reason", ""), "conviction": m.get("conviction", 0)},
                    "constraint_check": {"passed": True},
                    "human_decision": "JUDGE_INITIATED" if _auto_mode["enabled"] else None,
                    "human_notes": f"Judge portfolio review: {m.get('reason', '')}",
                    "created_at": datetime.now().isoformat(),
                })

            # Store all proposals
            if judge_proposals:
                store_proposals(judge_proposals)
                proposals_str = ", ".join(f"{p['action']} {p['shares']} {p['ticker']}" for p in judge_proposals)

            # Execute if auto mode, otherwise just show as pending
            if _auto_mode["enabled"] and judge_proposals:
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
    elif _auto_mode["enabled"]:
        _emit(run_id, "execution", "skipped", "AUTO MODE: Judge agrees with model — no trades needed")

    # Step 7: P&L report
    _emit(run_id, "pnl", "running", "Computing P&L...")
    try:
        from src.simulation.pnl import compute_pnl as pnl_compute
        portfolio = load_portfolio_state()
        pos_tickers = [pos["ticker"] for pos in portfolio["positions"]]
        prices = get_current_prices(pos_tickers)
        pnl_data = pnl_compute(portfolio, prices)
        _emit(
            run_id, "pnl", "done",
            f"Portfolio value: ${pnl_data['total_portfolio_value']:,.2f}, "
            f"P&L: ${pnl_data['total_unrealized_pnl']:,.2f} ({pnl_data['total_return_pct']:.1%})"
        )
    except Exception as e:
        _emit(run_id, "pnl", "done", f"P&L report skipped: {e}")

    # Step 7b: Portfolio snapshot
    try:
        from src.simulation.executor import snapshot_portfolio
        portfolio = load_portfolio_state()
        pos_tickers = [pos["ticker"] for pos in portfolio["positions"]]
        snap_prices = get_current_prices(pos_tickers)
        pnl_for_snap = pnl_data if 'pnl_data' in dir() else {"total_return_pct": 0}
        snapshot_portfolio(portfolio, pnl_for_snap, snap_prices, source="pipeline")
    except Exception as e:
        logger.warning(f"Portfolio snapshot failed: {e}")

    # Step 8: Self-Learning — outcome tracking + pattern detection
    _emit(run_id, "learning", "running", "Running self-learning analysis...")
    try:
        from src.learning.outcome_tracker import run_outcome_tracking
        from src.learning.pattern_detector import detect_patterns

        outcome_result = run_outcome_tracking()
        patterns = detect_patterns()

        seeded = outcome_result["seeded"]
        measured = outcome_result["measurements"]
        summary = outcome_result["summary"]
        alerts = [p for p in patterns if p.get("is_alert")]

        msg_parts = [f"Seeded {seeded} new outcomes"]
        if summary.get("classified", 0) > 0:
            msg_parts.append(f"win rate: {summary['win_rate']:.0%} ({summary['good']}W/{summary['bad']}L/{summary['neutral']}N)")
        msg_parts.append(f"{len(patterns)} patterns detected")
        if alerts:
            msg_parts.append(f"{len(alerts)} alerts")

        _emit(run_id, "learning", "done", " | ".join(msg_parts))
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
def trigger_pipeline():
    """Start a pipeline run in a background thread. Returns a run_id for SSE streaming."""
    run_id = str(uuid.uuid4())[:8]
    _pipeline_runs[run_id] = []
    _pipeline_locks[run_id] = threading.Event()
    thread = threading.Thread(target=_run_pipeline_thread, args=(run_id,), daemon=True)
    thread.start()
    return {"run_id": run_id}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
