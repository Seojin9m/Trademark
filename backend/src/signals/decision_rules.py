"""Decision rules engine: generate hold/buy/sell/trim/add signals from scores."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings


def generate_signals(
    scores: pd.DataFrame,
    current_holdings: dict[str, float],
    prior_deciles: dict[str, int],
    portfolio_drawdown: float = 0.0,
    adaptive_params: dict | None = None,
) -> list[dict]:
    """Generate trade signals from ranked scores and current holdings.

    Args:
        scores: Today's ranked scores (from ranker.py)
        current_holdings: {ticker: current_weight_pct}
        prior_deciles: {ticker: prior_score_decile}
        portfolio_drawdown: Current portfolio drawdown from peak (negative number)
        adaptive_params: Optional dict from adaptive constraint tuner overriding defaults

    Returns:
        List of signal dicts with: ticker, action, reason, score details
    """
    # Use adaptive parameters if available, otherwise fall back to settings
    if adaptive_params:
        min_decile_change = adaptive_params.get("min_decile_change", settings.strategy.min_decile_change_to_trade)
        max_new = adaptive_params.get("max_new_positions_per_run", settings.strategy.max_new_positions_per_run)
        max_total_trades = adaptive_params.get("max_trades_per_run", settings.strategy.max_trades_per_run)
        position_scalar = adaptive_params.get("position_size_scalar", 1.0)
        dd_schedule = adaptive_params.get("drawdown_schedule")
    else:
        min_decile_change = settings.strategy.min_decile_change_to_trade
        max_new = settings.strategy.max_new_positions_per_run
        max_total_trades = settings.strategy.max_trades_per_run
        position_scalar = 1.0
        dd_schedule = None

    dd_alert = settings.strategy.max_portfolio_drawdown_alert
    dd_halt = settings.strategy.max_portfolio_drawdown_halt

    signals = []
    score_map = {}

    for _, row in scores.iterrows():
        ticker = row["ticker"]
        decile = int(row["score_decile"])
        score_map[ticker] = {
            "decile": decile,
            "composite_score": row["composite_score"],
            "factors": {
                "momentum_12m1m": row.get("momentum_12m1m"),
                "eps_growth_yoy": row.get("eps_growth_yoy"),
                "revenue_growth_yoy": row.get("revenue_growth_yoy"),
                "gross_margin_trend": row.get("gross_margin_trend"),
                "relative_valuation": row.get("relative_valuation"),
            },
        }

    # Check drawdown gates — use continuous scaling if adaptive params available
    if dd_schedule:
        from src.learning.adaptive import drawdown_size_scalar
        dd_scalar = drawdown_size_scalar(portfolio_drawdown, dd_schedule)
        buys_blocked = dd_scalar <= 0.0
        all_blocked = portfolio_drawdown < dd_halt
        effective_scalar = position_scalar * dd_scalar
    else:
        buys_blocked = portfolio_drawdown < dd_alert
        all_blocked = portfolio_drawdown < dd_halt
        effective_scalar = position_scalar

    if buys_blocked:
        gate_note = f"Drawdown gate active ({portfolio_drawdown:.1%}): new buys blocked"
    elif effective_scalar < 1.0:
        gate_note = f"Position sizing reduced to {effective_scalar:.0%} (drawdown: {portfolio_drawdown:.1%}, vol scalar: {position_scalar:.0%})"
    else:
        gate_note = None

    # --- Process current holdings ---
    sell_signals = []
    hold_signals = []

    for ticker, current_weight in current_holdings.items():
        info = score_map.get(ticker, {})
        decile = info.get("decile", 5)
        # Default to 5 (neutral) so holdings need real score drops to trigger sells
        prior_decile = prior_deciles.get(ticker, 5)
        decile_change = decile - prior_decile

        if decile <= 2 and abs(decile_change) >= min_decile_change:
            sell_signals.append({
                "ticker": ticker,
                "action": "SELL",
                "reason": f"Strong sell: decile dropped to {decile} (was {prior_decile})",
                "current_weight": current_weight,
                "target_weight": 0.0,
                "score_decile": decile,
                "prior_decile": prior_decile,
                "signal_data": info,
                "gate_note": gate_note,
            })
        elif decile <= 4 and abs(decile_change) >= min_decile_change:
            target = max(current_weight * 0.5, 0)  # Trim 50%
            sell_signals.append({
                "ticker": ticker,
                "action": "TRIM",
                "reason": f"Sell signal: decile {decile} (was {prior_decile}), trim to {target:.1%}",
                "current_weight": current_weight,
                "target_weight": target,
                "score_decile": decile,
                "prior_decile": prior_decile,
                "signal_data": info,
                "gate_note": gate_note,
            })
        elif decile >= 9 and decile_change >= min_decile_change:
            if not buys_blocked:
                max_w = settings.strategy.max_single_position_weight
                add_multiplier = 1.0 + (0.5 * effective_scalar)  # Scale add aggressiveness
                target = min(current_weight * add_multiplier, max_w)
                sell_signals.append({
                    "ticker": ticker,
                    "action": "ADD",
                    "reason": f"Strong hold/add: decile rose to {decile} (was {prior_decile}), size {effective_scalar:.0%}",
                    "current_weight": current_weight,
                    "target_weight": target,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": info,
                    "gate_note": gate_note,
                })
        else:
            hold_signals.append({
                "ticker": ticker,
                "action": "HOLD",
                "reason": f"Hold: decile {decile} (was {prior_decile}), change {abs(decile_change)} < threshold {min_decile_change}",
                "current_weight": current_weight,
                "target_weight": current_weight,
                "score_decile": decile,
                "prior_decile": prior_decile,
                "signal_data": info,
                "gate_note": gate_note,
            })

    # --- Process non-holdings: buy candidates ---
    # BUY now requires decile change >= min_decile_change (same bar as sells)
    # Prior defaults to 5 (neutral) — ticker must have climbed to top decile
    buy_signals = []
    if not buys_blocked and not all_blocked:
        for _, row in scores.iterrows():
            ticker = row["ticker"]
            if ticker in current_holdings:
                continue

            decile = int(row["score_decile"])
            prior_decile = prior_deciles.get(ticker, 5)
            decile_change = decile - prior_decile

            if decile >= 9 and decile_change >= min_decile_change:
                base_weight = 0.06
                scaled_weight = round(base_weight * effective_scalar, 4)
                buy_signals.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "reason": f"Buy candidate: decile {decile} (was {prior_decile}, change +{decile_change}), size {effective_scalar:.0%}",
                    "current_weight": 0.0,
                    "target_weight": scaled_weight,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": score_map.get(ticker, {}),
                    "gate_note": gate_note,
                })

    # --- Rotation: find weak holdings to fund stronger buys ---
    # If we have buy candidates but limited cash, identify held positions
    # that are mediocre (decile 4-6) to potentially trim and rotate
    rotate_signals = []
    if buy_signals and not buys_blocked:
        # Sort buys by composite score (best first)
        buy_signals.sort(
            key=lambda s: s["signal_data"].get("composite_score", 0),
            reverse=True,
        )

        # Find held positions in the "weak zone" (decile <= 6, not already selling)
        selling_tickers = {s["ticker"] for s in sell_signals}
        weak_holdings = []
        for ticker, current_weight in current_holdings.items():
            if ticker in selling_tickers:
                continue
            info = score_map.get(ticker, {})
            decile = info.get("decile", 5)
            if decile <= 5:
                weak_holdings.append({
                    "ticker": ticker,
                    "decile": decile,
                    "weight": current_weight,
                    "composite_score": info.get("composite_score", 0),
                })

        # Sort weakest first
        weak_holdings.sort(key=lambda h: h["composite_score"])

        # Generate ROTATE signals for weak holdings (trim to fund better buys)
        for weak in weak_holdings:
            if not buy_signals:
                break
            # Only rotate if the best buy candidate is meaningfully better
            best_buy = buy_signals[0]
            best_buy_score = best_buy["signal_data"].get("composite_score", 0)
            if best_buy_score <= weak["composite_score"] + 0.1:
                break  # Not enough improvement to justify rotation

            target = max(weak["weight"] * 0.5, 0)
            prior_decile = prior_deciles.get(weak["ticker"], 5)
            rotate_signals.append({
                "ticker": weak["ticker"],
                "action": "TRIM",
                "reason": f"Rotation: decile {weak['decile']}, trimming to fund {best_buy['ticker']} (score {best_buy_score:.3f} vs {weak['composite_score']:.3f})",
                "current_weight": weak["weight"],
                "target_weight": target,
                "score_decile": weak["decile"],
                "prior_decile": prior_decile,
                "signal_data": score_map.get(weak["ticker"], {}),
                "gate_note": gate_note,
            })
            # This freed up capital for ~1 buy
            buy_signals.pop(0)

    # --- Cap new BUY signals ---
    buy_signals.sort(
        key=lambda s: s["signal_data"].get("composite_score", 0),
        reverse=True,
    )
    buy_signals = buy_signals[:max_new]

    # --- Assemble final signals with trade cap ---
    # Priority: sells > rotations > buys > holds
    actionable = sell_signals + rotate_signals + buy_signals
    actionable = actionable[:max_total_trades]

    signals = actionable + hold_signals
    return signals


def filter_actionable_signals(signals: list[dict]) -> list[dict]:
    """Filter to only signals that require action (not HOLD)."""
    return [s for s in signals if s["action"] != "HOLD"]
