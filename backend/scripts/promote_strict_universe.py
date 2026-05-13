"""Promote universe_strict.csv to the live universe.

What this does
--------------
1. Reads universe_strict.csv (built by build_universe.py)
2. Reads current portfolio holdings (from portfolio_state)
3. Adds any holding missing from strict (the "never-drop-what-we-own" rule)
4. Writes the result to universe.csv (backing up the existing file first)
5. TRUNCATE + COPY into the Postgres universe table

Re-runnable. The same script is what the monthly rebuild cron will call.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config.settings import settings
from src.db.state import load_portfolio_state


# Holdings we add back even if the strict filter would drop them. Tier and
# sub_sector are best-effort fallbacks; the curated existing universe
# values take precedence whenever available.
HOLDING_FALLBACKS = {
    "TSM":  {"name": "Taiwan Semiconductor Manufacturing", "sub_sector": "semiconductors",   "market_cap_tier": "mega", "risk_tier": "standard"},
}

# Columns the live universe table + CSV expect, in order. risk_tier is the
# main-added column for trading-risk classification; we default to "standard"
# unless the existing universe row has a more specific value.
UNIVERSE_COLS = ["ticker", "name", "sub_sector", "market_cap_tier", "risk_tier"]


def main() -> None:
    cfg_dir = settings.paths.universe_path.parent
    strict_path = cfg_dir / "universe_strict.csv"
    live_path = cfg_dir / "universe.csv"

    if not strict_path.exists():
        raise SystemExit(f"Strict universe not found: {strict_path}. Run build_universe.py first.")

    strict = pd.read_csv(strict_path)
    print(f"strict universe:           {len(strict):,} tickers")

    # --- Holdings ∪ strict ---
    state = load_portfolio_state()
    holdings = sorted({p["ticker"] for p in state.get("positions", []) if p.get("ticker")})
    print(f"portfolio holdings:        {len(holdings)}")

    strict_set = set(strict["ticker"].astype(str))
    missing_holdings = [t for t in holdings if t not in strict_set]
    print(f"holdings missing from strict: {missing_holdings}")

    # Source rows for missing holdings: prefer the existing live universe row
    # if we have it, fall back to HOLDING_FALLBACKS, else fabricate.
    existing = pd.read_csv(live_path) if live_path.exists() else pd.DataFrame(columns=["ticker", "name", "sub_sector", "market_cap_tier"])
    existing_by_ticker = {row["ticker"]: row for _, row in existing.iterrows()}

    additions = []
    for t in missing_holdings:
        if t in existing_by_ticker:
            row = existing_by_ticker[t]
            additions.append({
                "ticker": t,
                "name": row.get("name", t),
                "sub_sector": row.get("sub_sector", "uncategorized"),
                "market_cap_tier": row.get("market_cap_tier", "large"),
                "risk_tier": row.get("risk_tier", "standard"),
            })
            print(f"  + {t}: from current universe.csv")
        elif t in HOLDING_FALLBACKS:
            additions.append({"ticker": t, **HOLDING_FALLBACKS[t]})
            print(f"  + {t}: from HOLDING_FALLBACKS")
        else:
            additions.append({
                "ticker": t, "name": t,
                "sub_sector": "uncategorized", "market_cap_tier": "large",
                "risk_tier": "standard",
            })
            print(f"  + {t}: fabricated default (consider adding to HOLDING_FALLBACKS)")

    if additions:
        merged = pd.concat([strict, pd.DataFrame(additions)], ignore_index=True)
    else:
        merged = strict.copy()

    # build_universe.py doesn't produce risk_tier yet — seed it as "standard"
    # for every row coming from the strict CSV, so the column is fully
    # populated after the swap.
    if "risk_tier" not in merged.columns:
        merged["risk_tier"] = "standard"
    else:
        merged["risk_tier"] = merged["risk_tier"].fillna("standard")

    print(f"\nfinal universe size:       {len(merged):,} tickers")

    # --- Backup existing universe.csv ---
    if live_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = cfg_dir / f"universe_pre_strict_{ts}.csv"
        shutil.copy(live_path, backup_path)
        print(f"backup created:            {backup_path.name}")

    # --- Write live universe.csv ---
    merged.to_csv(live_path, index=False)
    print(f"wrote live universe.csv:   {live_path}")

    # --- Postgres swap ---
    payload = merged.reindex(columns=UNIVERSE_COLS).copy()

    buf = io.StringIO()
    payload.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL_DIRECT"))
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE universe")
            cur.copy_expert(
                f"COPY universe ({', '.join(UNIVERSE_COLS)}) "
                "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
            cur.execute("SELECT COUNT(*) FROM universe")
            n = cur.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"\nPostgres universe table:   {n:,} rows (atomic TRUNCATE + COPY)")
    print("\nDone. Promotion successful.")


if __name__ == "__main__":
    main()
