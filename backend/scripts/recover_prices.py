"""Recover price history for tickers damaged by the bulk yfinance rate-limit incident.

Reads `data/damaged_tickers.json` (the list wiped from DB) and re-fetches each
ticker via yfinance bulk download in small batches with pacing between batches.
Uses the patched fetch_yfinance_bulk which now drops NaN-only ticker frames
before storing, so a transient rate-limit on a sub-batch can no longer clobber
existing good data on retry.

Run
---
    cd backend && python -u -m scripts.recover_prices

Tunables via env vars:
    RECOVER_BATCH_SIZE    default 80   (tickers per yfinance bulk call)
    RECOVER_PAUSE_SEC     default 30   (sleep between batches)
    RECOVER_START         default 2016-01-01
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.ingest.prices import fetch_yfinance_bulk, store_prices


def main() -> None:
    batch_size = int(os.getenv("RECOVER_BATCH_SIZE", "80"))
    pause = float(os.getenv("RECOVER_PAUSE_SEC", "30"))
    start = os.getenv("RECOVER_START", "2016-01-01")

    damaged_path = settings.paths.data_dir / "damaged_tickers.json"
    if not damaged_path.exists():
        print(f"ERROR: {damaged_path} not found. Run the wipe step first.")
        return
    with open(damaged_path) as f:
        damaged: list[str] = json.load(f)

    print(f"Recovering {len(damaged)} tickers in batches of {batch_size}")
    print(f"  Pacing: {pause}s between batches")
    print(f"  Start date: {start}")

    end = datetime.now().strftime("%Y-%m-%d")
    n_batches = (len(damaged) + batch_size - 1) // batch_size

    total_recovered = 0
    failed_again: list[str] = []

    for i in range(n_batches):
        chunk = damaged[i * batch_size : (i + 1) * batch_size]
        print(f"\n--- Batch {i + 1}/{n_batches} ({len(chunk)} tickers) ---")

        try:
            df = fetch_yfinance_bulk(chunk, start=start, end=end)
        except Exception as e:
            print(f"  Batch {i + 1} crashed: {e}")
            failed_again.extend(chunk)
            continue

        if df.empty:
            print(f"  Batch {i + 1}: no data returned (likely all rate-limited)")
            failed_again.extend(chunk)
        else:
            recovered_in_batch = set(df["ticker"].unique())
            missed_in_batch = set(chunk) - recovered_in_batch
            print(f"  Batch {i + 1}: recovered {len(recovered_in_batch)}, missed {len(missed_in_batch)}")
            total_recovered += len(recovered_in_batch)
            failed_again.extend(missed_in_batch)
            store_prices(df)

        if i < n_batches - 1:
            print(f"  Pausing {pause}s before next batch...")
            time.sleep(pause)

    print(f"\n=== Recovery summary ===")
    print(f"  Total recovered:  {total_recovered}")
    print(f"  Still missing:    {len(failed_again)}")

    # Persist the still-missing list so we can run another pass later
    if failed_again:
        out_path = settings.paths.data_dir / "damaged_tickers_remaining.json"
        with open(out_path, "w") as f:
            json.dump(sorted(set(failed_again)), f)
        print(f"  Saved remaining list to {out_path}")


if __name__ == "__main__":
    main()
