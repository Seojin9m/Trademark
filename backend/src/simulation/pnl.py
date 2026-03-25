"""P&L tracking: mark-to-market, unrealized/realized gains."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings


def compute_pnl(portfolio: dict, prices: dict[str, float]) -> dict:
    """Compute P&L for the current portfolio.

    Returns dict with per-position and total P&L.
    """
    positions_pnl = []
    total_market_value = 0
    total_cost_basis = 0
    total_unrealized = 0

    for pos in portfolio["positions"]:
        ticker = pos["ticker"]
        shares = pos["shares"]
        cost_basis = pos["cost_basis_per_share"]
        current_price = prices.get(ticker, 0)

        market_value = shares * current_price
        cost_value = shares * cost_basis
        unrealized_pnl = market_value - cost_value
        unrealized_pct = (current_price / cost_basis - 1) if cost_basis > 0 else 0

        positions_pnl.append({
            "ticker": ticker,
            "shares": shares,
            "cost_basis": cost_basis,
            "current_price": current_price,
            "market_value": market_value,
            "cost_value": cost_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pct": unrealized_pct,
        })

        total_market_value += market_value
        total_cost_basis += cost_value
        total_unrealized += unrealized_pnl

    total_portfolio_value = total_market_value + portfolio["cash"]

    return {
        "as_of_date": portfolio["as_of_date"],
        "positions": positions_pnl,
        "cash": portfolio["cash"],
        "total_market_value": total_market_value,
        "total_cost_basis": total_cost_basis,
        "total_unrealized_pnl": total_unrealized,
        "total_portfolio_value": total_portfolio_value,
        "total_return_pct": (total_portfolio_value / (total_cost_basis + portfolio["cash"]) - 1)
            if (total_cost_basis + portfolio["cash"]) > 0 else 0,
    }


def print_pnl_report(pnl: dict) -> None:
    """Pretty-print the P&L report."""
    print("=" * 70)
    print("PORTFOLIO P&L REPORT")
    print(f"As of: {pnl['as_of_date']}")
    print("=" * 70)

    print(f"\n{'Ticker':<8} {'Shares':>6} {'Cost':>8} {'Price':>8} {'Value':>10} {'P&L':>10} {'P&L%':>7}")
    print("-" * 70)

    for pos in sorted(pnl["positions"], key=lambda x: x["market_value"], reverse=True):
        print(
            f"{pos['ticker']:<8} {pos['shares']:>6} "
            f"${pos['cost_basis']:>7.2f} ${pos['current_price']:>7.2f} "
            f"${pos['market_value']:>9,.2f} "
            f"${pos['unrealized_pnl']:>9,.2f} "
            f"{pos['unrealized_pct']:>6.1%}"
        )

    print("-" * 70)
    print(f"{'Cash':<8} {'':>6} {'':>8} {'':>8} ${pnl['cash']:>9,.2f}")
    print(f"{'TOTAL':<8} {'':>6} {'':>8} {'':>8} ${pnl['total_portfolio_value']:>9,.2f} "
          f"${pnl['total_unrealized_pnl']:>9,.2f} {pnl['total_return_pct']:>6.1%}")
    print("=" * 70)
