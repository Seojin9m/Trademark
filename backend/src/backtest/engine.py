"""Walk-forward backtesting engine.

Simulates the factor-ranking strategy on historical data:
1. At each rebalance date, score and rank all universe tickers
2. Build a portfolio: top-decile stocks get highest weight, bottom gets zero
3. Apply turnover controls: only trade when decile changes by threshold
4. Apply drawdown gate: block new buys when drawdown exceeds limit
5. Track returns net of transaction costs
6. Compare to QQQ benchmark
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection
from src.backtest.metrics import full_metrics_report, print_metrics_report


def get_returns_matrix(start_date: str, end_date: str) -> pd.DataFrame:
    """Get daily returns for all universe tickers + benchmarks."""
    con = get_connection()
    prices = con.execute("""
        SELECT ticker, date, adj_close
        FROM prices
        WHERE date BETWEEN $1 AND $2
          AND adj_close IS NOT NULL AND adj_close > 0
        ORDER BY ticker, date
    """, [start_date, end_date]).fetchdf()
    con.close()

    if prices.empty:
        return pd.DataFrame()

    prices["date"] = pd.to_datetime(prices["date"])
    pivot = prices.pivot(index="date", columns="ticker", values="adj_close")
    returns = pivot.pct_change(fill_method=None).dropna(how="all")
    return returns


def decile_to_target_weight(decile: int) -> float:
    """Map score decile to target portfolio weight tier."""
    if decile >= 9:
        return 0.06  # Core: 6% target
    elif decile >= 7:
        return 0.04  # Tactical: 4% target
    elif decile >= 5:
        return 0.02  # Underweight: 2%
    else:
        return 0.0  # Exit


def build_target_weights(
    scores: pd.DataFrame,
    current_weights: dict[str, float],
    prior_deciles: dict[str, int],
    min_decile_change: int = 2,
    drawdown_block_buys: bool = False,
) -> dict[str, float]:
    """Build target portfolio weights with turnover controls.

    Only changes position if:
    - Ticker's decile changed by >= min_decile_change since last rebalance, OR
    - Ticker is new to portfolio (wasn't held before), OR
    - Ticker's target weight is 0 (exit signal)

    If drawdown_block_buys=True, no new positions are opened.
    """
    max_weight = settings.strategy.max_single_position_weight
    max_positions = settings.strategy.max_positions

    scores = scores.sort_values("composite_score", ascending=False)

    # Build ideal target weights from scores
    ideal_weights = {}
    new_deciles = {}
    for _, row in scores.iterrows():
        ticker = row["ticker"]
        decile = int(row["score_decile"])
        new_deciles[ticker] = decile
        w = decile_to_target_weight(decile)
        if w > 0:
            ideal_weights[ticker] = min(w, max_weight)

    # Apply turnover control: only trade if decile changed enough
    final_weights = {}
    for ticker in set(list(ideal_weights.keys()) + list(current_weights.keys())):
        old_w = current_weights.get(ticker, 0)
        ideal_w = ideal_weights.get(ticker, 0)
        old_decile = prior_deciles.get(ticker, 5)  # Default to neutral
        new_decile = new_deciles.get(ticker, 5)

        decile_change = abs(new_decile - old_decile)

        if ideal_w == 0 and old_w > 0:
            # Exit signal: always honor (decile dropped to 1-4)
            if decile_change >= min_decile_change:
                final_weights[ticker] = 0  # Sell
            else:
                final_weights[ticker] = old_w  # Hold despite low score
        elif old_w > 0:
            # Existing position: only resize if decile changed enough
            if decile_change >= min_decile_change:
                final_weights[ticker] = ideal_w
            else:
                final_weights[ticker] = old_w  # Hold current weight
        elif ideal_w > 0 and old_w == 0:
            # New position: only buy if not blocked by drawdown
            if drawdown_block_buys:
                continue  # Skip new buys during drawdown
            if new_decile >= 9:  # Only enter top-decile names
                final_weights[ticker] = ideal_w

    # Remove zero-weight entries
    final_weights = {t: w for t, w in final_weights.items() if w > 0}

    # Limit to max positions (keep highest-scored)
    if len(final_weights) > max_positions:
        scored_tickers = scores[scores["ticker"].isin(final_weights.keys())]
        top_tickers = scored_tickers.head(max_positions)["ticker"].tolist()
        final_weights = {t: final_weights[t] for t in top_tickers if t in final_weights}

    # Normalize if needed
    total = sum(final_weights.values())
    if total > 1.0:
        factor = 1.0 / total
        final_weights = {t: w * factor for t, w in final_weights.items()}

    return final_weights, new_deciles


def compute_transaction_costs(
    old_weights: dict,
    new_weights: dict,
    portfolio_value: float,
) -> float:
    """Compute transaction costs from portfolio rebalance."""
    cost_bps = settings.strategy.round_trip_cost_bps_large / 10000

    all_tickers = set(old_weights.keys()) | set(new_weights.keys())
    total_traded = sum(
        abs(new_weights.get(t, 0) - old_weights.get(t, 0))
        for t in all_tickers
    )

    return total_traded * portfolio_value * cost_bps


def compute_drawdown(daily_returns: list[dict]) -> float:
    """Compute current drawdown from peak."""
    if not daily_returns:
        return 0.0
    cum = np.cumprod([1 + r["return"] for r in daily_returns])
    peak = np.maximum.accumulate(cum)
    return (cum[-1] / peak[-1]) - 1.0


def run_backtest(
    scores_df: pd.DataFrame,
    start_date: str = "2021-06-01",
    end_date: str | None = None,
    initial_capital: float = 100000.0,
    min_decile_change: int = 2,
) -> dict:
    """Run a full walk-forward backtest with turnover controls and drawdown gate."""
    if end_date is None:
        end_date = str(scores_df["date"].max())

    returns_matrix = get_returns_matrix(start_date, end_date)
    if returns_matrix.empty:
        print("ERROR: No returns data available")
        return {}

    benchmark = settings.primary_benchmark
    bench_returns = returns_matrix[benchmark] if benchmark in returns_matrix.columns else None

    scores_df = scores_df.copy()
    scores_df["date"] = pd.to_datetime(scores_df["date"])
    rebalance_dates = set(scores_df["date"].unique())

    # Initialize
    portfolio_value = initial_capital
    current_weights: dict[str, float] = {}
    prior_deciles: dict[str, int] = {}
    daily_returns = []
    trade_log = []
    turnover_log = []
    drawdown_alert = settings.strategy.max_portfolio_drawdown_alert  # -0.15

    trading_dates = returns_matrix.index.sort_values()

    for day in trading_dates:
        is_rebalance = day in rebalance_dates

        if is_rebalance:
            day_scores = scores_df[scores_df["date"] == day]
            if not day_scores.empty:
                # Check drawdown gate
                current_dd = compute_drawdown(daily_returns)
                block_buys = current_dd < drawdown_alert

                if block_buys:
                    print(f"  DRAWDOWN GATE: {current_dd:.1%} on {day.date()}, blocking new buys")

                new_weights, new_deciles = build_target_weights(
                    day_scores,
                    current_weights,
                    prior_deciles,
                    min_decile_change=min_decile_change,
                    drawdown_block_buys=block_buys,
                )

                # Transaction costs
                cost = compute_transaction_costs(
                    current_weights, new_weights, portfolio_value
                )

                # Log turnover
                all_t = set(current_weights.keys()) | set(new_weights.keys())
                turnover = sum(
                    abs(new_weights.get(t, 0) - current_weights.get(t, 0))
                    for t in all_t
                ) / 2
                turnover_log.append({"date": day, "turnover": turnover})

                # Log trades
                for t in all_t:
                    old_w = current_weights.get(t, 0)
                    new_w = new_weights.get(t, 0)
                    if abs(new_w - old_w) > 0.005:
                        trade_log.append({
                            "date": day,
                            "ticker": t,
                            "old_weight": old_w,
                            "new_weight": new_w,
                            "action": "BUY" if new_w > old_w else "SELL",
                        })

                current_weights = new_weights
                prior_deciles = new_deciles
                portfolio_value -= cost

        # Daily portfolio return
        day_return = 0.0
        for ticker, weight in current_weights.items():
            if ticker in returns_matrix.columns:
                r = returns_matrix.loc[day, ticker]
                if not pd.isna(r):
                    day_return += weight * r

        daily_returns.append({"date": day, "return": day_return})
        portfolio_value *= (1 + day_return)

    # Build results
    port_returns = pd.Series(
        [r["return"] for r in daily_returns],
        index=pd.DatetimeIndex([r["date"] for r in daily_returns]),
        name="portfolio",
    )

    metrics = full_metrics_report(
        port_returns,
        benchmark_returns=bench_returns,
        periods_per_year=252,
    )

    # Turnover stats
    if turnover_log:
        turnover_df = pd.DataFrame(turnover_log)
        rebal_per_year = len(turnover_df) / (len(port_returns) / 252)
        metrics["avg_rebalance_turnover"] = turnover_df["turnover"].mean()
        metrics["annualized_turnover"] = turnover_df["turnover"].mean() * rebal_per_year
    else:
        metrics["avg_rebalance_turnover"] = 0
        metrics["annualized_turnover"] = 0

    metrics["n_trades"] = len(trade_log)
    metrics["final_portfolio_value"] = portfolio_value

    return {
        "portfolio_returns": port_returns,
        "benchmark_returns": bench_returns,
        "metrics": metrics,
        "trade_log": pd.DataFrame(trade_log) if trade_log else pd.DataFrame(),
        "turnover_log": pd.DataFrame(turnover_log) if turnover_log else pd.DataFrame(),
    }


def run_full_backtest(
    start_date: str = "2021-06-01",
    end_date: str | None = None,
    rebalance_freq: str = "2W-FRI",
    min_decile_change: int = 2,
) -> dict:
    """End-to-end: compute historical scores then run backtest."""
    from src.features.composite import compute_composite_historical

    print(f"Config: rebalance={rebalance_freq}, min_decile_change={min_decile_change}")
    print("Step 1: Computing historical factor scores...")
    scores = compute_composite_historical(
        start_date=start_date,
        end_date=end_date,
        freq=rebalance_freq,
    )

    if scores.empty:
        print("ERROR: No scores computed")
        return {}

    print(f"\nScores computed: {len(scores)} rows across {scores['date'].nunique()} dates")
    print(f"Tickers covered: {scores['ticker'].nunique()}")

    print("\nStep 2: Running backtest...")
    results = run_backtest(
        scores,
        start_date=start_date,
        end_date=end_date,
        min_decile_change=min_decile_change,
    )

    if not results:
        return {}

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print_metrics_report(results["metrics"])
    print(f"  Annualized Turnover:  {results['metrics']['annualized_turnover']:>8.2%}")
    print(f"  Total Trades:         {results['metrics']['n_trades']:>8d}")
    print(f"  Final Value:          ${results['metrics']['final_portfolio_value']:>12,.2f}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    results = run_full_backtest(
        start_date="2021-06-01",
        rebalance_freq="2W-FRI",
        min_decile_change=2,
    )
