"""Orchestrate a full universe rebuild: build -> enrich -> diff report.

This is the entry point the monthly scheduler will call. It chains the three
existing scripts and produces a single diff report that summarizes changes
relative to the live universe.csv.

The script is non-destructive: it writes `universe_strict.csv` but never
touches `universe.csv` itself. Promotion is a separate manual step (or a
later scheduler task once we trust the rebuild output).

Run
---
    cd backend && python -u -m scripts.rebuild_universe

Tunables — same env vars as build_universe.py + enrich_universe.py:
    UNIVERSE_MIN_MEDIAN_DV    default 10_000_000
    UNIVERSE_MIN_QUARTERS     default 5
    UNIVERSE_LOOKBACK_DAYS    default 60
    ENRICH_WORKERS            default 6  (passed through to yfinance fetch)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


def _run_step(name: str, func) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    t0 = time.time()
    func()
    print(f"\n[{name}] done in {time.time() - t0:.1f}s")


def step_build() -> None:
    from scripts.build_universe import main as build_main
    build_main()


def step_enrich() -> None:
    # enrich_universe.py reads/writes the same universe_strict.csv path that
    # build_universe.py writes (it operates on UNIVERSE_PATH.parent /
    # "universe_expanded.csv"). We need to point it at universe_strict.csv.
    import os
    strict_path = settings.paths.universe_path.parent / "universe_strict.csv"
    # The script uses the constant UNIVERSE_PATH = ... universe_expanded.csv at
    # module load time. Easiest path: pass via env var the script doesn't read,
    # so we monkey-patch via os.environ for the run.
    os.environ["UNIVERSE_PATH_OVERRIDE"] = str(strict_path)
    from scripts import enrich_universe
    # Temporarily redirect the module-level UNIVERSE_PATH
    original = enrich_universe.UNIVERSE_PATH
    enrich_universe.UNIVERSE_PATH = strict_path
    try:
        enrich_universe.main()
    finally:
        enrich_universe.UNIVERSE_PATH = original


def step_diff() -> None:
    """Compare universe_strict.csv against the live universe.csv."""
    live_path = settings.paths.universe_path
    strict_path = settings.paths.universe_path.parent / "universe_strict.csv"

    live = pd.read_csv(live_path)
    strict = pd.read_csv(strict_path)
    live_set = set(live["ticker"].astype(str))
    strict_set = set(strict["ticker"].astype(str))

    added = sorted(strict_set - live_set)
    removed = sorted(live_set - strict_set)
    kept = strict_set & live_set

    # Detect ticker re-tierings (same ticker, different market_cap_tier)
    retiered = []
    if not live.empty and not strict.empty:
        live_idx = live.set_index("ticker")
        strict_idx = strict.set_index("ticker")
        for t in kept:
            if t in live_idx.index and t in strict_idx.index:
                lt = live_idx.loc[t].get("market_cap_tier")
                st = strict_idx.loc[t].get("market_cap_tier")
                if lt != st:
                    retiered.append((t, lt, st))

    print(f"\nLive universe:    {len(live)} tickers ({live_path.name})")
    print(f"Strict universe:  {len(strict)} tickers ({strict_path.name})")
    print(f"\nKept:       {len(kept)}")
    print(f"Added:      {len(added)}")
    print(f"Removed:    {len(removed)}")
    print(f"Re-tiered:  {len(retiered)}")

    # Persist diff to JSON for the scheduler / downstream tooling
    diff_path = settings.paths.data_dir / "universe_rebuild_diff.json"
    diff_payload = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "live_count": int(len(live)),
        "strict_count": int(len(strict)),
        "added": added,
        "removed": removed,
        "retiered": [{"ticker": t, "from": str(a), "to": str(b)} for t, a, b in retiered],
    }
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    with open(diff_path, "w") as f:
        json.dump(diff_payload, f, indent=2, default=str)
    print(f"\nDiff JSON: {diff_path}")

    # Sub-sector distribution shift
    if not strict.empty:
        print("\nStrict universe sub_sector distribution (top 15):")
        counts = strict["sub_sector"].value_counts()
        for s, n in counts.head(15).items():
            print(f"  {s:24s} {n:>5d}")
        uncat = (strict["sub_sector"] == "uncategorized").sum()
        if uncat:
            print(f"  ... uncategorized: {uncat}")


def main() -> None:
    print("Universe rebuild pipeline")
    print(f"  Live universe path:   {settings.paths.universe_path}")
    print(f"  Strict output path:   {settings.paths.universe_path.parent / 'universe_strict.csv'}")
    print()

    _run_step("Step 1/3 — Build (filters)", step_build)
    _run_step("Step 2/3 — Enrich (sub_sector mapping)", step_enrich)
    _run_step("Step 3/3 — Diff report", step_diff)

    print("\n" + "=" * 70)
    print("  Universe rebuild complete")
    print("=" * 70)
    print(f"\nTo promote strict -> live, manually run:")
    print(f"  cp config/universe_strict.csv config/universe.csv")
    print(f"\n(After Phase 2 migration, this becomes a Postgres swap instead.)")


if __name__ == "__main__":
    main()
