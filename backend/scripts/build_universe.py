"""Build an expanded stock universe from Polygon's reference + grouped daily endpoints.

This script is non-destructive: it writes to `backend/config/universe_expanded.csv`
so you can diff it against the curated `universe.csv` before swapping.

Strategy
--------
1. Pull every active US common stock listing from Polygon's reference tickers
   endpoint (paginated, single bulk listing — no per-ticker rate limits).
2. Pull one recent trading day's grouped-daily aggregates (single API call,
   returns every US stock's OHLCV) to get a liquidity snapshot: dollar-volume
   = close * volume.
3. Filter on liquidity (default: avg dollar-volume >= $5M/day) and exchange
   (NYSE / NASDAQ only).
4. Tier each survivor by dollar-volume into mega / large / mid / small. We
   intentionally tier by liquidity rather than market cap because what
   actually constrains a retail account is whether you can fill an order —
   a low-float micro-cap with huge market cap is still untradable.
5. Preserve sub_sector labels for tickers already in `universe.csv`. New
   tickers default to "uncategorized" until manually curated (or until a
   sector-mapping pass is added).

Run
---
    cd backend && python -m scripts.build_universe

Optional flags via env vars:
    UNIVERSE_MIN_DOLLAR_VOLUME  default 5_000_000
    UNIVERSE_DATE               default = most recent weekday (YYYY-MM-DD)
    UNIVERSE_OUT                default = backend/config/universe_expanded.csv
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


# Liquidity tier thresholds (avg daily dollar-volume in USD).
TIER_BUCKETS = [
    ("mega", 1_000_000_000),   # >= $1B/day
    ("large", 100_000_000),    # $100M - $1B
    ("mid", 10_000_000),       # $10M - $100M
    ("small", 5_000_000),      # $5M - $10M (configurable floor)
]

# Polygon's MIC codes for the exchanges we'll keep. ARCX (NYSE Arca) hosts
# most ETFs and a few small-caps; we exclude it to keep the universe to
# operating companies. Add it back if you want ETFs in the universe.
ALLOWED_EXCHANGES = {"XNYS", "XNAS"}


def _most_recent_weekday() -> str:
    """Yesterday if it's a weekday, else last Friday. Polygon EOD lags ~1 day."""
    d = datetime.now() - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


_LISTINGS_CACHE = settings.paths.data_dir / "raw" / "polygon_listings_cache.csv"


def fetch_all_us_common_stocks(use_cache: bool = True) -> pd.DataFrame:
    """Page through /v3/reference/tickers for every active US common stock.

    Polygon's free tier caps at 5 calls/min, so we throttle to ~4/min (15s
    between page requests) to stay safely under. Expect ~6000-8000 results
    across 6-8 pages, so this stage takes ~90-120 seconds.

    Results are cached to disk because the listing universe changes slowly
    (new IPOs, delistings) — re-running the script during the same week
    skips the network round-trip entirely.
    """
    if use_cache and _LISTINGS_CACHE.exists():
        age_hours = (time.time() - _LISTINGS_CACHE.stat().st_mtime) / 3600
        if age_hours < 168:  # < 1 week old
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
        # First request uses params dict; subsequent uses next_url which already
        # encodes cursor — append apiKey since Polygon strips it from next_url.
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

        if url:
            # Throttle: ~4 calls/min stays under the 5/min free-tier ceiling.
            time.sleep(15)

    df = pd.DataFrame(rows).drop_duplicates(subset=["ticker"])
    _LISTINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(_LISTINGS_CACHE, index=False)
    print(f"  Reference listing returned {len(df)} active common stocks (cached)")
    return df


def fetch_dollar_volume_snapshot(date: str) -> pd.DataFrame:
    """One API call -> close * volume for every US stock on `date`."""
    from polygon import RESTClient

    client = RESTClient(api_key=settings.api_keys.polygon_api_key)

    print(f"Fetching grouped daily aggregates for {date}...")
    rows = []
    aggs = client.get_grouped_daily_aggs(date)
    for a in aggs:
        if a.close is None or a.volume is None:
            continue
        rows.append({
            "ticker": a.ticker,
            "close": float(a.close),
            "volume": int(a.volume),
            "dollar_volume": float(a.close) * int(a.volume),
        })
    df = pd.DataFrame(rows)
    print(f"  Grouped daily returned {len(df)} ticker bars")
    return df


def assign_tier(dv: float) -> str:
    for label, threshold in TIER_BUCKETS:
        if dv >= threshold:
            return label
    return "below_floor"


def load_existing_universe() -> dict[str, dict[str, str]]:
    """Read the curated universe.csv into {ticker: row_dict} for sub_sector reuse."""
    path = settings.paths.universe_path
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return {row["ticker"]: row.to_dict() for _, row in df.iterrows()}


def main() -> None:
    min_dv = float(os.getenv("UNIVERSE_MIN_DOLLAR_VOLUME", "5000000"))
    date = os.getenv("UNIVERSE_DATE") or _most_recent_weekday()
    out_path = Path(
        os.getenv("UNIVERSE_OUT")
        or settings.paths.universe_path.parent / "universe_expanded.csv"
    )

    existing = load_existing_universe()
    print(f"Existing universe: {len(existing)} tickers")

    listings = fetch_all_us_common_stocks()
    listings = listings[listings["primary_exchange"].isin(ALLOWED_EXCHANGES)].copy()
    print(f"  After NYSE/NASDAQ filter: {len(listings)}")

    # Drop SPACs, warrants, units, rights — Polygon marks these via ticker
    # suffix in the symbol itself (e.g. .WS, .U, .R) and via type, but type=CS
    # already filters most of it. Belt-and-suspenders pattern match here.
    listings = listings[~listings["ticker"].str.contains(r"\.|\-W|\-U|\-R", regex=True)]
    print(f"  After SPAC/warrant suffix filter: {len(listings)}")

    snapshot = fetch_dollar_volume_snapshot(date)
    merged = listings.merge(snapshot, on="ticker", how="inner")
    print(f"  Listings with price data on {date}: {len(merged)}")

    # Apply liquidity floor
    merged = merged[merged["dollar_volume"] >= min_dv].copy()
    merged = merged.sort_values("dollar_volume", ascending=False)
    print(f"  After ${min_dv:,.0f} dollar-volume floor: {len(merged)}")

    merged["market_cap_tier"] = merged["dollar_volume"].apply(assign_tier)

    # Carry over curated sub_sector labels; new entries get "uncategorized".
    def _sub_sector(t: str) -> str:
        row = existing.get(t)
        if row and isinstance(row.get("sub_sector"), str):
            return row["sub_sector"]
        return "uncategorized"

    merged["sub_sector"] = merged["ticker"].apply(_sub_sector)

    out = merged[["ticker", "name", "sub_sector", "market_cap_tier"]].copy()
    out.to_csv(out_path, index=False)
    print(f"\nWrote {len(out)} tickers to {out_path}")

    # Summary
    print("\n=== Summary ===")
    print(f"Total tickers:           {len(out)}")
    print(f"Tier breakdown:")
    for tier, _ in TIER_BUCKETS:
        n = (out["market_cap_tier"] == tier).sum()
        print(f"  {tier:8s} {n:>5d}")
    preserved = sum(1 for t in out["ticker"] if t in existing)
    new_count = len(out) - preserved
    dropped = [t for t in existing if t not in set(out["ticker"])]
    print(f"\nCarried over from existing universe:  {preserved}")
    print(f"Newly added:                          {new_count}")
    print(f"Dropped (failed liquidity filter):    {len(dropped)}")
    if dropped:
        print(f"  -> {', '.join(sorted(dropped)[:20])}{'...' if len(dropped) > 20 else ''}")
    uncategorized = (out["sub_sector"] == "uncategorized").sum()
    print(f"\nNew tickers needing sub_sector mapping: {uncategorized}")


if __name__ == "__main__":
    main()
