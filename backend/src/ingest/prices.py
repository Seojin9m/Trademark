"""Price ingestion: yfinance for historical backfill, Polygon.io for live EOD."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection, init_db
from config.settings import settings


def load_universe() -> list[str]:
    """Load ticker list from universe CSV."""
    df = pd.read_csv(settings.paths.universe_path)
    return df["ticker"].tolist()


def fetch_yfinance_bulk(
    tickers: list[str],
    start: str = "2016-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Download historical daily OHLCV from yfinance for all tickers.

    Uses adjusted close prices (split + dividend adjusted).
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    print(f"Downloading {len(tickers)} tickers from yfinance ({start} to {end})...")

    # yfinance bulk download
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        threads=True,
        progress=True,
    )

    if raw.empty:
        print("WARNING: yfinance returned empty DataFrame")
        return pd.DataFrame()

    # yfinance returns MultiIndex columns: (Price, Ticker)
    # Melt into long format: ticker, date, open, high, low, close, volume
    records = []
    for ticker in tickers:
        try:
            ticker_data = raw.xs(ticker, level="Ticker", axis=1)
            if ticker_data.empty:
                print(f"  WARNING: No data for {ticker}")
                continue

            df = ticker_data.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]

            # Rename 'price' or 'date' column
            if "date" not in df.columns and "Date" in df.columns:
                df = df.rename(columns={"Date": "date"})

            df["ticker"] = ticker
            df["adj_close"] = df["close"]  # auto_adjust=True means close IS adjusted

            records.append(df[["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"]])
        except (KeyError, Exception) as e:
            print(f"  WARNING: Failed to process {ticker}: {e}")
            continue

    if not records:
        return pd.DataFrame()

    result = pd.concat(records, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"]).dt.date
    result["volume"] = result["volume"].fillna(0).astype("int64")

    print(f"Downloaded {len(result)} total price rows for {result['ticker'].nunique()} tickers")
    return result


def check_eod_data_exists(min_tickers: int = 50) -> tuple[bool, int, str | None]:
    """Check if recent EOD price data already exists in DuckDB.

    Looks at the most recent date present in the prices table.
    Considers data 'current' if:
      - The most recent date is within the last 5 calendar days (covers weekends/holidays)
      - At least min_tickers have data for that date

    Returns (exists, ticker_count, latest_date).
    """
    con = get_connection()
    row = con.execute("""
        SELECT MAX(date) as latest_date, COUNT(DISTINCT ticker) as ticker_count
        FROM prices
        WHERE date >= CAST(CURRENT_DATE AS DATE) - INTERVAL '5 days'
          AND date < CAST(CURRENT_DATE AS DATE)
    """).fetchone()
    con.close()

    if not row or row[0] is None:
        return (False, 0, None)

    latest_date = str(row[0])
    count = int(row[1]) if row[1] else 0
    return (count >= min_tickers, count, latest_date)


def store_prices(df: pd.DataFrame) -> None:
    """Insert price data into DuckDB, replacing existing rows on conflict."""
    if df.empty:
        print("No data to store.")
        return

    con = get_connection()

    # Delete existing data for these tickers/dates, then insert
    # Using a temp table approach for upsert
    con.execute("CREATE TEMP TABLE prices_staging AS SELECT * FROM prices WHERE 1=0")
    con.register("prices_df", df)
    con.execute("""
        INSERT INTO prices_staging
        SELECT ticker, date, open, high, low, close, volume, adj_close
        FROM prices_df
    """)

    # Delete overlapping rows then insert
    con.execute("""
        DELETE FROM prices
        WHERE (ticker, date) IN (SELECT ticker, date FROM prices_staging)
    """)
    con.execute("INSERT INTO prices SELECT * FROM prices_staging")
    con.execute("DROP TABLE prices_staging")

    row_count = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    ticker_count = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
    con.close()

    print(f"Stored in DuckDB: {row_count} total rows, {ticker_count} tickers")


def fetch_polygon_eod(tickers: list[str], date: str | None = None) -> pd.DataFrame:
    """Fetch single-day EOD data from Polygon.io free tier.

    Rate limit: 5 calls/min. For 75 tickers, this takes ~15 minutes.
    """
    import time
    from polygon import RESTClient

    client = RESTClient(api_key=settings.api_keys.polygon_api_key)

    if date is None:
        # Use most recent trading day
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    records = []
    for i, ticker in enumerate(tickers):
        try:
            aggs = client.get_aggs(ticker, 1, "day", date, date)
            if aggs:
                agg = aggs[0]
                records.append({
                    "ticker": ticker,
                    "date": date,
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": int(agg.volume) if agg.volume else 0,
                    "adj_close": agg.close,  # Polygon returns adjusted by default
                })
        except Exception as e:
            print(f"  WARNING: Polygon failed for {ticker}: {e}")

        # Rate limit: 5 calls/min = 1 call per 12 seconds
        if (i + 1) % 5 == 0 and i < len(tickers) - 1:
            print(f"  Fetched {i + 1}/{len(tickers)}, pausing for rate limit...")
            time.sleep(61)  # Wait 61 seconds after every 5 calls

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    print(f"Polygon EOD: {len(df)} tickers fetched for {date}")
    return df


def backfill_historical() -> None:
    """One-time historical backfill using yfinance (10 years)."""
    init_db()
    tickers = load_universe()

    # Add benchmarks
    benchmarks = [settings.primary_benchmark, settings.secondary_benchmark]
    all_tickers = tickers + [b for b in benchmarks if b not in tickers]

    df = fetch_yfinance_bulk(all_tickers, start="2016-01-01")
    store_prices(df)


if __name__ == "__main__":
    backfill_historical()
