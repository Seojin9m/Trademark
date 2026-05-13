"""Market context: price trends, technicals, and sector performance for the LLM judge."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection
from src.db.state import load_universe_df


def _compute_ticker_metrics(prices_df: pd.DataFrame) -> dict:
    """Compute return, SMA, and 52-week range metrics from a price series.

    Expects a DataFrame with columns [date, adj_close] sorted by date ascending.
    """
    if prices_df.empty:
        return {}

    closes = prices_df["adj_close"].values
    n = len(closes)
    current = float(closes[-1])

    def pct(ago: int) -> float | None:
        if n > ago and closes[-(ago + 1)] > 0:
            return round((current / closes[-(ago + 1)] - 1) * 100, 2)
        return None

    high_52w = float(np.max(closes))
    low_52w = float(np.min(closes))

    sma_50 = float(np.mean(closes[-50:])) if n >= 50 else None
    sma_200 = float(np.mean(closes[-200:])) if n >= 200 else None

    return {
        "current_price": round(current, 2),
        "return_5d_pct": pct(5),
        "return_1m_pct": pct(21),
        "return_3m_pct": pct(63),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "dist_from_52w_high_pct": round((current / high_52w - 1) * 100, 1) if high_52w > 0 else None,
        "sma_50d": round(sma_50, 2) if sma_50 else None,
        "sma_200d": round(sma_200, 2) if sma_200 else None,
        "above_sma_50": current > sma_50 if sma_50 else None,
        "above_sma_200": current > sma_200 if sma_200 else None,
    }


def get_price_context(ticker: str) -> dict:
    """Get full price context for a single ticker + benchmark + sector.

    Returns a dict with stock metrics, benchmark metrics, and sector comparison.
    Returns empty dict on any failure.
    """
    try:
        benchmark = settings.primary_benchmark
        con = get_connection()

        # Fetch ~1 year of prices for stock + benchmark in one query
        df = con.execute("""
            SELECT ticker, date, adj_close
            FROM prices
            WHERE ticker = ANY($1) AND adj_close > 0
            ORDER BY ticker, date DESC
        """, [[ticker, benchmark]]).fetchdf()

        # Load universe for sector lookup
        universe = load_universe_df()
        sub_sector_row = universe.loc[universe["ticker"] == ticker, "sub_sector"]
        sub_sector = sub_sector_row.iloc[0] if not sub_sector_row.empty else None

        # Sector tickers for comparison
        sector_metrics = None
        if sub_sector:
            sector_tickers = universe.loc[universe["sub_sector"] == sub_sector, "ticker"].tolist()
            sector_tickers = [t for t in sector_tickers if t != ticker][:10]
            if sector_tickers:
                sector_df = con.execute("""
                    SELECT ticker, date, adj_close
                    FROM prices
                    WHERE ticker = ANY($1) AND adj_close > 0
                    ORDER BY ticker, date DESC
                """, [sector_tickers]).fetchdf()
            else:
                sector_df = pd.DataFrame()
        else:
            sector_df = pd.DataFrame()

        con.close()

        if df.empty:
            return {}

        # Compute stock metrics
        stock_prices = df[df["ticker"] == ticker].sort_values("date").tail(252)
        stock = _compute_ticker_metrics(stock_prices)
        if not stock:
            return {}

        # Compute benchmark metrics
        bench_prices = df[df["ticker"] == benchmark].sort_values("date").tail(252)
        bench = _compute_ticker_metrics(bench_prices)

        # Compute sector context
        if sub_sector and not sector_df.empty:
            sector_returns_1m = []
            for st in sector_df["ticker"].unique():
                st_prices = sector_df[sector_df["ticker"] == st].sort_values("date").tail(252)
                st_metrics = _compute_ticker_metrics(st_prices)
                if st_metrics.get("return_1m_pct") is not None:
                    sector_returns_1m.append(st_metrics["return_1m_pct"])

            if sector_returns_1m:
                median_1m = float(np.median(sector_returns_1m))
                bench_1m = bench.get("return_1m_pct", 0) or 0
                stock_1m = stock.get("return_1m_pct", 0) or 0
                sector_metrics = {
                    "name": sub_sector,
                    "n_tickers": len(sector_returns_1m),
                    "median_return_1m_pct": round(median_1m, 2),
                    "vs_market_1m_pct": round(median_1m - bench_1m, 2),
                    "stock_vs_sector_1m_pct": round(stock_1m - median_1m, 2),
                }

        return {
            "ticker": ticker,
            **stock,
            "benchmark": {"ticker": benchmark, **bench} if bench else None,
            "sector": sector_metrics,
        }

    except Exception:
        return {}


def get_batch_price_context(tickers: list[str]) -> dict[str, dict]:
    """Get price context for multiple tickers efficiently.

    Returns dict of ticker -> metrics. Used by portfolio review.
    """
    try:
        benchmark = settings.primary_benchmark
        all_tickers = list(set(tickers + [benchmark]))

        con = get_connection()
        df = con.execute("""
            SELECT ticker, date, adj_close
            FROM prices
            WHERE ticker = ANY($1) AND adj_close > 0
            ORDER BY ticker, date DESC
        """, [all_tickers]).fetchdf()

        # Load universe for sector info
        universe = load_universe_df()
        sector_map = dict(zip(universe["ticker"], universe.get("sub_sector", pd.Series())))

        # Also fetch sector peers for sector context
        held_sectors = set(sector_map.get(t) for t in tickers if sector_map.get(t))
        sector_peer_tickers = []
        for sec in held_sectors:
            peers = universe.loc[universe["sub_sector"] == sec, "ticker"].tolist()
            sector_peer_tickers.extend([t for t in peers if t not in all_tickers][:5])

        if sector_peer_tickers:
            peer_df = con.execute("""
                SELECT ticker, date, adj_close
                FROM prices
                WHERE ticker = ANY($1) AND adj_close > 0
                ORDER BY ticker, date DESC
            """, [sector_peer_tickers]).fetchdf()
            df = pd.concat([df, peer_df])

        con.close()

        if df.empty:
            return {}

        # Compute benchmark metrics once
        bench_prices = df[df["ticker"] == benchmark].sort_values("date").tail(252)
        bench = _compute_ticker_metrics(bench_prices)
        bench_1m = bench.get("return_1m_pct", 0) or 0

        # Compute per-sector median returns
        sector_medians = {}
        all_unique_tickers = df["ticker"].unique()
        for sec in held_sectors:
            sec_tickers = [t for t in universe.loc[universe["sub_sector"] == sec, "ticker"].tolist()
                           if t in all_unique_tickers]
            sec_returns = []
            for t in sec_tickers:
                t_prices = df[df["ticker"] == t].sort_values("date").tail(252)
                t_m = _compute_ticker_metrics(t_prices)
                if t_m.get("return_1m_pct") is not None:
                    sec_returns.append(t_m["return_1m_pct"])
            if sec_returns:
                sector_medians[sec] = {
                    "median_return_1m_pct": round(float(np.median(sec_returns)), 2),
                    "n_tickers": len(sec_returns),
                }

        # Compute per-ticker metrics
        results = {}
        for ticker in tickers:
            t_prices = df[df["ticker"] == ticker].sort_values("date").tail(252)
            metrics = _compute_ticker_metrics(t_prices)
            if not metrics:
                continue

            sub_sector = sector_map.get(ticker)
            sector_ctx = None
            if sub_sector and sub_sector in sector_medians:
                sm = sector_medians[sub_sector]
                stock_1m = metrics.get("return_1m_pct", 0) or 0
                sector_ctx = {
                    "name": sub_sector,
                    "n_tickers": sm["n_tickers"],
                    "median_return_1m_pct": sm["median_return_1m_pct"],
                    "vs_market_1m_pct": round(sm["median_return_1m_pct"] - bench_1m, 2),
                    "stock_vs_sector_1m_pct": round(stock_1m - sm["median_return_1m_pct"], 2),
                }

            results[ticker] = {
                "ticker": ticker,
                **metrics,
                "benchmark": {"ticker": benchmark, **bench} if bench else None,
                "sector": sector_ctx,
            }

        return results

    except Exception:
        return {}


def format_price_section(ctx: dict) -> str:
    """Format a single ticker's price context into a prompt section string."""
    if not ctx:
        return ""

    ticker = ctx.get("ticker", "?")
    lines = [f"### {ticker} Price Data"]

    price = ctx.get("current_price")
    if price:
        lines.append(f"Current price: ${price:.2f}")

    r5 = ctx.get("return_5d_pct")
    r1m = ctx.get("return_1m_pct")
    r3m = ctx.get("return_3m_pct")
    parts = []
    if r5 is not None: parts.append(f"5d {r5:+.1f}%")
    if r1m is not None: parts.append(f"1m {r1m:+.1f}%")
    if r3m is not None: parts.append(f"3m {r3m:+.1f}%")
    if parts:
        lines.append(f"Returns: {' | '.join(parts)}")

    hi = ctx.get("high_52w")
    lo = ctx.get("low_52w")
    dist = ctx.get("dist_from_52w_high_pct")
    if hi and lo:
        lines.append(f"52-week range: ${lo:.2f} - ${hi:.2f} ({dist:+.1f}% from high)")

    sma50 = ctx.get("sma_50d")
    above50 = ctx.get("above_sma_50")
    if sma50 is not None:
        lines.append(f"50-day SMA: ${sma50:.2f} ({'ABOVE' if above50 else 'BELOW'})")

    sma200 = ctx.get("sma_200d")
    above200 = ctx.get("above_sma_200")
    if sma200 is not None:
        lines.append(f"200-day SMA: ${sma200:.2f} ({'ABOVE' if above200 else 'BELOW'})")

    # Benchmark section
    bench = ctx.get("benchmark")
    if bench:
        lines.append(f"\n### Market Context ({bench.get('ticker', 'QQQ')})")
        bp = []
        if bench.get("return_5d_pct") is not None: bp.append(f"5d {bench['return_5d_pct']:+.1f}%")
        if bench.get("return_1m_pct") is not None: bp.append(f"1m {bench['return_1m_pct']:+.1f}%")
        if bench.get("return_3m_pct") is not None: bp.append(f"3m {bench['return_3m_pct']:+.1f}%")
        if bp:
            lines.append(f"Returns: {' | '.join(bp)}")
        sma_parts = []
        if bench.get("above_sma_50") is not None:
            sma_parts.append(f"50d SMA: {'ABOVE' if bench['above_sma_50'] else 'BELOW'}")
        if bench.get("above_sma_200") is not None:
            sma_parts.append(f"200d SMA: {'ABOVE' if bench['above_sma_200'] else 'BELOW'}")
        if sma_parts:
            lines.append(f"Trend: {' | '.join(sma_parts)}")

    # Sector section
    sector = ctx.get("sector")
    if sector:
        lines.append(f"\n### Sector ({sector['name']}, n={sector.get('n_tickers', '?')})")
        lines.append(f"Sector median 1m: {sector['median_return_1m_pct']:+.1f}% (vs market: {sector['vs_market_1m_pct']:+.1f}%)")
        lines.append(f"Stock vs sector 1m: {sector['stock_vs_sector_1m_pct']:+.1f}%")

    return "\n".join(lines)


def format_portfolio_price_section(contexts: dict[str, dict]) -> str:
    """Format batch price context into a compact table for portfolio review."""
    if not contexts:
        return ""

    # Get benchmark from first entry
    bench = None
    for ctx in contexts.values():
        if ctx.get("benchmark"):
            bench = ctx["benchmark"]
            break

    lines = ["## Price & Technical Context"]

    if bench:
        bp = []
        if bench.get("return_5d_pct") is not None: bp.append(f"5d {bench['return_5d_pct']:+.1f}%")
        if bench.get("return_1m_pct") is not None: bp.append(f"1m {bench['return_1m_pct']:+.1f}%")
        if bench.get("return_3m_pct") is not None: bp.append(f"3m {bench['return_3m_pct']:+.1f}%")
        sma_str = ""
        if bench.get("above_sma_50") is not None:
            sma_str += f" | 50d: {'ABOVE' if bench['above_sma_50'] else 'BELOW'}"
        if bench.get("above_sma_200") is not None:
            sma_str += f" | 200d: {'ABOVE' if bench['above_sma_200'] else 'BELOW'}"
        lines.append(f"\nMarket ({bench.get('ticker', 'QQQ')}): {' | '.join(bp)}{sma_str}")

    lines.append("")
    lines.append("| Ticker | Price | 5d% | 1m% | 3m% | vs52wH | >50d | >200d | Sector 1m |")
    lines.append("|--------|-------|-----|-----|-----|--------|------|-------|-----------|")

    for ticker, ctx in sorted(contexts.items()):
        price = f"${ctx.get('current_price', 0):.0f}" if ctx.get("current_price") else "?"
        r5 = f"{ctx['return_5d_pct']:+.1f}" if ctx.get("return_5d_pct") is not None else "?"
        r1m = f"{ctx['return_1m_pct']:+.1f}" if ctx.get("return_1m_pct") is not None else "?"
        r3m = f"{ctx['return_3m_pct']:+.1f}" if ctx.get("return_3m_pct") is not None else "?"
        dist = f"{ctx['dist_from_52w_high_pct']:+.1f}%" if ctx.get("dist_from_52w_high_pct") is not None else "?"
        a50 = "Y" if ctx.get("above_sma_50") else ("N" if ctx.get("above_sma_50") is False else "?")
        a200 = "Y" if ctx.get("above_sma_200") else ("N" if ctx.get("above_sma_200") is False else "?")
        sec = ""
        if ctx.get("sector"):
            sec = f"{ctx['sector']['median_return_1m_pct']:+.1f}%"
        lines.append(f"| {ticker} | {price} | {r5} | {r1m} | {r3m} | {dist} | {a50} | {a200} | {sec} |")

    lines.append("")
    lines.append("Use price context alongside factor scores. Stocks below both SMAs with negative trends may indicate deteriorating conditions despite good factor scores.")

    return "\n".join(lines)
