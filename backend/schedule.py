"""Daily job orchestration for Trademark.

Runs the full EOD pipeline:
1. Ingest latest prices from Polygon.io
2. Compute factor scores and rank universe
3. Generate signals and trade proposals
4. Send proposals to LLM judge (Phase 4)
5. Await human confirmation via dashboard (Phase 4)
"""

import sys
from datetime import datetime

import pandas as pd
import pytz

from config.settings import settings
from src.db.schema import init_db
from src.signals.ranker import rank_universe, store_scores, get_prior_deciles
from src.signals.decision_rules import generate_signals, filter_actionable_signals, get_recent_trades
from src.signals.portfolio_engine import (
    load_portfolio_state,
    get_current_prices,
    compute_portfolio_weights,
    compute_portfolio_value,
    build_trade_proposals,
    store_proposals,
)
from src.simulation.pnl import compute_pnl, print_pnl_report


def run_eod_pipeline() -> dict:
    """Execute the full end-of-day pipeline.

    Returns dict with scores, signals, proposals, and P&L for dashboard use.
    """
    tz = pytz.timezone(settings.schedule.timezone)
    now = datetime.now(tz)
    print(f"[{now.isoformat()}] Starting EOD pipeline...")

    init_db()

    # --- Step 1: Data ingestion (skip if already fetched today) ---
    print("\n  [1/5] Data ingestion...")
    try:
        from src.ingest.prices import load_universe, fetch_polygon_eod, store_prices, check_eod_data_exists
        tickers = load_universe()
        benchmarks = [settings.primary_benchmark, settings.secondary_benchmark]
        all_tickers = tickers + [b for b in benchmarks if b not in tickers]

        already_exists, existing_count, latest_date = check_eod_data_exists()
        if already_exists:
            print(f"    Skipped — already have {existing_count} tickers for {latest_date}")
        else:
            eod_df = fetch_polygon_eod(all_tickers)
            if not eod_df.empty:
                store_prices(eod_df)
                print(f"    Ingested {len(eod_df)} EOD prices from Polygon.io")
            else:
                print("    No new EOD prices (market may be closed)")
    except Exception as e:
        print(f"    WARNING: Price ingestion failed: {e}")
        print("    Continuing with existing data...")

    # --- Step 2: Feature computation ---
    print("\n  [2/5] Scoring and ranking universe...")
    scores = rank_universe()
    if scores.empty:
        print("    ERROR: No scores computed, aborting pipeline")
        return {}

    store_scores(scores)
    as_of_date = str(scores["date"].iloc[0])
    print(f"    Scored {len(scores)} tickers as of {as_of_date}")
    print(f"    Top 5: {scores.head(5)['ticker'].tolist()}")
    print(f"    Bottom 5: {scores.tail(5)['ticker'].tolist()}")

    # --- Step 3: Signal generation ---
    print("\n  [3/5] Generating signals...")

    portfolio = load_portfolio_state()
    all_tickers = [pos["ticker"] for pos in portfolio["positions"]] + scores["ticker"].tolist()
    prices = get_current_prices(list(set(all_tickers)))
    current_weights = compute_portfolio_weights(portfolio, prices)
    portfolio_value = compute_portfolio_value(portfolio, prices)
    prior_deciles = get_prior_deciles(as_of_date)

    # Compute drawdown (simplified: vs cost basis for now)
    pnl = compute_pnl(portfolio, prices)
    drawdown = pnl["total_return_pct"] if pnl["total_return_pct"] < 0 else 0.0

    recent_trades = get_recent_trades()
    signals = generate_signals(scores, current_weights, prior_deciles, drawdown, recent_trades=recent_trades)
    actionable = filter_actionable_signals(signals)

    print(f"    Total signals: {len(signals)} ({len(actionable)} actionable)")
    for s in actionable:
        print(f"    {s['action']:>5} {s['ticker']:<6} | decile {s['score_decile']} (was {s['prior_decile']}) | {s['reason']}")

    # --- Step 4: Build trade proposals ---
    universe = pd.read_csv(settings.paths.universe_path)
    proposals = build_trade_proposals(actionable, portfolio, prices, universe)
    store_proposals(proposals)

    passed = [p for p in proposals if p["constraint_check"]["passed"]]
    blocked = [p for p in proposals if not p["constraint_check"]["passed"]]
    print(f"    Proposals: {len(passed)} passed constraints, {len(blocked)} blocked")
    for p in blocked:
        print(f"    BLOCKED: {p['action']} {p['ticker']} - {p['constraint_check']['violations']}")

    # --- Step 5: News research ---
    print("\n  [5/7] News research...")
    research_map = {}
    try:
        from src.research.news_agent import collect_news_batch
        from src.research.summarizer import research_tickers as summarize_batch, store_research

        research_tickers_list = list(set(
            [p["ticker"] for p in passed]
            + [pos["ticker"] for pos in portfolio["positions"]]
        ))[:20]

        news_data = collect_news_batch(research_tickers_list, max_per_ticker=6)
        research_results = summarize_batch(research_tickers_list, news_data)
        store_research(research_results)
        research_map = {r.ticker: r for r in research_results}
        print(f"    Researched {len(research_results)} tickers")
    except Exception as e:
        print(f"    WARNING: News research failed: {e}")

    # --- Step 6: LLM judge review ---
    print("\n  [6/7] LLM judge review...")
    try:
        from src.judge.client import evaluate_all_proposals
        judge_results = evaluate_all_proposals(passed, portfolio_value, pnl, research_map, recent_trades=recent_trades)
        print(f"    Judge evaluated {len(judge_results)} proposals")
    except Exception as e:
        print(f"    WARNING: Judge failed: {e}")

    # --- Step 7: P&L report ---
    print("\n  [7/7] P&L report...")
    print_pnl_report(pnl)

    print(f"\n[{datetime.now(tz).isoformat()}] EOD pipeline complete.")

    return {
        "scores": scores,
        "signals": signals,
        "proposals": proposals,
        "pnl": pnl,
        "portfolio_value": portfolio_value,
    }


if __name__ == "__main__":
    if "--now" in sys.argv:
        run_eod_pipeline()
    else:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BlockingScheduler()
        trigger = CronTrigger(
            hour=settings.schedule.eod_run_hour,
            minute=settings.schedule.eod_run_minute,
            timezone=settings.schedule.timezone,
            day_of_week="mon-fri",
        )
        scheduler.add_job(run_eod_pipeline, trigger)
        print(
            f"Scheduler started. EOD pipeline will run at "
            f"{settings.schedule.eod_run_hour}:{settings.schedule.eod_run_minute:02d} ET, Mon-Fri."
        )
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("Scheduler stopped.")
