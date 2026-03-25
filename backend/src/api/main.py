"""FastAPI backend serving all dashboard data + pipeline streaming."""

import asyncio
import json
import logging
import sys
import threading
import traceback
import uuid
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


@app.on_event("startup")
def startup():
    init_db()


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

    # Step 3: Signal generation
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

        signals = generate_signals(scores, current_weights, prior_deciles, drawdown)
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

    # Step 6: P&L report
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
