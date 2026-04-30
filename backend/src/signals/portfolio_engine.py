"""Portfolio engine: position sizing, constraint checks, and trade proposal generation."""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection


# Map brokerage tickers to our universe tickers where they differ
_TICKER_MAP = {
    "GOOG": "GOOGL",   # Wealthsimple uses Class C; our universe tracks Class A
}


def _extract_ticker(ticker_val) -> str:
    """Normalize a ticker value that may be a string or a SnapTrade symbol dict."""
    if isinstance(ticker_val, str):
        t = ticker_val.split(".")[0] if "." in ticker_val else ticker_val
    elif isinstance(ticker_val, dict):
        # SnapTrade symbol object: {"symbol": "GOOG", "raw_symbol": "GOOG", ...}
        raw = ticker_val.get("symbol") or ticker_val.get("raw_symbol") or ""
        t = str(raw).split(".")[0] if raw else str(ticker_val)
    else:
        t = str(ticker_val)
    return _TICKER_MAP.get(t, t)


def load_portfolio_state() -> dict:
    """Load the current portfolio state from JSON, normalizing ticker values."""
    with open(settings.paths.portfolio_state_path) as f:
        portfolio = json.load(f)
    for pos in portfolio.get("positions", []):
        pos["ticker"] = _extract_ticker(pos.get("ticker", ""))
    return portfolio


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Get latest prices for tickers from DuckDB."""
    con = get_connection()
    result = con.execute("""
        WITH latest AS (
            SELECT ticker, adj_close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM prices WHERE ticker = ANY($1) AND adj_close > 0
        )
        SELECT ticker, adj_close FROM latest WHERE rn = 1
    """, [tickers]).fetchdf()
    con.close()
    return dict(zip(result["ticker"], result["adj_close"]))


def compute_portfolio_weights(portfolio: dict, prices: dict) -> dict:
    """Compute current portfolio weights from positions and prices."""
    positions_value = {}
    for pos in portfolio["positions"]:
        ticker = pos["ticker"]
        if ticker in prices:
            positions_value[ticker] = pos["shares"] * prices[ticker]

    total_value = sum(positions_value.values()) + portfolio["cash"]
    if total_value == 0:
        return {}

    return {t: v / total_value for t, v in positions_value.items()}


def compute_portfolio_value(portfolio: dict, prices: dict) -> float:
    """Compute total portfolio market value."""
    pos_value = sum(
        pos["shares"] * prices.get(pos["ticker"], 0)
        for pos in portfolio["positions"]
    )
    return pos_value + portfolio["cash"]


def check_constraints(
    signal: dict,
    current_weights: dict[str, float],
    portfolio: dict,
    prices: dict,
    universe: pd.DataFrame,
    adaptive_params: dict | None = None,
) -> dict:
    """Check if a proposed trade violates any risk constraints.

    Returns dict with: passed (bool), violations (list of strings)
    """
    violations = []
    ticker = signal["ticker"]
    target_weight = signal["target_weight"]

    # Max single position weight
    if target_weight > settings.strategy.max_single_position_weight:
        violations.append(
            f"Position weight {target_weight:.1%} exceeds max {settings.strategy.max_single_position_weight:.1%}"
        )

    # Min position size
    if 0 < target_weight < settings.strategy.min_position_size_pct:
        violations.append(
            f"Position weight {target_weight:.1%} below minimum {settings.strategy.min_position_size_pct:.1%}"
        )

    # Sub-sector concentration
    sub_sector = universe.loc[universe["ticker"] == ticker, "sub_sector"]
    if not sub_sector.empty:
        sector = sub_sector.iloc[0]
        sector_tickers = universe[universe["sub_sector"] == sector]["ticker"].tolist()
        sector_weight = sum(current_weights.get(t, 0) for t in sector_tickers)

        # Add the proposed change
        old_weight = current_weights.get(ticker, 0)
        new_sector_weight = sector_weight - old_weight + target_weight
        max_sector = settings.strategy.max_subsector_weight.get(sector, 0.35)

        sector_cap_adj = (adaptive_params or {}).get("sector_cap_adjustments", {})
        if sector in sector_cap_adj:
            max_sector *= sector_cap_adj[sector]

        if new_sector_weight > max_sector:
            violations.append(
                f"Sub-sector '{sector}' would reach {new_sector_weight:.1%}, exceeds max {max_sector:.1%}"
            )

    # Position count
    n_positions = len([w for w in current_weights.values() if w > 0])
    if signal["action"] == "BUY" and n_positions >= settings.strategy.max_positions:
        violations.append(f"Already at max positions ({settings.strategy.max_positions})")

    # Cash check for buys
    if signal["action"] in ("BUY", "ADD"):
        portfolio_value = compute_portfolio_value(portfolio, prices)
        required_cash = target_weight * portfolio_value - current_weights.get(ticker, 0) * portfolio_value
        if required_cash > portfolio["cash"]:
            violations.append(
                f"Insufficient cash: need ${required_cash:,.0f}, have ${portfolio['cash']:,.0f}"
            )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
    }


def build_trade_proposals(
    signals: list[dict],
    portfolio: dict,
    prices: dict,
    universe: pd.DataFrame,
    adaptive_params: dict | None = None,
) -> list[dict]:
    """Convert signals into formal trade proposals with constraint checks.

    Only includes actionable signals (not HOLD).
    """
    current_weights = compute_portfolio_weights(portfolio, prices)
    portfolio_value = compute_portfolio_value(portfolio, prices)

    proposals = []
    for signal in signals:
        if signal["action"] == "HOLD":
            continue

        ticker = signal["ticker"]
        constraint_result = check_constraints(
            signal, current_weights, portfolio, prices, universe,
            adaptive_params=adaptive_params,
        )

        # Compute shares to trade
        current_value = current_weights.get(ticker, 0) * portfolio_value
        target_value = signal["target_weight"] * portfolio_value
        delta_value = target_value - current_value
        price = prices.get(ticker, 0)

        if price > 0:
            shares = int(delta_value / price)
        else:
            shares = 0

        # Skip proposals with 0 shares (e.g. price too high for target allocation)
        if abs(shares) == 0:
            continue

        proposal = {
            "proposal_id": str(uuid.uuid4())[:8],
            "created_at": datetime.now().isoformat(),
            "ticker": ticker,
            "action": signal["action"],
            "shares": abs(shares),
            "estimated_value": abs(delta_value),
            "current_weight": signal["current_weight"],
            "target_weight": signal["target_weight"],
            "signal_data": signal.get("signal_data", {}),
            "constraint_check": constraint_result,
            "reason": signal["reason"],
            "status": "PENDING",
            "gate_note": signal.get("gate_note"),
        }
        proposals.append(proposal)

    # Cap BUY proposals by available cash — prioritize by composite score
    cash = portfolio.get("cash", 0)
    buys = [p for p in proposals if p["action"] == "BUY"]
    non_buys = [p for p in proposals if p["action"] != "BUY"]

    # Sort buys by composite score descending (best signals first)
    buys.sort(
        key=lambda p: p.get("signal_data", {}).get("composite_score", 0),
        reverse=True,
    )

    capped_buys = []
    remaining_cash = cash
    for p in buys:
        if p["estimated_value"] <= remaining_cash:
            capped_buys.append(p)
            remaining_cash -= p["estimated_value"]
        # else: skip — not enough cash

    return non_buys + capped_buys


def store_proposals(proposals: list[dict]) -> None:
    """Persist trade proposals to DuckDB."""
    if not proposals:
        return

    con = get_connection()
    for p in proposals:
        con.execute("""
            INSERT INTO trade_proposals
            (proposal_id, run_id, created_at, ticker, action, shares,
             signal_data, constraint_check, status, human_decision, human_notes, reason)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """, [
            p["proposal_id"],
            p.get("run_id"),
            p["created_at"],
            p["ticker"],
            p["action"],
            p["shares"],
            json.dumps(p["signal_data"]) if isinstance(p["signal_data"], dict) else p["signal_data"],
            json.dumps(p["constraint_check"]) if isinstance(p["constraint_check"], dict) else p["constraint_check"],
            p["status"],
            p.get("human_decision"),
            p.get("human_notes"),
            p.get("reason"),
        ])
    con.close()
    print(f"Stored {len(proposals)} trade proposals")
