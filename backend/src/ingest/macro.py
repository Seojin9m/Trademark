"""Macro data ingestion from FRED API."""

import sys
from pathlib import Path

import pandas as pd
from fredapi import Fred

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection, init_db
from config.settings import settings

# Key macro series for tech stock context
MACRO_SERIES = {
    "DFF": "Federal Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Spread (yield curve)",
    "VIXCLS": "VIX (volatility index)",
    "CPIAUCSL": "CPI (inflation)",
    "UNRATE": "Unemployment Rate",
}


def fetch_fred_series(
    series_ids: list[str] | None = None,
    start: str = "2016-01-01",
) -> pd.DataFrame:
    """Download macro series from FRED."""
    fred = Fred(api_key=settings.api_keys.fred_api_key)

    if series_ids is None:
        series_ids = list(MACRO_SERIES.keys())

    records = []
    for series_id in series_ids:
        try:
            data = fred.get_series(series_id, observation_start=start)
            if data is not None and not data.empty:
                df = data.reset_index()
                df.columns = ["date", "value"]
                df["series_id"] = series_id
                df = df.dropna(subset=["value"])
                records.append(df[["series_id", "date", "value"]])
                print(f"  {series_id} ({MACRO_SERIES.get(series_id, '')}): {len(df)} observations")
        except Exception as e:
            print(f"  WARNING: Failed to fetch {series_id}: {e}")

    if not records:
        return pd.DataFrame()

    result = pd.concat(records, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"]).dt.date
    print(f"Total macro data: {len(result)} rows across {result['series_id'].nunique()} series")
    return result


def store_macro(df: pd.DataFrame) -> None:
    """Store macro data into DuckDB."""
    if df.empty:
        print("No macro data to store.")
        return

    con = get_connection()

    con.register("macro_df", df)
    con.execute("DELETE FROM macro_data")
    con.execute("""
        INSERT INTO macro_data
        SELECT series_id, date, value FROM macro_df
    """)

    row_count = con.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
    con.close()
    print(f"Stored in DuckDB: {row_count} macro data rows")


def ingest_macro() -> None:
    """Full macro data ingestion pipeline."""
    init_db()
    df = fetch_fred_series()
    store_macro(df)


if __name__ == "__main__":
    ingest_macro()
