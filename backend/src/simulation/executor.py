"""Simulated trade execution: apply approved trades to portfolio state."""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection


def log_execution_to_db(
    proposal: dict,
    execution_price: float,
    shares_executed: int,
    success: bool,
    execution_source: str,
    pre_cash: float,
    post_cash: float,
    pre_position_shares: int,
    post_position_shares: int,
    run_id: str | None = None,
    failure_reason: str | None = None,
) -> str:
    """Write a row to trade_executions and return the execution_id."""
    execution_id = f"exec-{uuid.uuid4().hex[:10]}"
    total_value = shares_executed * execution_price

    con = get_connection()
    con.execute("""
        INSERT INTO trade_executions
        (execution_id, proposal_id, run_id, ticker, action, shares,
         execution_price, total_value, execution_source,
         pre_cash, post_cash, pre_position_shares, post_position_shares,
         success, failure_reason, executed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
    """, [
        execution_id,
        proposal.get("proposal_id", "unknown"),
        run_id,
        proposal["ticker"],
        proposal["action"],
        shares_executed,
        execution_price,
        total_value,
        execution_source,
        pre_cash,
        post_cash,
        pre_position_shares,
        post_position_shares,
        success,
        failure_reason,
        datetime.now().isoformat(),
    ])

    # Mark the proposal as EXECUTED in trade_proposals
    if success:
        con.execute("""
            UPDATE trade_proposals SET status = 'EXECUTED'
            WHERE proposal_id = $1
        """, [proposal.get("proposal_id")])

    con.close()
    return execution_id


def execute_trade(
    portfolio: dict,
    proposal: dict,
    current_price: float,
    execution_source: str = "auto_pipeline",
    run_id: str | None = None,
) -> dict:
    """Apply a single approved trade to the portfolio state and log to DB.

    Returns updated portfolio dict.
    """
    ticker = proposal["ticker"]
    action = proposal["action"]
    shares = proposal["shares"]

    pre_cash = portfolio["cash"]

    # Find existing position
    existing = None
    for i, pos in enumerate(portfolio["positions"]):
        if pos["ticker"] == ticker:
            existing = i
            break

    pre_position_shares = portfolio["positions"][existing]["shares"] if existing is not None else 0

    if action in ("BUY", "ADD"):
        cost = shares * current_price
        if cost > portfolio["cash"]:
            print(f"  WARNING: Insufficient cash for {action} {shares} {ticker}")
            shares = int(portfolio["cash"] / current_price)
            cost = shares * current_price

        if shares <= 0:
            log_execution_to_db(
                proposal, current_price, 0, False, execution_source,
                pre_cash, pre_cash, pre_position_shares, pre_position_shares,
                run_id, "Insufficient cash",
            )
            return portfolio

        portfolio["cash"] -= cost

        if existing is not None:
            pos = portfolio["positions"][existing]
            total_shares = pos["shares"] + shares
            total_cost = (pos["shares"] * pos["cost_basis_per_share"]) + cost
            pos["shares"] = total_shares
            pos["cost_basis_per_share"] = total_cost / total_shares
        else:
            portfolio["positions"].append({
                "ticker": ticker,
                "shares": shares,
                "cost_basis_per_share": current_price,
                "date_acquired": datetime.now().strftime("%Y-%m-%d"),
            })

    elif action in ("SELL", "TRIM"):
        if existing is None:
            print(f"  WARNING: Cannot {action} {ticker}, not in portfolio")
            log_execution_to_db(
                proposal, current_price, 0, False, execution_source,
                pre_cash, pre_cash, 0, 0,
                run_id, f"Position {ticker} not in portfolio",
            )
            return portfolio

        pos = portfolio["positions"][existing]
        sell_shares = min(shares, pos["shares"])
        proceeds = sell_shares * current_price

        portfolio["cash"] += proceeds
        pos["shares"] -= sell_shares

        if pos["shares"] <= 0:
            portfolio["positions"].pop(existing)

        shares = sell_shares  # actual shares sold

    # Determine post-execution position shares
    post_pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
    post_position_shares = post_pos["shares"] if post_pos else 0

    portfolio["as_of_date"] = datetime.now().strftime("%Y-%m-%d")

    # Log successful execution
    log_execution_to_db(
        proposal, current_price, shares, True, execution_source,
        pre_cash, portfolio["cash"], pre_position_shares, post_position_shares,
        run_id,
    )

    return portfolio


def execute_proposals(
    portfolio: dict,
    proposals: list[dict],
    prices: dict[str, float],
    execution_source: str = "auto_pipeline",
    run_id: str | None = None,
) -> tuple[dict, list[dict]]:
    """Execute all approved proposals and return updated portfolio + execution log."""
    execution_log = []

    for p in proposals:
        if p.get("status") != "APPROVED":
            continue

        ticker = p["ticker"]
        price = prices.get(ticker, 0)
        if price <= 0:
            log_execution_to_db(
                p, 0, 0, False, execution_source,
                portfolio["cash"], portfolio["cash"], 0, 0,
                run_id, "No price available",
            )
            execution_log.append({**p, "executed": False, "reason": "No price available"})
            continue

        portfolio = execute_trade(portfolio, p, price, execution_source, run_id)
        execution_log.append({
            **p,
            "executed": True,
            "execution_price": price,
            "execution_time": datetime.now().isoformat(),
        })
        print(f"  Executed: {p['action']} {p['shares']} {ticker} @ ${price:.2f}")

    return portfolio, execution_log


def snapshot_portfolio(
    portfolio: dict,
    pnl: dict,
    prices: dict[str, float],
    source: str = "pipeline",
) -> None:
    """Record a point-in-time snapshot of portfolio value to the DB."""
    snapshot_id = f"snap-{uuid.uuid4().hex[:10]}"
    today = datetime.now().strftime("%Y-%m-%d")

    # Compute position details
    positions_value = 0.0
    total_cost_basis = 0.0
    positions_detail = []

    for pos in portfolio.get("positions", []):
        ticker = pos["ticker"]
        price = prices.get(ticker, 0)
        market_value = pos["shares"] * price
        cost = pos["shares"] * pos.get("cost_basis_per_share", 0)
        positions_value += market_value
        total_cost_basis += cost
        positions_detail.append({
            "ticker": ticker,
            "shares": pos["shares"],
            "price": round(price, 2),
            "market_value": round(market_value, 2),
            "cost_basis": round(cost, 2),
            "pnl": round(market_value - cost, 2),
        })

    total_value = portfolio.get("cash", 0) + positions_value
    unrealized_pnl = positions_value - total_cost_basis

    # Get benchmark price
    benchmark = settings.primary_benchmark
    benchmark_price = prices.get(benchmark)
    if not benchmark_price:
        con = get_connection()
        row = con.execute("""
            SELECT adj_close FROM prices
            WHERE ticker = $1 AND adj_close > 0
            ORDER BY date DESC LIMIT 1
        """, [benchmark]).fetchone()
        con.close()
        benchmark_price = row[0] if row else None

    con = get_connection()
    # ON CONFLICT uses EXCLUDED.column refs instead of re-binding $N. Two
    # reasons: (1) Postgres convention — EXCLUDED is the cleaner upsert
    # idiom. (2) Our PgConnectionAdapter regex-translates every $N to %s,
    # so reusing $1/$3/... in the SET clause used to balloon the expected
    # param count from 13 to 24 and trigger psycopg2 IndexError
    # ("list index out of range"). EXCLUDED keeps each parameter $N
    # appearing exactly once.
    con.execute("""
        INSERT INTO portfolio_snapshots
        (snapshot_id, snapshot_date, total_value, cash, positions_value,
         n_positions, total_cost_basis, unrealized_pnl, total_return_pct,
         benchmark_value, snapshot_source, positions_detail, created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (snapshot_date, snapshot_source) DO UPDATE SET
            snapshot_id = EXCLUDED.snapshot_id,
            total_value = EXCLUDED.total_value,
            cash = EXCLUDED.cash,
            positions_value = EXCLUDED.positions_value,
            n_positions = EXCLUDED.n_positions,
            total_cost_basis = EXCLUDED.total_cost_basis,
            unrealized_pnl = EXCLUDED.unrealized_pnl,
            total_return_pct = EXCLUDED.total_return_pct,
            benchmark_value = EXCLUDED.benchmark_value,
            positions_detail = EXCLUDED.positions_detail,
            created_at = EXCLUDED.created_at
    """, [
        snapshot_id,
        today,
        round(total_value, 2),
        round(portfolio.get("cash", 0), 2),
        round(positions_value, 2),
        len(portfolio.get("positions", [])),
        round(total_cost_basis, 2),
        round(unrealized_pnl, 2),
        round(pnl.get("total_return_pct", 0), 4),
        benchmark_price,
        source,
        json.dumps(positions_detail),
        datetime.now().isoformat(),
    ])
    con.close()
    print(f"  Portfolio snapshot saved: ${total_value:,.2f} ({len(positions_detail)} positions)")


def save_portfolio_state(portfolio: dict) -> None:
    """Save updated portfolio state (routes to Postgres or JSON via state helper)."""
    from src.db.state import save_portfolio_state as _save
    _save(portfolio)
    print(f"Portfolio state saved ({len(portfolio['positions'])} positions, ${portfolio['cash']:,.2f} cash)")
