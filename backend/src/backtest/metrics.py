"""Performance metrics: Sharpe, Information Ratio, max drawdown, turnover, etc."""

import pandas as pd
import numpy as np


def annualized_return(returns: pd.Series, periods_per_year: float = 252) -> float:
    """Compute annualized return from a series of periodic returns."""
    total_return = (1 + returns).prod()
    n_periods = len(returns)
    if n_periods == 0:
        return 0.0
    return total_return ** (periods_per_year / n_periods) - 1


def annualized_volatility(returns: pd.Series, periods_per_year: float = 252) -> float:
    """Compute annualized volatility."""
    return returns.std() * np.sqrt(periods_per_year)


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04,
    periods_per_year: float = 252,
) -> float:
    """Compute annualized Sharpe ratio."""
    ann_ret = annualized_return(returns, periods_per_year)
    ann_vol = annualized_volatility(returns, periods_per_year)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free_rate) / ann_vol


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04,
    periods_per_year: float = 252,
) -> float:
    """Compute annualized Sortino ratio (downside deviation only)."""
    ann_ret = annualized_return(returns, periods_per_year)
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf")
    downside_vol = downside.std() * np.sqrt(periods_per_year)
    if downside_vol == 0:
        return 0.0
    return (ann_ret - risk_free_rate) / downside_vol


def max_drawdown(returns: pd.Series) -> float:
    """Compute maximum drawdown from a return series."""
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / running_max
    return drawdowns.min()


def calmar_ratio(returns: pd.Series, periods_per_year: float = 252) -> float:
    """Compute Calmar ratio (annualized return / max drawdown)."""
    ann_ret = annualized_return(returns, periods_per_year)
    mdd = abs(max_drawdown(returns))
    if mdd == 0:
        return 0.0
    return ann_ret / mdd


def information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: float = 252,
) -> float:
    """Compute annualized Information Ratio vs. benchmark."""
    # Align series
    aligned = pd.DataFrame({"port": returns, "bench": benchmark_returns}).dropna()
    if aligned.empty:
        return 0.0

    active_returns = aligned["port"] - aligned["bench"]
    ann_active = annualized_return(active_returns, periods_per_year)
    tracking_error = active_returns.std() * np.sqrt(periods_per_year)

    if tracking_error == 0:
        return 0.0
    return ann_active / tracking_error


def hit_rate(returns: pd.Series) -> float:
    """Percentage of positive return periods."""
    if len(returns) == 0:
        return 0.0
    return (returns > 0).sum() / len(returns)


def win_loss_ratio(returns: pd.Series) -> float:
    """Average win / average loss."""
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if len(losses) == 0 or losses.mean() == 0:
        return float("inf")
    return abs(wins.mean() / losses.mean())


def compute_turnover(weights_today: dict, weights_yesterday: dict) -> float:
    """Compute one-way turnover between two weight snapshots."""
    all_tickers = set(weights_today.keys()) | set(weights_yesterday.keys())
    total_change = sum(
        abs(weights_today.get(t, 0) - weights_yesterday.get(t, 0))
        for t in all_tickers
    )
    return total_change / 2  # One-way


def full_metrics_report(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    periods_per_year: float = 252,
    risk_free_rate: float = 0.04,
) -> dict:
    """Compute all metrics and return as a dictionary."""
    report = {
        "annualized_return": annualized_return(returns, periods_per_year),
        "annualized_volatility": annualized_volatility(returns, periods_per_year),
        "sharpe_ratio": sharpe_ratio(returns, risk_free_rate, periods_per_year),
        "sortino_ratio": sortino_ratio(returns, risk_free_rate, periods_per_year),
        "max_drawdown": max_drawdown(returns),
        "calmar_ratio": calmar_ratio(returns, periods_per_year),
        "hit_rate": hit_rate(returns),
        "win_loss_ratio": win_loss_ratio(returns),
        "total_return": (1 + returns).prod() - 1,
        "n_periods": len(returns),
    }

    if benchmark_returns is not None:
        bench_aligned = benchmark_returns.reindex(returns.index).dropna()
        report["benchmark_return"] = annualized_return(bench_aligned, periods_per_year)
        report["alpha"] = report["annualized_return"] - report["benchmark_return"]
        report["information_ratio"] = information_ratio(
            returns, benchmark_returns, periods_per_year
        )
        report["benchmark_max_drawdown"] = max_drawdown(bench_aligned)

    return report


def print_metrics_report(report: dict) -> None:
    """Pretty-print a metrics report."""
    print(f"  Annualized Return:    {report['annualized_return']:>8.2%}")
    print(f"  Annualized Vol:       {report['annualized_volatility']:>8.2%}")
    print(f"  Sharpe Ratio:         {report['sharpe_ratio']:>8.2f}")
    print(f"  Sortino Ratio:        {report['sortino_ratio']:>8.2f}")
    print(f"  Max Drawdown:         {report['max_drawdown']:>8.2%}")
    print(f"  Calmar Ratio:         {report['calmar_ratio']:>8.2f}")
    print(f"  Hit Rate:             {report['hit_rate']:>8.2%}")
    print(f"  Win/Loss Ratio:       {report['win_loss_ratio']:>8.2f}")
    print(f"  Total Return:         {report['total_return']:>8.2%}")

    if "benchmark_return" in report:
        print(f"  --- vs Benchmark ---")
        print(f"  Benchmark Return:     {report['benchmark_return']:>8.2%}")
        print(f"  Alpha:                {report['alpha']:>8.2%}")
        print(f"  Information Ratio:    {report['information_ratio']:>8.2f}")
