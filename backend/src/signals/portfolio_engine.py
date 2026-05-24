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


def load_portfolio_state(user_id: str) -> dict:
    """Load the user's portfolio state, normalizing ticker values."""
    from src.db.state import load_portfolio_state as _load
    portfolio = _load(user_id=user_id)
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


def _effective_max_single_position(risk_level: int) -> float:
    """The position-weight cap used by constraint checks.

    The risk profile sets the *preferred* max per aggressiveness level
    (e.g. 0.12 for Growth, 0.15 for Aggressive). The global setting is a
    floor for the legacy single-user defaults. We take the larger of the two
    so a user on Growth isn't blocked by the global 10% when their profile
    explicitly allows 12%.
    """
    from src.signals.risk_profile import get_risk_adjustments
    risk = get_risk_adjustments(risk_level)
    return max(risk.get("max_single_position", 0.0), settings.strategy.max_single_position_weight)


def check_constraints(
    signal: dict,
    current_weights: dict[str, float],
    portfolio: dict,
    prices: dict,
    universe: pd.DataFrame,
    adaptive_params: dict | None = None,
    projected_cash: float | None = None,
    risk_level: int = 3,
) -> dict:
    """Check if a proposed trade violates any risk constraints.

    `projected_cash` overrides `portfolio["cash"]` for the cash check. The
    caller passes a projected balance that accounts for pending TRIM/SELL
    proceeds so that BUY proposals can fund themselves out of the cash a
    same-run trim is about to release.

    `risk_level` controls the per-position weight cap so a Growth or
    Aggressive user isn't tripped by the global default that's tuned for
    Balanced. Without this, generate_signals (which uses the risk profile's
    larger cap) and check_constraints (which used the global setting) would
    disagree, marking valid Growth-sized ADDs as "exceeds max".

    Returns dict with: passed (bool), violations (list of strings).
    """
    violations = []
    ticker = signal["ticker"]
    target_weight = signal["target_weight"]
    available_cash = projected_cash if projected_cash is not None else portfolio.get("cash", 0)

    # Max single position weight (respects risk profile).
    max_single_pos = _effective_max_single_position(risk_level)
    if target_weight > max_single_pos:
        violations.append(
            f"Position weight {target_weight:.1%} exceeds max {max_single_pos:.1%}"
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
        max_sector = settings.strategy.max_subsector_weight.get(sector, 0.50)

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

    # Cash check for buys. Uses projected_cash if the caller supplied one
    # (i.e. cash + pending trim proceeds), otherwise raw portfolio cash.
    if signal["action"] in ("BUY", "ADD"):
        portfolio_value = compute_portfolio_value(portfolio, prices)
        required_cash = target_weight * portfolio_value - current_weights.get(ticker, 0) * portfolio_value
        if required_cash > available_cash:
            violations.append(
                f"Insufficient cash: need ${required_cash:,.0f}, have ${available_cash:,.0f}"
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
    risk_level: int = 3,
) -> list[dict]:
    """Convert signals into formal trade proposals with budget-aware sizing.

    Two passes:
      1. Build SELL / TRIM proposals first. Each frees cash for the BUYs.
      2. Walk BUY / ADD proposals in priority order (composite_score desc),
         deducting the required cash from a running budget. If a BUY would
         push past the budget we try to shrink it to fit; if shrinking would
         leave fewer than ``MIN_BUY_SHARES`` shares, the proposal is still
         emitted but marked with a "Budget exhausted" violation so the user
         can see what the model wanted but couldn't fund.

    This replaces the old behavior where every BUY checked cash in isolation,
    letting the model recommend more BUYs than the budget could ever support.
    """
    current_weights = compute_portfolio_weights(portfolio, prices)
    portfolio_value = compute_portfolio_value(portfolio, prices)

    # Cash freed by SELL/TRIM signals becomes available for BUYs in the same
    # run. If the user later rejects a trim, the corresponding BUY simply
    # stays un-funded — the per-trade human review absorbs that risk.
    cash_freed_by_trims = 0.0
    for s in signals:
        if s.get("action") not in ("SELL", "TRIM"):
            continue
        t = s["ticker"]
        current_value = current_weights.get(t, 0) * portfolio_value
        target_value = s.get("target_weight", 0) * portfolio_value
        cash_freed_by_trims += max(0.0, current_value - target_value)

    starting_budget = portfolio.get("cash", 0) + cash_freed_by_trims

    proposals: list[dict] = []

    # ---- Pass 1: SELL / TRIM (no budget interaction) ---------------------
    for signal in signals:
        if signal["action"] not in ("SELL", "TRIM"):
            continue
        p = _build_one_proposal(
            signal, current_weights, portfolio, prices, universe,
            portfolio_value, adaptive_params, starting_budget,
            risk_level=risk_level,
        )
        if p is not None:
            proposals.append(p)

    # ---- Pass 2: BUY / ADD with cumulative budget ------------------------
    buys = [s for s in signals if s["action"] in ("BUY", "ADD")]
    buys.sort(
        key=lambda s: s.get("signal_data", {}).get("composite_score", 0),
        reverse=True,
    )

    # MIN_BUY_DOLLARS keeps us from emitting microscopic BUYs (e.g. $4 of
    # remaining budget that would round to 0 shares anyway). Tuned to one
    # share at $50 — anything smaller isn't worth a brokerage commission.
    MIN_BUY_DOLLARS = 50.0

    # ---- Pass 2a: scale buy targets UP if they collectively under-deploy
    # the available cash. The user's stock account is treated as a "budget"
    # — savings are kept elsewhere — so anything beyond max_cash_pct sitting
    # idle is leakage we should plug. We boost each buy's target proportionally
    # (capped by the risk-profile-aware max single position) until we land
    # near the deploy target. Buys that hit the per-position cap leave a
    # leftover slice that gets redistributed to the uncapped ones, one
    # redistribution pass.
    max_cash_pct = settings.strategy.max_cash_pct
    max_single_pos = _effective_max_single_position(risk_level)
    target_idle_cash = portfolio_value * max_cash_pct
    target_deploy = max(0.0, starting_budget - target_idle_cash)

    # Pre-compute nominal deltas for every buy so we know the collective ask.
    nominal: list[tuple[dict, float, float]] = []  # (signal, price, desired_delta)
    for signal in buys:
        price = prices.get(signal["ticker"], 0)
        if price <= 0:
            continue
        current_value = current_weights.get(signal["ticker"], 0) * portfolio_value
        target_value = signal["target_weight"] * portfolio_value
        desired_delta = target_value - current_value
        if desired_delta <= 0:
            continue
        nominal.append((signal, price, desired_delta))

    nominal_spend = sum(d for _, _, d in nominal)
    if nominal and nominal_spend > 0 and nominal_spend < target_deploy:
        scale = target_deploy / nominal_spend
        max_value_per_buy = max_single_pos * portfolio_value
        boosted: list[tuple[dict, float, float]] = []
        overflow = 0.0
        uncapped: list[int] = []
        for idx, (signal, price, delta) in enumerate(nominal):
            wanted = delta * scale
            if wanted > max_value_per_buy:
                overflow += wanted - max_value_per_buy
                boosted.append((signal, price, max_value_per_buy))
            else:
                boosted.append((signal, price, wanted))
                uncapped.append(idx)

        # One redistribution pass: the overflow from capped buys gets split
        # evenly among the still-uncapped ones (capped per position too).
        if overflow > 0 and uncapped:
            per_extra = overflow / len(uncapped)
            for idx in uncapped:
                signal, price, val = boosted[idx]
                new_val = min(val + per_extra, max_value_per_buy)
                boosted[idx] = (signal, price, new_val)

        nominal = boosted

    remaining_budget = starting_budget

    for signal, price, desired_delta in nominal:
        ticker = signal["ticker"]

        # Run the other (non-cash) constraints first so we attach their
        # violations to the proposal regardless of budget outcome.
        non_cash_check = check_constraints(
            signal, current_weights, portfolio, prices, universe,
            adaptive_params=adaptive_params,
            # Pass infinity so the cash branch in check_constraints never
            # adds an "Insufficient cash" violation — we own that decision
            # here based on the cumulative budget.
            projected_cash=float("inf"),
            risk_level=risk_level,
        )

        if remaining_budget < MIN_BUY_DOLLARS:
            # Budget already exhausted by higher-priority BUYs. Emit the
            # proposal at the desired size with a clear violation so the
            # user sees the candidate but knows it can't be funded.
            shares = int(desired_delta / price)
            if shares == 0:
                continue
            violations = list(non_cash_check.get("violations", []))
            violations.append(
                f"Budget exhausted by higher-priority BUYs (${remaining_budget:,.0f} left, "
                f"this trade needs ${desired_delta:,.0f})"
            )
            proposals.append(_make_proposal(
                signal, ticker, "BUY" if signal["action"] == "BUY" else signal["action"],
                shares, desired_delta,
                {"passed": False, "violations": violations},
                price,
            ))
            continue

        if desired_delta <= remaining_budget:
            # Fits as-is.
            shares = int(desired_delta / price)
            if shares == 0:
                continue
            actual_value = shares * price
            remaining_budget -= actual_value
            proposals.append(_make_proposal(
                signal, ticker, signal["action"], shares, actual_value,
                non_cash_check, price,
            ))
        else:
            # Doesn't fit at full size — shrink to remaining budget.
            shrunk_shares = int(remaining_budget / price)
            if shrunk_shares == 0:
                # Even one share is too expensive. Emit as budget-exhausted.
                violations = list(non_cash_check.get("violations", []))
                violations.append(
                    f"Budget too small for even one share (${remaining_budget:,.0f} left, "
                    f"price ${price:,.2f})"
                )
                proposals.append(_make_proposal(
                    signal, ticker, signal["action"],
                    int(desired_delta / price), desired_delta,
                    {"passed": False, "violations": violations},
                    price,
                ))
                # Don't deduct — nothing actually gets allocated.
                continue
            actual_value = shrunk_shares * price
            remaining_budget -= actual_value
            violations = list(non_cash_check.get("violations", []))
            violations.append(
                f"Auto-shrunk to fit remaining budget "
                f"(wanted ${desired_delta:,.0f}, allocated ${actual_value:,.0f})"
            )
            # Treat shrunk proposals as still "passed" — the user can approve
            # them at the reduced size, which is the intent.
            constraint_after_shrink = {
                "passed": non_cash_check.get("passed", True),
                "violations": violations,
            }
            proposals.append(_make_proposal(
                signal, ticker, signal["action"], shrunk_shares, actual_value,
                constraint_after_shrink, price,
                # Record what the model originally asked for so the UI can
                # show "wanted X, got Y" if it wants to.
                original_target_value=desired_delta,
            ))

    return proposals


def _build_one_proposal(
    signal: dict,
    current_weights: dict[str, float],
    portfolio: dict,
    prices: dict,
    universe: pd.DataFrame,
    portfolio_value: float,
    adaptive_params: dict | None,
    projected_cash: float,
    risk_level: int = 3,
) -> dict | None:
    """Build a single SELL/TRIM proposal (no budget tracking needed)."""
    ticker = signal["ticker"]
    price = prices.get(ticker, 0)
    if price <= 0:
        return None

    current_value = current_weights.get(ticker, 0) * portfolio_value
    target_value = signal["target_weight"] * portfolio_value
    delta_value = target_value - current_value
    shares = int(delta_value / price) if price > 0 else 0
    if abs(shares) == 0:
        return None

    constraint_result = check_constraints(
        signal, current_weights, portfolio, prices, universe,
        adaptive_params=adaptive_params,
        projected_cash=projected_cash,
        risk_level=risk_level,
    )
    return _make_proposal(
        signal, ticker, signal["action"], abs(shares), abs(delta_value),
        constraint_result, price,
    )


def reallocate_budget_after_judge(
    user_id: str,
    run_id: str,
    portfolio: dict,
    prices: dict[str, float],
    risk_level: int = 3,
) -> list[str]:
    """Re-run budget-aware sizing on the surviving proposals for a pipeline run.

    The judge runs after ``build_trade_proposals``, so proposals it later
    marks JUDGE_REJECTED have already claimed cash in the initial allocation.
    That leaves *real* surviving proposals (PENDING / NEEDS_REVIEW /
    JUDGE_APPROVED) marked "Budget exhausted" by phantom buys that nobody
    is going to execute. We fix that by re-allocating budget across only the
    survivors and updating their shares/estimated_value/violations in place.

    The "phantom" composition is:
      - judge-rejected proposals don't get any budget allocation
      - SELL/TRIM proceeds still feed the budget (those happen first)
      - surviving BUY/ADD compete for what's left, in composite-score order
    """
    REJECTED = ("JUDGE_REJECTED", "REJECTED", "BLOCKED")
    con = get_connection()
    try:
        # trade_proposals stores only shares + JSONB blobs; target/current
        # weights and estimated value were never columnized. We reconstruct
        # the "desired delta" from `shares × price` because at proposal time
        # `shares` is set to the DESIRED count even on budget-exhausted
        # records (see _make_proposal in the exhausted branch).
        rows = con.execute("""
            SELECT proposal_id, ticker, action, shares, signal_data,
                   constraint_check, status
            FROM trade_proposals
            WHERE run_id = $1 AND user_id = CAST($2 AS UUID)
        """, [run_id, user_id]).fetchdf()
    finally:
        con.close()

    if rows.empty:
        return

    # Compute starting_budget = cash + proceeds from surviving SELL/TRIM only.
    # (Rejected SELL/TRIM proposals don't actually free cash.)
    cash_freed = 0.0
    for r in rows.itertuples():
        if r.action not in ("SELL", "TRIM"):
            continue
        if r.status in REJECTED:
            continue
        ticker_t = r.ticker
        price = prices.get(ticker_t, 0)
        if price <= 0:
            continue
        cash_freed += abs(int(r.shares)) * price

    starting_budget = portfolio.get("cash", 0) + cash_freed

    # Survivors that touch the budget (BUY / ADD only, not rejected).
    survivors = []
    for r in rows.itertuples():
        if r.action not in ("BUY", "ADD"):
            continue
        if r.status in REJECTED:
            continue
        signal_blob = r.signal_data if isinstance(r.signal_data, dict) else {}
        if isinstance(r.signal_data, str):
            try:
                signal_blob = json.loads(r.signal_data)
            except Exception:
                signal_blob = {}
        price = prices.get(r.ticker, 0)
        desired_value = abs(int(r.shares)) * price if price > 0 else 0.0
        survivors.append({
            "proposal_id": r.proposal_id,
            "ticker": r.ticker,
            "action": r.action,
            "shares_nominal": int(r.shares),
            "estimated_value_nominal": desired_value,
            "composite_score": signal_blob.get("composite_score", 0) or 0,
            "current_check": r.constraint_check,
        })
    if not survivors:
        return []

    # Track which proposals had passed=False before reallocation so the caller
    # can re-judge those that flip to passed=True (they were skipped on the
    # initial judge pass because of phantom budget exhaustion).
    initially_blocked: set[str] = set()
    for s in survivors:
        check = s["current_check"] if isinstance(s["current_check"], dict) else {}
        if isinstance(s["current_check"], str):
            try:
                check = json.loads(s["current_check"])
            except Exception:
                check = {}
        if check.get("passed") is False:
            initially_blocked.add(s["proposal_id"])

    # Higher composite_score wins the budget first — same priority as the
    # initial allocation, just over the (much smaller) survivor set.
    survivors.sort(key=lambda s: s["composite_score"], reverse=True)

    # Cash-deploy boost (mirrors the logic in build_trade_proposals). When the
    # judge rejects most candidates, the survivor set's collective ask is
    # usually a tiny fraction of the budget. Without this scale-up, ADDs that
    # only wanted "+1 share to existing position" stay at 1 share even when
    # $5k of freed cash is sitting idle. We boost each survivor's desired
    # delta until they collectively hit the deploy target (capped per
    # position by max_single_position_weight).
    portfolio_value = compute_portfolio_value(portfolio, prices)
    max_cash_pct = settings.strategy.max_cash_pct
    target_deploy = max(0.0, starting_budget - portfolio_value * max_cash_pct)
    nominal_spend = sum(s["estimated_value_nominal"] for s in survivors)
    if nominal_spend > 0 and nominal_spend < target_deploy:
        scale = target_deploy / nominal_spend
        max_value_per_buy = _effective_max_single_position(risk_level) * portfolio_value
        overflow = 0.0
        uncapped_idx: list[int] = []
        for i, s in enumerate(survivors):
            wanted = s["estimated_value_nominal"] * scale
            if wanted > max_value_per_buy:
                overflow += wanted - max_value_per_buy
                s["estimated_value_nominal"] = max_value_per_buy
            else:
                s["estimated_value_nominal"] = wanted
                uncapped_idx.append(i)
        if overflow > 0 and uncapped_idx:
            per_extra = overflow / len(uncapped_idx)
            for i in uncapped_idx:
                survivors[i]["estimated_value_nominal"] = min(
                    survivors[i]["estimated_value_nominal"] + per_extra,
                    max_value_per_buy,
                )

    MIN_BUY_DOLLARS = 50.0
    remaining_budget = starting_budget

    updates: list[tuple[str, int, float, dict]] = []  # (id, shares, value, constraint_check)
    for s in survivors:
        price = prices.get(s["ticker"], 0)
        if price <= 0:
            continue
        desired_delta = s["estimated_value_nominal"]
        if desired_delta <= 0:
            continue

        # Strip any prior budget-related violations; we'll re-add fresh ones
        # if needed below.
        check = s["current_check"] if isinstance(s["current_check"], dict) else {}
        if isinstance(s["current_check"], str):
            try:
                check = json.loads(s["current_check"])
            except Exception:
                check = {}
        prior_violations = [
            v for v in (check.get("violations") or [])
            if not (
                isinstance(v, str)
                and (v.startswith("Budget exhausted") or v.startswith("Budget too small") or v.startswith("Auto-shrunk"))
            )
        ]

        # After stripping budget-related violations, passed depends entirely
        # on whether non-budget violations remain. If nothing remains, this
        # proposal clears constraints. If anything remains (e.g. sector
        # concentration), it stays blocked.
        prior_clean = len(prior_violations) == 0

        if remaining_budget < MIN_BUY_DOLLARS:
            new_check = {
                "passed": False,
                "violations": prior_violations + [
                    f"Budget exhausted by higher-priority BUYs (${remaining_budget:,.0f} left, "
                    f"this trade needs ${desired_delta:,.0f})"
                ],
            }
            updates.append((s["proposal_id"], int(desired_delta / price), desired_delta, new_check))
            continue

        if desired_delta <= remaining_budget:
            shares = int(desired_delta / price)
            if shares == 0:
                continue
            actual = shares * price
            remaining_budget -= actual
            new_check = {
                "passed": prior_clean,
                "violations": prior_violations,
            }
            updates.append((s["proposal_id"], shares, actual, new_check))
        else:
            shrunk = int(remaining_budget / price)
            if shrunk == 0:
                new_check = {
                    "passed": False,
                    "violations": prior_violations + [
                        f"Budget too small for even one share (${remaining_budget:,.0f} left, "
                        f"price ${price:,.2f})"
                    ],
                }
                updates.append((s["proposal_id"], int(desired_delta / price), desired_delta, new_check))
                continue
            actual = shrunk * price
            remaining_budget -= actual
            # Auto-shrunk is informational, not a hard block — the proposal
            # is still actionable at the reduced size.
            new_check = {
                "passed": prior_clean,
                "violations": prior_violations + [
                    f"Auto-shrunk to fit remaining budget "
                    f"(wanted ${desired_delta:,.0f}, allocated ${actual:,.0f})"
                ],
            }
            updates.append((s["proposal_id"], shrunk, actual, new_check))

    if not updates:
        return []

    con = get_connection()
    try:
        for pid, shares, value, check in updates:
            con.execute(
                """
                UPDATE trade_proposals
                SET shares = $1,
                    constraint_check = CAST($2 AS JSONB)
                WHERE proposal_id = $3 AND user_id = CAST($4 AS UUID)
                """,
                [shares, json.dumps(check), pid, user_id],
            )
    finally:
        con.close()

    # Proposals that flipped from passed=False to passed=True. The caller
    # should re-judge these — they were skipped on the initial judge pass.
    return [
        pid for pid, _shares, _value, new_check in updates
        if pid in initially_blocked and new_check.get("passed") is True
    ]


def _make_proposal(
    signal: dict,
    ticker: str,
    action: str,
    shares: int,
    value: float,
    constraint_result: dict,
    price: float,
    original_target_value: float | None = None,
) -> dict:
    """Assemble the proposal dict written to trade_proposals."""
    proposal = {
        "proposal_id": str(uuid.uuid4())[:8],
        "created_at": datetime.now().isoformat(),
        "ticker": ticker,
        "action": action,
        "shares": abs(int(shares)),
        "estimated_value": abs(float(value)),
        "current_weight": signal["current_weight"],
        "target_weight": signal["target_weight"],
        "signal_data": signal.get("signal_data", {}),
        "constraint_check": constraint_result,
        "reason": signal["reason"],
        "status": "PENDING",
        "gate_note": signal.get("gate_note"),
    }
    if original_target_value is not None:
        proposal["original_target_value"] = float(original_target_value)
    return proposal


def _sanitize_for_json(obj):
    """Recursively replace NaN/Inf with None so json.dumps produces valid JSON.

    Python's default json.dumps emits the literal "NaN" for float('nan') —
    valid Python but not valid JSON. Postgres JSONB columns reject it
    ("Token 'NaN' is invalid"). Walking the structure once before dumps
    is the cheapest robust fix.
    """
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _json_or_passthrough(value):
    """JSON-encode dicts (with NaN sanitization), leave other types alone."""
    if isinstance(value, dict):
        return json.dumps(_sanitize_for_json(value), allow_nan=False)
    return value


def store_proposals(proposals: list[dict], user_id: str) -> None:
    """Persist trade proposals for the given user. trade_proposals is per-user."""
    if not proposals:
        return
    if not user_id:
        raise ValueError("user_id is required for store_proposals")

    con = get_connection()
    for p in proposals:
        con.execute("""
            INSERT INTO trade_proposals
            (proposal_id, user_id, run_id, created_at, ticker, action, shares,
             signal_data, constraint_check, status, human_decision, human_notes, reason)
            VALUES ($1, CAST($2 AS UUID), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """, [
            p["proposal_id"],
            user_id,
            p.get("run_id"),
            p["created_at"],
            p["ticker"],
            p["action"],
            p["shares"],
            _json_or_passthrough(p["signal_data"]),
            _json_or_passthrough(p["constraint_check"]),
            p["status"],
            p.get("human_decision"),
            p.get("human_notes"),
            p.get("reason"),
        ])
    con.close()
    print(f"Stored {len(proposals)} trade proposals")
