"""Build a long-term-quality stock universe.

This is the v2 universe construction script. It replaces the single-day
dollar-volume snapshot with a more principled 5-stage funnel suitable for
monthly rebuilds:

    Stage 1: Polygon active US common stocks                    (~5,000)
    Stage 2: NYSE/NASDAQ + drop warrants/units/rights           (~5,000)
    Stage 3: 60-day MEDIAN dollar-volume >= $10M                (~2,000)
    Stage 4: >= 5 quarters of fundamentals available            (~1,500)
    Stage 5: Tier by 60-day median dollar-volume                (final)

Why median-of-60 instead of single-day:
    A single anomalous day (earnings, halt, news) can spike or kill a
    ticker's $-volume. Median over a 60-day window is robust to outliers
    and tracks true tradability.

Why a fundamentals floor:
    Tickers without enough quarters get NaN factor scores and silently
    drop out of ranking anyway. Filtering explicitly is cleaner and
    surfaces the right summary in diff reports.

    Floor is set to 5 quarters (not 8) because that's the depth yfinance
    reliably returns from `quarterly_income_stmt`. With 5 quarters we can
    still compute YoY growth (Q0 vs Q-4) — the minimum signal we need.
    Tickers SimFin tracks usually have 20+ quarters and exceed this
    easily; the 5-floor matters only for the yfinance-only tail (foreign
    issuers, recent IPOs, share-class variants).

    Known share-class quirk: GOOGL fundamentals may live under GOOG in
    SimFin. Add explicit whitelist if a portfolio holding gets dropped.

The script is non-destructive: writes to `backend/config/universe_strict.csv`
so you can compare against `universe.csv` before swapping.

Run
---
    cd backend && python -u -m scripts.build_universe

Tunables via env vars:
    UNIVERSE_MIN_MEDIAN_DV    default 10_000_000  ($10M median ADV)
    UNIVERSE_MIN_QUARTERS     default 5           (5 quarters of fundamentals)
    UNIVERSE_LOOKBACK_DAYS    default 60          (trading days for DV median)
    UNIVERSE_OUT              default universe_strict.csv
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


# Liquidity-based tier buckets (median daily dollar-volume in USD).
# Until we wire in a reliable market-cap source, $-volume tiers are the most
# stable proxy for size that doesn't require a separate per-ticker API call.
TIER_BUCKETS = [
    ("mega", 1_000_000_000),
    ("large", 100_000_000),
    ("mid", 10_000_000),
    ("small", 5_000_000),
]

# MIC codes for the venues we want — operating companies on the primary
# US exchanges. ARCX (Arca) is ETF-heavy; OTC venues are too thin.
ALLOWED_EXCHANGES = {"XNYS", "XNAS"}

# Cache locations for the expensive Polygon pulls. Both are weekly cached:
# the listing universe and the 60-day price snapshot evolve slowly, and
# re-running the script during the same week shouldn't re-pay the network.
_LISTINGS_CACHE = settings.paths.data_dir / "raw" / "polygon_listings_cache.csv"
_DV_HISTORY_CACHE = settings.paths.data_dir / "raw" / "polygon_dv_history_cache.parquet"


def _most_recent_weekday() -> datetime:
    d = datetime.now() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_all_us_common_stocks(use_cache: bool = True) -> pd.DataFrame:
    """Paged Polygon /v3/reference/tickers fetch (cached for 1 week).

    Returns columns: ticker, name, primary_exchange.
    """
    if use_cache and _LISTINGS_CACHE.exists():
        age_hours = (time.time() - _LISTINGS_CACHE.stat().st_mtime) / 3600
        if age_hours < 168:
            print(f"Using cached listings ({age_hours:.0f}h old): {_LISTINGS_CACHE}")
            return pd.read_csv(_LISTINGS_CACHE)

    import requests

    api_key = settings.api_keys.polygon_api_key
    base = "https://api.polygon.io/v3/reference/tickers"
    params = {
        "market": "stocks",
        "type": "CS",
        "active": "true",
        "limit": 1000,
        "apiKey": api_key,
    }

    print("Fetching US common stock listings from Polygon reference...")
    rows: list[dict] = []
    url: str | None = base
    page = 0
    while url:
        page += 1
        if page == 1:
            resp = requests.get(url, params=params, timeout=30)
        else:
            sep = "&" if "?" in url else "?"
            resp = requests.get(f"{url}{sep}apiKey={api_key}", timeout=30)

        if resp.status_code == 429:
            print(f"  Page {page}: 429 rate limit, sleeping 65s and retrying...")
            time.sleep(65)
            continue

        resp.raise_for_status()
        data = resp.json()
        for t in data.get("results", []):
            rows.append({
                "ticker": t.get("ticker") or "",
                "name": t.get("name") or "",
                "primary_exchange": t.get("primary_exchange") or "",
            })

        url = data.get("next_url")
        print(f"  Page {page}: +{len(data.get('results', []))} (running total: {len(rows)})")

        # No pacing — Polygon Starter has unlimited API calls. If you drop
        # back to the free tier, restore time.sleep(15) here to stay under
        # the 5/min ceiling.

    df = pd.DataFrame(rows).drop_duplicates(subset=["ticker"])
    _LISTINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(_LISTINGS_CACHE, index=False)
    print(f"  Reference listing returned {len(df)} active common stocks (cached)")
    return df


def fetch_dollar_volume_history(num_trading_days: int = 60, use_cache: bool = True) -> pd.DataFrame:
    """Pull `num_trading_days` of Polygon Grouped Daily aggregates.

    Each call returns OHLCV for every US stock on a single date. We walk
    backwards day-by-day, skipping weekends and any date Polygon returns
    empty (US market holidays). At 5 calls/min on free tier, 60 trading
    days takes ~13 min total. Caches the result as parquet so re-runs
    during the same week skip the network entirely.

    Returns columns: ticker, date, close, volume, dollar_volume.
    """
    if use_cache and _DV_HISTORY_CACHE.exists():
        age_hours = (time.time() - _DV_HISTORY_CACHE.stat().st_mtime) / 3600
        if age_hours < 168:
            print(f"Using cached DV history ({age_hours:.0f}h old): {_DV_HISTORY_CACHE}")
            return pd.read_parquet(_DV_HISTORY_CACHE)

    from polygon import RESTClient

    client = RESTClient(api_key=settings.api_keys.polygon_api_key)
    rows: list[dict] = []
    days_collected = 0
    cal_date = _most_recent_weekday()
    # Bound on calendar-day iteration so a long-holiday week can't loop forever
    max_calendar_iterations = num_trading_days * 2 + 14

    print(f"Fetching {num_trading_days} trading days of grouped daily aggregates...")
    iterations = 0
    while days_collected < num_trading_days and iterations < max_calendar_iterations:
        iterations += 1
        if cal_date.weekday() >= 5:
            cal_date -= timedelta(days=1)
            continue

        date_str = cal_date.strftime("%Y-%m-%d")
        try:
            aggs = client.get_grouped_daily_aggs(date_str)
            day_rows = []
            for a in aggs:
                if a.close is None or a.volume is None or a.volume == 0:
                    continue
                day_rows.append({
                    "ticker": a.ticker,
                    "date": date_str,
                    "close": float(a.close),
                    "volume": int(a.volume),
                    "dollar_volume": float(a.close) * int(a.volume),
                })
            if day_rows:
                rows.extend(day_rows)
                days_collected += 1
                print(f"  Day {days_collected}/{num_trading_days}: {date_str} ({len(day_rows)} tickers)")
        except Exception as e:
            print(f"  {date_str}: skip ({e})")

        cal_date -= timedelta(days=1)
        # No pacing — Polygon Starter unlimited. Restore time.sleep(13) here
        # if the project drops back to the free 5/min tier.

    df = pd.DataFrame(rows)
    _DV_HISTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_DV_HISTORY_CACHE, index=False)
    print(f"  Collected {len(df)} bars across {days_collected} trading days (cached)")
    return df


def compute_median_dollar_volume(history: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker median dollar-volume + observed-days count."""
    grouped = history.groupby("ticker")["dollar_volume"].agg(["median", "count"]).reset_index()
    grouped = grouped.rename(columns={
        "median": "median_dollar_volume",
        "count": "trading_days_observed",
    })
    return grouped


def fetch_fundamentals_quarter_counts_from_db() -> dict[str, int]:
    """Per-ticker quarter counts from our DuckDB fundamentals_pit table.

    Returns {ticker: quarter_count}. Empty dict if the table doesn't exist
    yet (first-ever run).
    """
    try:
        from src.db.schema import get_connection
        con = get_connection()
        try:
            df = con.execute(
                "SELECT ticker, COUNT(*) AS quarters FROM fundamentals_pit GROUP BY ticker"
            ).fetchdf()
        finally:
            con.close()
        return dict(zip(df["ticker"].astype(str), df["quarters"].astype(int)))
    except Exception as e:
        print(f"  WARNING: couldn't read fundamentals_pit ({e}); will fall back to SimFin bulk only")
        return {}


def fetch_fundamentals_quarter_counts_from_simfin() -> dict[str, int]:
    """Per-ticker quarter counts from SimFin's bulk income CSVs.

    Provides coverage for tickers we haven't yet ingested into our DB —
    answers "does SimFin track this ticker with enough history" without
    needing a re-ingestion pass first. This is the safety net that
    prevents the rebuild from dropping new IPO / new-to-universe tickers
    on a fundamentals technicality.
    """
    try:
        import simfin as sf
    except ImportError:
        return {}

    sf.set_api_key(settings.api_keys.simfin_api_key)
    sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))

    frames = []
    for label, loader in [
        ("general", sf.load_income),
        ("banks", sf.load_income_banks),
        ("insurance", sf.load_income_insurance),
    ]:
        try:
            df = loader(variant="quarterly", market="us")
        except Exception as e:
            print(f"  SimFin {label}: skip ({e})")
            continue
        if df is None or df.empty:
            continue
        df = df.reset_index()
        frames.append(df[["Ticker"]])

    if not frames:
        return {}
    union = pd.concat(frames, ignore_index=True)
    counts = union.groupby("Ticker").size()
    return dict(zip(counts.index.astype(str), counts.astype(int)))


def assign_tier(dv: float) -> str:
    for label, threshold in TIER_BUCKETS:
        if dv >= threshold:
            return label
    return "below_floor"


def load_existing_universe() -> dict[str, dict[str, str]]:
    """Read universe.csv into {ticker: row_dict} for sub_sector carryover."""
    path = settings.paths.universe_path
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return {row["ticker"]: row.to_dict() for _, row in df.iterrows()}


def main() -> None:
    min_median_dv = float(os.getenv("UNIVERSE_MIN_MEDIAN_DV", "10000000"))
    min_quarters = int(os.getenv("UNIVERSE_MIN_QUARTERS", "5"))
    num_trading_days = int(os.getenv("UNIVERSE_LOOKBACK_DAYS", "60"))
    out_path = Path(
        os.getenv("UNIVERSE_OUT")
        or settings.paths.universe_path.parent / "universe_strict.csv"
    )

    print(f"Building strict universe with:")
    print(f"  Median dollar-volume floor:      ${min_median_dv:,.0f}")
    print(f"  Minimum quarters of fundamentals: {min_quarters}")
    print(f"  Lookback trading days:            {num_trading_days}")
    print(f"  Output:                           {out_path}")
    print()

    existing = load_existing_universe()
    print(f"Existing universe: {len(existing)} tickers (kept for sub_sector carryover)\n")

    # --- Stage 1+2: Polygon listing + venue/suffix filter ---
    listings = fetch_all_us_common_stocks()
    n_raw = len(listings)
    # Drop rows with missing ticker (NaN can appear in cached CSV)
    listings = listings.dropna(subset=["ticker"]).copy()
    listings["ticker"] = listings["ticker"].astype(str)
    listings = listings[listings["primary_exchange"].isin(ALLOWED_EXCHANGES)].copy()
    listings = listings[~listings["ticker"].str.contains(r"\.|\-W|\-U|\-R", regex=True, na=False)]
    print(f"\nStage 2: NYSE/NASDAQ + suffix filter  -> {len(listings)} (from {n_raw})")

    # --- Stage 3: 60-day median dollar-volume ---
    history = fetch_dollar_volume_history(num_trading_days)
    dv_stats = compute_median_dollar_volume(history)
    listings = listings.merge(dv_stats, on="ticker", how="inner")
    n_before = len(listings)
    listings = listings[listings["median_dollar_volume"] >= min_median_dv].copy()

    # Require at least 70% of the lookback window to be observed — protects
    # against newly-listed tickers with only a handful of bars getting
    # promoted on what looks like a high median but is really a small sample.
    coverage_floor = num_trading_days * 0.7
    listings = listings[listings["trading_days_observed"] >= coverage_floor].copy()
    print(f"Stage 3: median ADV >= ${min_median_dv:,.0f} & coverage >= {coverage_floor:.0f}d -> {len(listings)} (from {n_before})")

    # --- Stage 4: fundamentals quality ---
    db_quarters = fetch_fundamentals_quarter_counts_from_db()
    simfin_quarters = fetch_fundamentals_quarter_counts_from_simfin()
    print(f"  DB has fundamentals for      {len(db_quarters)} tickers")
    print(f"  SimFin bulk has data for     {len(simfin_quarters)} tickers")

    def _max_quarters(t: str) -> int:
        return max(db_quarters.get(t, 0), simfin_quarters.get(t, 0))

    listings["quarters_available"] = listings["ticker"].apply(_max_quarters)
    n_before = len(listings)
    listings = listings[listings["quarters_available"] >= min_quarters].copy()
    print(f"Stage 4: >= {min_quarters} quarters of fundamentals  -> {len(listings)} (from {n_before})")

    # --- Stage 5: tier + sub_sector carryover ---
    listings = listings.sort_values("median_dollar_volume", ascending=False).copy()
    listings["market_cap_tier"] = listings["median_dollar_volume"].apply(assign_tier)

    def _sub_sector(t: str) -> str:
        row = existing.get(t)
        if row and isinstance(row.get("sub_sector"), str):
            return row["sub_sector"]
        return "uncategorized"

    listings["sub_sector"] = listings["ticker"].apply(_sub_sector)

    out = listings[["ticker", "name", "sub_sector", "market_cap_tier"]].copy()
    out.to_csv(out_path, index=False)
    print(f"\nWrote {len(out)} tickers to {out_path}")

    # --- Summary + diff vs existing universe.csv ---
    print("\n=== Universe Summary ===")
    print(f"Total tickers:           {len(out)}")
    print(f"Tier breakdown:")
    for tier, _ in TIER_BUCKETS:
        n = (out["market_cap_tier"] == tier).sum()
        print(f"  {tier:8s} {n:>5d}")

    new_set = set(out["ticker"])
    existing_set = set(existing.keys())
    preserved = len(new_set & existing_set)
    added = sorted(new_set - existing_set)
    dropped = sorted(existing_set - new_set)
    print(f"\nCarried over from existing universe:  {preserved}")
    print(f"Newly added:                          {len(added)}")
    print(f"Dropped:                              {len(dropped)}")
    if dropped:
        print(f"  Sample dropped: {', '.join(dropped[:25])}{'...' if len(dropped) > 25 else ''}")
    uncategorized = (out["sub_sector"] == "uncategorized").sum()
    print(f"\nNew tickers needing sub_sector mapping: {uncategorized}")


if __name__ == "__main__":
    main()
