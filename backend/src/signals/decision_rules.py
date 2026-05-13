"""Decision rules engine: value-investing framework with good-stock filter.

Key principles:
1. Evaluate fundamentals/quality FIRST to determine if a stock is "good."
2. Price movement is a TIMING signal, not a quality signal.
3. Good stock + price dip = better buy opportunity.
4. Good stock + price rise = watch/buy less (avoid chasing).
5. Bad stock + price dip ≠ buy signal.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection


def get_recent_trades(lookback_days: int = 60) -> list[dict]:
    """Query trade_executions for recently executed trades."""
    try:
        con = get_connection()
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        rows = con.execute("""
            SELECT ticker, action, executed_at, shares
            FROM trade_executions
            WHERE executed_at >= CAST($1 AS TIMESTAMP)
              AND success = TRUE
            ORDER BY executed_at DESC
        """, [cutoff]).fetchall()
        con.close()
        return [
            {"ticker": r[0], "action": r[1], "executed_at": r[2], "shares": r[3]}
            for r in rows
        ]
    except Exception:
        return []


def _build_trade_recency(recent_trades: list[dict]) -> dict[str, dict]:
    """Build a per-ticker recency map from recent trade history."""
    now = datetime.now()
    recency: dict[str, dict] = {}

    for trade in recent_trades:
        ticker = trade["ticker"]
        if ticker not in recency:
            recency[ticker] = {
                "last_buy_days_ago": None,
                "last_sell_days_ago": None,
                "trade_count_30d": 0,
            }

        executed = trade["executed_at"]
        if isinstance(executed, str):
            executed = datetime.fromisoformat(executed)
        days_ago = (now - executed).days

        action = trade["action"].upper()
        if action in ("BUY", "ADD"):
            if recency[ticker]["last_buy_days_ago"] is None or days_ago < recency[ticker]["last_buy_days_ago"]:
                recency[ticker]["last_buy_days_ago"] = days_ago
        elif action in ("SELL", "TRIM"):
            if recency[ticker]["last_sell_days_ago"] is None or days_ago < recency[ticker]["last_sell_days_ago"]:
                recency[ticker]["last_sell_days_ago"] = days_ago

        if days_ago <= 30:
            recency[ticker]["trade_count_30d"] += 1

    return recency


def _chase_weight_multiplier(recent_change: float, threshold: float, mode: str) -> float:
    """Position size multiplier based on chase risk.

    Returns 1.0 (full), 0.0 (skip), or a value between for gradient mode.
    """
    if mode == "allow":
        return 1.0
    if recent_change <= threshold:
        return 1.0
    if mode == "strict":
        return 0.0
    excess = recent_change - threshold
    return max(0.0, 1.0 - (excess / 0.10))


def generate_signals(
    scores: pd.DataFrame,
    current_holdings: dict[str, float],
    prior_deciles: dict[str, int],
    portfolio_drawdown: float = 0.0,
    adaptive_params: dict | None = None,
    recent_trades: list[dict] | None = None,
    risk_level: int = 3,
) -> list[dict]:
    """Generate trade signals with value-investing framework.

    Decision flow:
    1. Load quality assessment (is_good_stock) from scores.
    2. For BUY candidates: ONLY consider stocks that pass the good-stock filter.
    3. Among good stocks: price dip improves buy ranking, price rise → WATCH.
    4. Bad stocks with price dips do NOT become buy candidates.
    """
    from src.signals.risk_profile import get_risk_adjustments
    risk = get_risk_adjustments(risk_level)

    if adaptive_params:
        min_decile_change = adaptive_params.get("min_decile_change", risk["min_decile_change"])
        max_new = adaptive_params.get("max_new_positions_per_run", settings.strategy.max_new_positions_per_run)
        max_total_trades = adaptive_params.get("max_trades_per_run", settings.strategy.max_trades_per_run)
        position_scalar = adaptive_params.get("position_size_scalar", risk["position_size_scalar"])
        dd_schedule = adaptive_params.get("drawdown_schedule")
    else:
        min_decile_change = risk["min_decile_change"]
        max_new = settings.strategy.max_new_positions_per_run
        max_total_trades = settings.strategy.max_trades_per_run
        position_scalar = risk["position_size_scalar"]
        dd_schedule = None

    buy_min_decile = risk["buy_min_decile"]
    chase_threshold = risk["chase_threshold"]
    chase_mode = risk.get("chase_mode", "gradient")
    max_single_pos = risk["max_single_position"]
    allowed_risk_tiers = risk.get("allowed_risk_tiers", ["standard", "moderate_risk", "high_risk"])

    # Load universe risk tiers for filtering
    try:
        _universe_df = pd.read_csv(settings.paths.universe_path)
        _ticker_risk_tiers = dict(zip(_universe_df["ticker"], _universe_df.get("risk_tier", "standard")))
    except Exception:
        _ticker_risk_tiers = {}
    dd_alert = risk["drawdown_alert"]
    dd_halt = risk["drawdown_halt"]

    signals = []
    score_map = {}

    for _, row in scores.iterrows():
        ticker = row["ticker"]
        decile = int(row["score_decile"])
        _ig = row.get("is_good_stock", False)
        is_good = bool(_ig) if pd.notna(_ig) else False
        recent_price_change = row.get("recent_price_change", 0.0)
        price_dip_score = row.get("price_dip_score", 0.0)
        _qs = row.get("quality_score", 0.0)
        quality_score = float(_qs) if pd.notna(_qs) else 0.0
        per_ratio = row.get("per_ratio")
        quality_reasons = row.get("quality_reasons", [])

        score_map[ticker] = {
            "decile": decile,
            "composite_score": row["composite_score"],
            "is_good_stock": is_good,
            "quality_score": quality_score if pd.notna(quality_score) else 0.0,
            "recent_price_change": float(recent_price_change) if pd.notna(recent_price_change) else 0.0,
            "price_dip_score": float(price_dip_score) if pd.notna(price_dip_score) else 0.0,
            "per_ratio": float(per_ratio) if pd.notna(per_ratio) else None,
            "quality_reasons": quality_reasons if isinstance(quality_reasons, list) else [],
            "factors": {
                "momentum_12m1m": row.get("momentum_12m1m"),
                "eps_growth_yoy": row.get("eps_growth_yoy"),
                "revenue_growth_yoy": row.get("revenue_growth_yoy"),
                "gross_margin_trend": row.get("gross_margin_trend"),
                "relative_valuation": row.get("relative_valuation"),
            },
        }

    # Check earnings timing for all scored tickers
    earnings_flags: dict[str, dict] = {}
    try:
        from src.ingest.earnings_calendar import get_upcoming_earnings
        all_tickers = list(score_map.keys())
        upcoming = get_upcoming_earnings(all_tickers, days_ahead=14)
        for t, e in upcoming.items():
            earnings_flags[t] = e
    except Exception:
        pass

    # Penalize composite scores for stocks near earnings (affects ranking)
    for ticker, einfo in earnings_flags.items():
        if ticker in score_map:
            days_until = einfo["days_until"]
            if days_until <= 2:
                score_map[ticker]["composite_score"] *= 0.7
            elif days_until <= 7:
                score_map[ticker]["composite_score"] *= 0.85

    # Check drawdown gates
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

    # Anti-whipsaw
    min_hold = settings.strategy.min_holding_days
    cooldown_window = min_hold * 2
    trade_recency = _build_trade_recency(recent_trades or [])

    # --- Process current holdings ---
    sell_signals = []
    hold_signals = []

    for ticker, current_weight in current_holdings.items():
        info = score_map.get(ticker, {})
        decile = info.get("decile", 5)
        prior_decile = prior_deciles.get(ticker, 5)
        decile_change = decile - prior_decile
        is_good = info.get("is_good_stock", False)
        recent_change = info.get("recent_price_change", 0.0)

        recency = trade_recency.get(ticker, {})
        last_buy_days = recency.get("last_buy_days_ago")
        holding_protected = False
        effective_min_decile = min_decile_change

        if last_buy_days is not None and last_buy_days < min_hold:
            holding_protected = True
        elif last_buy_days is not None and last_buy_days < cooldown_window:
            progress = (last_buy_days - min_hold) / max(cooldown_window - min_hold, 1)
            multiplier = 2.0 - progress
            effective_min_decile = max(min_decile_change, int(min_decile_change * multiplier))

        if holding_protected:
            hold_signals.append({
                "ticker": ticker,
                "action": "HOLD",
                "reason": f"Holding period: bought {last_buy_days}d ago (min hold {min_hold}d). Decile {decile} (was {prior_decile})",
                "current_weight": current_weight,
                "target_weight": current_weight,
                "score_decile": decile,
                "prior_decile": prior_decile,
                "signal_data": info,
                "gate_note": gate_note,
            })
        elif is_good:
            # ── GOOD STOCK: high bar to sell ──
            # Value investing: don't sell winners because price dropped.
            # A good stock at a low composite decile means momentum reversed
            # (price fell) — that's a dip opportunity, not a sell signal.
            # Only sell when quality itself deteriorates (is_good becomes False).
            if decile >= buy_min_decile and decile_change >= min_decile_change:
                if not buys_blocked:
                    max_w = max_single_pos
                    if recent_change < -0.02:
                        add_multiplier = 1.0 + (0.7 * effective_scalar)
                        reason = f"Strong add (dip opportunity): decile {decile}, price down {recent_change:.1%} — good stock at better price"
                    elif recent_change > chase_threshold:
                        chase_mult = _chase_weight_multiplier(recent_change, chase_threshold, chase_mode)
                        if chase_mult <= 0.0:
                            hold_signals.append({
                                "ticker": ticker,
                                "action": "HOLD",
                                "reason": f"Watch (avoid chase): decile {decile} but price already up {recent_change:.1%} — wait for better entry",
                                "current_weight": current_weight,
                                "target_weight": current_weight,
                                "score_decile": decile,
                                "prior_decile": prior_decile,
                                "signal_data": info,
                                "gate_note": gate_note,
                            })
                            continue
                        else:
                            add_multiplier = 1.0 + (0.5 * effective_scalar * chase_mult)
                            reason = f"Cautious add (chase {1.0 - chase_mult:.0%} reduced): decile {decile}, price up {recent_change:.1%}"
                    else:
                        add_multiplier = 1.0 + (0.5 * effective_scalar)
                        reason = f"Strong hold/add: decile rose to {decile} (was {prior_decile}), size {effective_scalar:.0%}"

                    target = min(current_weight * add_multiplier, max_w)
                    sell_signals.append({
                        "ticker": ticker,
                        "action": "ADD",
                        "reason": reason,
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
                        "reason": f"Good stock hold (buys blocked): decile {decile}, quality {quality_score:.2f}",
                        "current_weight": current_weight,
                        "target_weight": current_weight,
                        "score_decile": decile,
                        "prior_decile": prior_decile,
                        "signal_data": info,
                        "gate_note": gate_note,
                    })
            else:
                reason = f"Hold (good stock): decile {decile} (was {prior_decile}), quality {quality_score:.2f}"
                if recent_change < -0.05:
                    reason += f" — dipped {recent_change:.1%}, consider adding"
                hold_signals.append({
                    "ticker": ticker,
                    "action": "HOLD",
                    "reason": reason,
                    "current_weight": current_weight,
                    "target_weight": current_weight,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": info,
                    "gate_note": gate_note,
                })
        else:
            # ── BAD STOCK: standard sell discipline ──
            # Quality has genuinely deteriorated — sell/trim as warranted.
            if decile <= 2 and abs(decile_change) >= effective_min_decile:
                sell_signals.append({
                    "ticker": ticker,
                    "action": "SELL",
                    "reason": f"Sell (quality failed + low rank): decile {decile} (was {prior_decile}), quality {quality_score:.2f}",
                    "current_weight": current_weight,
                    "target_weight": 0.0,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": info,
                    "gate_note": gate_note,
                })
            elif decile <= 4 and abs(decile_change) >= effective_min_decile:
                target = max(current_weight * 0.5, 0)
                sell_signals.append({
                    "ticker": ticker,
                    "action": "TRIM",
                    "reason": f"Trim (quality failed): decile {decile} (was {prior_decile}), quality {quality_score:.2f}",
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
                    "reason": f"Hold: decile {decile} (was {prior_decile}), change {abs(decile_change)} < threshold {effective_min_decile}",
                    "current_weight": current_weight,
                    "target_weight": current_weight,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": info,
                    "gate_note": gate_note,
                })

    # --- Process non-holdings: buy candidates ---
    # CRITICAL: Only consider stocks that pass the good-stock filter.
    # Price dip on a bad stock does NOT create a buy signal.
    buy_signals = []
    if not buys_blocked and not all_blocked:
        for _, row in scores.iterrows():
            ticker = row["ticker"]
            if ticker in current_holdings:
                continue

            info = score_map.get(ticker, {})
            decile = int(row["score_decile"])
            prior_decile = prior_deciles.get(ticker, 5)
            decile_change = decile - prior_decile
            is_good = info.get("is_good_stock", False)
            recent_change = info.get("recent_price_change", 0.0)

            # GATE: Must be a good stock to be a buy candidate
            if not is_good:
                continue

            # GATE: Risk tier must be allowed for this risk level
            ticker_tier = _ticker_risk_tiers.get(ticker, "standard")
            if ticker_tier not in allowed_risk_tiers:
                continue

            # Anti-whipsaw
            recency = trade_recency.get(ticker, {})
            last_sell_days = recency.get("last_sell_days_ago")
            if last_sell_days is not None and last_sell_days < min_hold:
                continue

            trade_count = recency.get("trade_count_30d", 0)
            if trade_count >= 3:
                continue

            if decile >= buy_min_decile and decile_change >= min_decile_change:
                base_weight = 0.06

                if recent_change < -0.02:
                    dip_bonus = min(abs(recent_change) * 0.5, 0.03)
                    scaled_weight = round((base_weight + dip_bonus) * effective_scalar, 4)
                    reason = (f"Buy opportunity (dip): decile {decile}, price down {recent_change:.1%} — "
                              f"good stock at discounted price")
                elif recent_change > chase_threshold:
                    chase_mult = _chase_weight_multiplier(recent_change, chase_threshold, chase_mode)
                    if chase_mult <= 0.0:
                        continue
                    scaled_weight = round(base_weight * effective_scalar * chase_mult, 4)
                    reason = (f"Buy candidate (chase-reduced {chase_mult:.0%}): decile {decile}, "
                              f"price up {recent_change:.1%}")
                else:
                    scaled_weight = round(base_weight * effective_scalar, 4)
                    reason = f"Buy candidate: decile {decile} (was {prior_decile}, change +{decile_change}), size {effective_scalar:.0%}"

                risk_flags = []
                if ticker in earnings_flags:
                    days_until = earnings_flags[ticker]["days_until"]
                    if days_until <= 2:
                        scaled_weight = round(scaled_weight * 0.5, 4)
                        risk_flags.append(f"EARNINGS IN {days_until}d — binary event risk, position halved")
                    elif days_until <= 7:
                        scaled_weight = round(scaled_weight * 0.75, 4)
                        risk_flags.append(f"Earnings in {days_until}d — position reduced 25%")

                buy_signals.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "reason": reason,
                    "current_weight": 0.0,
                    "target_weight": scaled_weight,
                    "score_decile": decile,
                    "prior_decile": prior_decile,
                    "signal_data": info,
                    "gate_note": gate_note,
                    "risk_flags": risk_flags,
                })

    # --- Vol-adjusted position sizing for buy signals ---
    if buy_signals and adaptive_params:
        try:
            from src.learning.adaptive import compute_vol_adjusted_weights
            base_targets = {s["ticker"]: s["target_weight"] for s in buy_signals}
            adjusted = compute_vol_adjusted_weights(base_targets, position_scalar)
            for s in buy_signals:
                if s["ticker"] in adjusted:
                    s["target_weight"] = adjusted[s["ticker"]]
        except Exception:
            pass

    # --- Correlation-aware dedup and penalty for buy signals ---
    if buy_signals and adaptive_params:
        try:
            from src.learning.adaptive import compute_correlation_penalties
            candidate_tickers = [s["ticker"] for s in buy_signals]
            holding_tickers = list(current_holdings.keys())
            corr_penalties, correlated_pairs = compute_correlation_penalties(
                candidate_tickers, holding_tickers,
            )

            for t1, t2, corr_val in correlated_pairs:
                s1 = next((s for s in buy_signals if s["ticker"] == t1), None)
                s2 = next((s for s in buy_signals if s["ticker"] == t2), None)
                if s1 and s2:
                    score1 = s1["signal_data"].get("composite_score", 0)
                    score2 = s2["signal_data"].get("composite_score", 0)
                    loser = s2 if score1 >= score2 else s1
                    buy_signals = [s for s in buy_signals if s["ticker"] != loser["ticker"]]

            for s in buy_signals:
                penalty = corr_penalties.get(s["ticker"], 1.0)
                if penalty < 1.0:
                    s["target_weight"] = round(s["target_weight"] * penalty, 4)
                    s["signal_data"]["correlation_penalty"] = penalty
                    s["reason"] += f" [corr penalty {penalty:.0%}]"
        except Exception:
            pass

    # --- Rotation: find weak holdings to fund stronger buys ---
    rotate_signals = []
    if buy_signals and not buys_blocked:
        buy_signals.sort(
            key=lambda s: s["signal_data"].get("composite_score", 0),
            reverse=True,
        )

        selling_tickers = {s["ticker"] for s in sell_signals}
        weak_holdings = []
        for ticker, current_weight in current_holdings.items():
            if ticker in selling_tickers:
                continue
            recency = trade_recency.get(ticker, {})
            last_buy_days = recency.get("last_buy_days_ago")
            if last_buy_days is not None and last_buy_days < cooldown_window:
                continue
            info = score_map.get(ticker, {})
            decile = info.get("decile", 5)
            is_good = info.get("is_good_stock", True)
            if decile <= 4 and not is_good:
                weak_holdings.append({
                    "ticker": ticker,
                    "decile": decile,
                    "weight": current_weight,
                    "composite_score": info.get("composite_score", 0),
                })

        weak_holdings.sort(key=lambda h: h["composite_score"])

        for weak in weak_holdings:
            if not buy_signals:
                break
            best_buy = buy_signals[0]
            best_buy_score = best_buy["signal_data"].get("composite_score", 0)
            if best_buy_score <= weak["composite_score"] + 0.1:
                break

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
            buy_signals.pop(0)

    # Cap new BUY signals
    buy_signals.sort(
        key=lambda s: s["signal_data"].get("composite_score", 0),
        reverse=True,
    )
    buy_signals = buy_signals[:max_new]

    # Assemble final signals
    actionable = sell_signals + rotate_signals + buy_signals
    actionable = actionable[:max_total_trades]

    signals = actionable + hold_signals
    return signals


def filter_actionable_signals(signals: list[dict]) -> list[dict]:
    """Filter to only signals that require action (not HOLD)."""
    return [s for s in signals if s["action"] != "HOLD"]
