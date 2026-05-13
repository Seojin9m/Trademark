"""Port portfolio_state.json + universe.csv into Postgres tables.

One-shot script run during Phase 2.5. After this, the app reads/writes
through the state helpers and the file copies are kept only as a
DuckDB-mode fallback.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Force postgres for save_portfolio_state to write to the DB
os.environ["DB_BACKEND"] = "postgres"

from config.settings import settings
from src.db.state import save_portfolio_state


def main() -> None:
    # ---- portfolio_state.json -> portfolio_state table ----
    with open(settings.paths.portfolio_state_path) as f:
        state = json.load(f)
    save_portfolio_state(state)
    print(
        f"portfolio_state ported: {len(state.get('positions', []))} positions, "
        f"cash={state.get('cash', 0)}"
    )

    # ---- universe.csv -> universe table ----
    df = pd.read_csv(settings.paths.universe_path)
    print(f"universe CSV: {len(df)} tickers")
    cols = ["ticker", "name", "sub_sector", "market_cap_tier"]
    payload = df.reindex(columns=cols).copy()

    buf = io.StringIO()
    payload.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL_DIRECT"))
    with conn.cursor() as cur:
        cur.execute("TRUNCATE universe")
        cur.copy_expert(
            "COPY universe (ticker, name, sub_sector, market_cap_tier) "
            "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
            buf,
        )
        cur.execute("SELECT COUNT(*) FROM universe")
        n = cur.fetchone()[0]
    conn.commit()
    conn.close()
    print(f"universe table reloaded: {n} rows")


if __name__ == "__main__":
    main()
