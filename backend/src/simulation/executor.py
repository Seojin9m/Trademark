"""Simulated trade execution: apply approved trades to portfolio state."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings


def execute_trade(portfolio: dict, proposal: dict, current_price: float) -> dict:
    """Apply a single approved trade to the portfolio state.

    Returns updated portfolio dict.
    """
    ticker = proposal["ticker"]
    action = proposal["action"]
    shares = proposal["shares"]

    # Find existing position
    existing = None
    for i, pos in enumerate(portfolio["positions"]):
        if pos["ticker"] == ticker:
            existing = i
            break

    if action in ("BUY", "ADD"):
        cost = shares * current_price
        if cost > portfolio["cash"]:
            print(f"  WARNING: Insufficient cash for {action} {shares} {ticker}")
            shares = int(portfolio["cash"] / current_price)
            cost = shares * current_price

        if shares <= 0:
            return portfolio

        portfolio["cash"] -= cost

        if existing is not None:
            # Update existing position (average cost basis)
            pos = portfolio["positions"][existing]
            total_shares = pos["shares"] + shares
            total_cost = (pos["shares"] * pos["cost_basis_per_share"]) + cost
            pos["shares"] = total_shares
            pos["cost_basis_per_share"] = total_cost / total_shares
        else:
            # New position
            portfolio["positions"].append({
                "ticker": ticker,
                "shares": shares,
                "cost_basis_per_share": current_price,
                "date_acquired": datetime.now().strftime("%Y-%m-%d"),
            })

    elif action in ("SELL", "TRIM"):
        if existing is None:
            print(f"  WARNING: Cannot {action} {ticker}, not in portfolio")
            return portfolio

        pos = portfolio["positions"][existing]
        sell_shares = min(shares, pos["shares"])
        proceeds = sell_shares * current_price

        portfolio["cash"] += proceeds
        pos["shares"] -= sell_shares

        if pos["shares"] <= 0:
            portfolio["positions"].pop(existing)

    portfolio["as_of_date"] = datetime.now().strftime("%Y-%m-%d")
    return portfolio


def execute_proposals(
    portfolio: dict,
    proposals: list[dict],
    prices: dict[str, float],
) -> tuple[dict, list[dict]]:
    """Execute all approved proposals and return updated portfolio + execution log."""
    execution_log = []

    for p in proposals:
        if p.get("status") != "APPROVED":
            continue

        ticker = p["ticker"]
        price = prices.get(ticker, 0)
        if price <= 0:
            execution_log.append({**p, "executed": False, "reason": "No price available"})
            continue

        portfolio = execute_trade(portfolio, p, price)
        execution_log.append({
            **p,
            "executed": True,
            "execution_price": price,
            "execution_time": datetime.now().isoformat(),
        })
        print(f"  Executed: {p['action']} {p['shares']} {ticker} @ ${price:.2f}")

    return portfolio, execution_log


def save_portfolio_state(portfolio: dict) -> None:
    """Save updated portfolio state to JSON."""
    # Remove internal comment field if present
    portfolio.pop("_comment", None)

    with open(settings.paths.portfolio_state_path, "w") as f:
        json.dump(portfolio, f, indent=2)

    print(f"Portfolio state saved ({len(portfolio['positions'])} positions, ${portfolio['cash']:,.2f} cash)")
