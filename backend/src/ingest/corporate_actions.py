"""Corporate actions verification: check that historical splits are correctly adjusted."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection

# Known major splits to verify against (post-split adjusted prices should be smooth)
KNOWN_SPLITS = [
    {"ticker": "NVDA", "date": "2024-06-10", "ratio": "10:1", "pre_split_approx": 1200, "post_split_approx": 120},
    {"ticker": "TSLA", "date": "2022-08-25", "ratio": "3:1", "pre_split_approx": 900, "post_split_approx": 300},
    {"ticker": "GOOGL", "date": "2022-07-18", "ratio": "20:1", "pre_split_approx": 2200, "post_split_approx": 110},
    {"ticker": "AMZN", "date": "2022-06-06", "ratio": "20:1", "pre_split_approx": 2400, "post_split_approx": 120},
    {"ticker": "SHOP", "date": "2022-06-29", "ratio": "10:1", "pre_split_approx": 700, "post_split_approx": 35},
]


def verify_split_adjustment(ticker: str, split_date: str, post_split_approx: float) -> dict:
    """Verify that adjusted prices around a split date are smooth (no discontinuity).

    If yfinance auto_adjust worked correctly, the adjusted close before and after
    the split should be roughly continuous (no 10x jump).
    """
    con = get_connection()

    # Get prices around the split date
    result = con.execute("""
        SELECT date, adj_close
        FROM prices
        WHERE ticker = $1
          AND date BETWEEN CAST($2 AS DATE) - INTERVAL 5 DAY
                        AND CAST($2 AS DATE) + INTERVAL 5 DAY
        ORDER BY date
    """, [ticker, split_date]).fetchdf()
    con.close()

    if result.empty or len(result) < 2:
        return {
            "ticker": ticker,
            "split_date": split_date,
            "status": "NO_DATA",
            "detail": "Not enough price data around split date",
        }

    # Check for discontinuity: max day-over-day change should be < 50%
    result["pct_change"] = result["adj_close"].pct_change().abs()
    max_jump = result["pct_change"].max()

    # Also check that the post-split price is in a reasonable range
    post_prices = result[result["date"].astype(str) >= split_date]["adj_close"]
    if post_prices.empty:
        return {
            "ticker": ticker,
            "split_date": split_date,
            "status": "NO_POST_DATA",
            "detail": "No data after split date",
        }

    avg_post = post_prices.mean()

    # Adjusted prices should be in the post-split range (not pre-split)
    # Allow 2x tolerance for normal price movement
    price_reasonable = avg_post < post_split_approx * 3

    if max_jump > 0.50:
        status = "FAIL_DISCONTINUITY"
        detail = f"Max day-over-day jump: {max_jump:.1%} (>50%, split may not be adjusted)"
    elif not price_reasonable:
        status = "FAIL_PRICE_RANGE"
        detail = f"Avg post-split price ${avg_post:.2f} seems too high (expected ~${post_split_approx})"
    else:
        status = "PASS"
        detail = f"Max jump: {max_jump:.1%}, avg post-split price: ${avg_post:.2f}"

    return {
        "ticker": ticker,
        "split_date": split_date,
        "status": status,
        "detail": detail,
    }


def verify_all_splits() -> pd.DataFrame:
    """Run split verification for all known splits."""
    print("Verifying corporate action adjustments...")
    results = []
    for split in KNOWN_SPLITS:
        result = verify_split_adjustment(
            split["ticker"],
            split["date"],
            split["post_split_approx"],
        )
        print(f"  {result['ticker']} ({split['ratio']} on {split['date']}): {result['status']}")
        if result["status"] != "PASS":
            print(f"    {result['detail']}")
        results.append(result)

    return pd.DataFrame(results)


if __name__ == "__main__":
    df = verify_all_splits()
    passed = (df["status"] == "PASS").sum()
    total = len(df)
    print(f"\nSplit verification: {passed}/{total} passed")
