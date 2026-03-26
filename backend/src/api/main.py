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
# Auto mode endpoints
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

@app.get("/api/portfolio")
def get_portfolio():
    """Current portfolio state with P&L."""
    try:
        portfolio = load_portfolio_state()
        tickers = [p["ticker"] for p in portfolio["positions"]]
        prices = get_current_prices(tickers)
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
    """Human approves a proposal."""
    con = get_connection()
    con.execute("""
        UPDATE trade_proposals
        SET status = 'APPROVED', human_decision = 'APPROVED', human_notes = ?
        WHERE proposal_id = ?
    """, [notes, proposal_id])
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

    # Step 6: Judge evaluation (now enriched with news context)
    judge_results = []
    if len(passed_proposals) > 0:
        _emit(run_id, "judge", "running", f"Evaluating {len(passed_proposals)} proposals with LLM judge...")
        try:
            from src.judge.client import evaluate_all_proposals
            judge_results = evaluate_all_proposals(passed_proposals, portfolio_value, pnl, research_map)
            _emit(run_id, "judge", "done", f"Judge evaluated {len(judge_results)} proposals")
        except Exception as e:
            _emit(run_id, "judge", "done", f"Judge evaluation skipped: {e}")
    else:
        _emit(run_id, "judge", "skipped", "No proposals to evaluate")

    # Step 6b: Auto-execution (only when auto mode is enabled)
    if _auto_mode["enabled"] and judge_results:
        _emit(run_id, "execution", "running", "AUTO MODE: Executing approved trades...")
        try:
            from src.simulation.executor import execute_proposals, save_portfolio_state

            # Auto-approve all judge-approved proposals
            con = get_connection()
            approved_count = 0
            rejected_count = 0
            for result in judge_results:
                pid = result.get("proposal_id", "")
                verdict = result.get("verdict", "REJECT")
                if verdict == "APPROVE":
                    con.execute("""
                        UPDATE trade_proposals
                        SET status = 'APPROVED', human_decision = 'AUTO_APPROVED',
                            human_notes = 'Auto-approved by auto mode'
                        WHERE proposal_id = ?
                    """, [pid])
                    approved_count += 1
                else:
                    con.execute("""
                        UPDATE trade_proposals
                        SET status = 'REJECTED', human_decision = 'AUTO_REJECTED',
                            human_notes = 'Auto-rejected by auto mode (judge verdict: ' || ? || ')'
                        WHERE proposal_id = ?
                    """, [verdict, pid])
                    rejected_count += 1

            # Fetch approved proposals for execution
            approved_df = con.execute("""
                SELECT * FROM trade_proposals
                WHERE status = 'APPROVED' AND human_decision = 'AUTO_APPROVED'
                  AND created_at >= CURRENT_DATE
            """).fetchdf()
            con.close()

            if not approved_df.empty:
                approved_list = approved_df.to_dict(orient="records")
                portfolio = load_portfolio_state()
                pos_tickers = [pos["ticker"] for pos in portfolio["positions"]]
                exec_tickers = list(set(pos_tickers + [p["ticker"] for p in approved_list]))
                exec_prices = get_current_prices(exec_tickers)

                portfolio, exec_log = execute_proposals(portfolio, approved_list, exec_prices)
                save_portfolio_state(portfolio)

                executed = [e for e in exec_log if e.get("executed")]
                _emit(run_id, "execution", "done",
                      f"AUTO MODE: {approved_count} approved, {rejected_count} rejected, "
                      f"{len(executed)} trades executed | "
                      f"Cash: ${portfolio['cash']:,.2f}, Positions: {len(portfolio['positions'])}")
            else:
                _emit(run_id, "execution", "done",
                      f"AUTO MODE: {approved_count} approved, {rejected_count} rejected, 0 to execute")
        except Exception as e:
            _emit(run_id, "execution", "error", f"Auto-execution failed: {e}")
    elif _auto_mode["enabled"]:
        _emit(run_id, "execution", "skipped", "AUTO MODE: No judge results to execute")

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
