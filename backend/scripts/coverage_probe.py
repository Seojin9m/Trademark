"""Probe SimFin & yfinance coverage of the expanded universe.

Answers the question: "If we swapped universe.csv -> universe_expanded.csv,
how many tickers would actually have usable fundamentals data?"

Uses SimFin's bulk income datasets (general + banks + insurance — same union
as ingest/fundamentals.py) because that's the project's primary fundamentals
source. Cheap to run: SimFin caches the bulk CSVs locally, so re-runs read
from disk after the first download.

Run
---
    cd backend && python -u -m scripts.coverage_probe
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


# Match the ingestion pipeline's quality threshold: <5 quarters can't compute
# YoY, so SimFin coverage of fewer than that quarters effectively forces a
# yfinance fallback (or an exclusion).
_MIN_QUARTERS_FOR_USABLE = 5


def load_simfin_income_master() -> pd.DataFrame:
    """Load SimFin bulk quarterly income (general+banks+insurance) -> DataFrame.

    Mirrors fundamentals.fetch_simfin_income() but returns the raw union so we
    can count quarters per ticker. This downloads the bulk CSV on first run
    (one-time, ~30 sec); subsequent runs read from cache.
    """
    import simfin as sf

    sf.set_api_key(settings.api_keys.simfin_api_key)
    sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))

    frames = []
    for label, loader in [
        ("general", sf.load_income),
        ("banks", sf.load_income_banks),
        ("insurance", sf.load_income_insurance),
    ]:
        print(f"  Loading SimFin {label}...")
        try:
            df = loader(variant="quarterly", market="us")
        except Exception as e:
            print(f"    SKIP ({e})")
            continue
        if df is None or df.empty:
            continue
        df = df.reset_index()
        frames.append(df[["Ticker", "Report Date"]])

    if not frames:
        return pd.DataFrame(columns=["Ticker", "Report Date"])
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    expanded = pd.read_csv(settings.paths.universe_path.parent / "universe_expanded.csv")
    universe = set(expanded["ticker"].tolist())
    print(f"Expanded universe: {len(universe)} tickers")

    print("\nLoading SimFin bulk quarterly income (this is cached after first run)...")
    simfin = load_simfin_income_master()
    if simfin.empty:
        print("ERROR: SimFin returned no data. Check API key.")
        return

    # Quarter counts per ticker
    counts = simfin.groupby("Ticker").size().rename("quarters")
    simfin_tickers = set(counts.index)

    in_simfin = universe & simfin_tickers
    missing = universe - simfin_tickers
    enough_quarters = set(counts[counts >= _MIN_QUARTERS_FOR_USABLE].index) & universe

    pct_in = len(in_simfin) / len(universe) * 100
    pct_usable = len(enough_quarters) / len(universe) * 100

    print(f"\n=== SimFin Coverage of Expanded Universe ===")
    print(f"  Tickers in SimFin:                       {len(in_simfin):>5d} / {len(universe)} ({pct_in:.1f}%)")
    print(f"  Tickers with >= {_MIN_QUARTERS_FOR_USABLE} quarters (usable): {len(enough_quarters):>5d} / {len(universe)} ({pct_usable:.1f}%)")
    print(f"  Tickers missing from SimFin:             {len(missing):>5d}")

    # Drill into missing by tier
    if missing:
        miss_df = expanded[expanded["ticker"].isin(missing)]
        print(f"\n  Missing breakdown by liquidity tier:")
        for tier, n in miss_df["market_cap_tier"].value_counts().items():
            print(f"    {tier:8s} {n:>5d}")

        sample = sorted(miss_df.head(20)["ticker"].tolist())
        print(f"  Sample missing tickers: {', '.join(sample)}")

    # Coverage by tier (the more useful breakdown)
    print(f"\n  Coverage by liquidity tier:")
    for tier in ["mega", "large", "mid", "small"]:
        tier_set = set(expanded[expanded["market_cap_tier"] == tier]["ticker"])
        if not tier_set:
            continue
        in_t = len(tier_set & enough_quarters)
        pct_t = in_t / len(tier_set) * 100
        print(f"    {tier:8s} {in_t:>5d} / {len(tier_set):>5d} usable ({pct_t:5.1f}%)")

    # Coverage by sub_sector — find sub_sectors that are heavily uncovered
    print(f"\n  Worst-covered sub_sectors (>=20 tickers, sorted by % usable):")
    coverage_by_sector = []
    for sub, group in expanded.groupby("sub_sector"):
        if len(group) < 20:
            continue
        tickers_in_group = set(group["ticker"])
        usable = len(tickers_in_group & enough_quarters)
        coverage_by_sector.append((sub, len(group), usable, usable / len(group) * 100))
    coverage_by_sector.sort(key=lambda x: x[3])
    for sub, total, usable, pct in coverage_by_sector[:10]:
        print(f"    {sub:24s} {usable:>5d} / {total:>5d} usable ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
