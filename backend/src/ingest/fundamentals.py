"""Fundamentals ingestion from Simfin free tier with PIT tagging."""

import sys
from pathlib import Path

import pandas as pd
import simfin as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection, init_db
from config.settings import settings


def fetch_simfin_income() -> pd.DataFrame:
    """Download quarterly income statement data from Simfin free tier."""
    sf.set_api_key(settings.api_keys.simfin_api_key)
    sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))

    print("Downloading Simfin quarterly income statements...")
    df = sf.load_income(variant="quarterly", market="us")

    if df is None or df.empty:
        print("WARNING: Simfin returned empty income data")
        return pd.DataFrame()

    # Reset multi-index (Ticker, SimFinId, FiscalYear, FiscalPeriod)
    df = df.reset_index()
    print(f"  Raw Simfin income rows: {len(df)}")
    return df


def fetch_simfin_balance() -> pd.DataFrame:
    """Download quarterly balance sheet data from Simfin free tier."""
    sf.set_api_key(settings.api_keys.simfin_api_key)
    sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))

    print("Downloading Simfin quarterly balance sheets...")
    df = sf.load_balance(variant="quarterly", market="us")

    if df is None or df.empty:
        print("WARNING: Simfin returned empty balance data")
        return pd.DataFrame()

    df = df.reset_index()
    print(f"  Raw Simfin balance rows: {len(df)}")
    return df


def build_pit_fundamentals(income_df: pd.DataFrame) -> pd.DataFrame:
    """Build point-in-time fundamentals table from Simfin income data.

    PIT key: use 'Publish Date' (when the filing was made public) as report_date.
    If Publish Date is missing, fall back to Fiscal Period end + 60 days (conservative).
    """
    # Load universe tickers
    universe = pd.read_csv(settings.paths.universe_path)["ticker"].tolist()

    # Filter to universe tickers only
    df = income_df[income_df["Ticker"].isin(universe)].copy()
    print(f"  Universe-filtered income rows: {len(df)}")

    if df.empty:
        return pd.DataFrame()

    # Simfin columns:
    #   "Report Date" = fiscal period end date (e.g., 2024-06-30)
    #   "Publish Date" = when filing became public (PIT date)
    #   "Fiscal Period" = "Q1", "Q2", "Q3", "Q4" (NOT a date)
    #   "Fiscal Year" = integer year

    # fiscal_period_end = Report Date (the end of the fiscal quarter)
    df["fiscal_period_end"] = pd.to_datetime(df["Report Date"], errors="coerce")

    # PIT report_date = Publish Date (when data became publicly available)
    if "Publish Date" in df.columns and df["Publish Date"].notna().any():
        df["report_date"] = pd.to_datetime(df["Publish Date"], errors="coerce")
        # Fall back to fiscal_period_end + 60 days where Publish Date is missing
        mask = df["report_date"].isna()
        df.loc[mask, "report_date"] = df.loc[mask, "fiscal_period_end"] + pd.Timedelta(days=60)
    else:
        # Conservative fallback: assume 60-day lag from period end
        df["report_date"] = df["fiscal_period_end"] + pd.Timedelta(days=60)
        print("  WARNING: No Publish Date found, using fiscal period end + 60 days as PIT proxy")

    # Build the output table
    col_map = {
        "Ticker": "ticker",
        "Revenue": "revenue",
        "Gross Profit": "gross_profit",
        "Operating Income (Loss)": "operating_income",
        "Net Income": "net_income",
    }

    # Find available columns
    available = {k: v for k, v in col_map.items() if k in df.columns}
    result = df.rename(columns=available)

    # Compute EPS if shares data available
    if "net_income" in result.columns and "Shares (Diluted)" in df.columns:
        result["eps_diluted"] = result["net_income"] / df["Shares (Diluted)"]
        result["shares_outstanding"] = df["Shares (Diluted)"]
    elif "net_income" in result.columns and "Shares (Basic)" in df.columns:
        result["eps_diluted"] = result["net_income"] / df["Shares (Basic)"]
        result["shares_outstanding"] = df["Shares (Basic)"]
    else:
        result["eps_diluted"] = None
        result["shares_outstanding"] = None

    # Select final columns
    final_cols = [
        "ticker", "fiscal_period_end", "report_date",
        "revenue", "gross_profit", "operating_income", "net_income",
        "eps_diluted", "shares_outstanding",
    ]
    for col in final_cols:
        if col not in result.columns:
            result[col] = None

    result = result[final_cols].copy()
    result["fiscal_period_end"] = pd.to_datetime(result["fiscal_period_end"]).dt.date
    result["report_date"] = pd.to_datetime(result["report_date"]).dt.date

    # Drop rows without valid dates
    result = result.dropna(subset=["ticker", "report_date"])

    # Deduplicate: keep latest report_date per ticker + fiscal_period_end
    result = result.sort_values("report_date").drop_duplicates(
        subset=["ticker", "fiscal_period_end"], keep="last"
    )

    print(f"  PIT fundamentals: {len(result)} rows for {result['ticker'].nunique()} tickers")
    return result


def store_fundamentals(df: pd.DataFrame) -> None:
    """Store PIT fundamentals into DuckDB."""
    if df.empty:
        print("No fundamentals to store.")
        return

    con = get_connection()

    con.register("fund_df", df)
    con.execute("DELETE FROM fundamentals_pit")
    con.execute("""
        INSERT INTO fundamentals_pit
        SELECT ticker, fiscal_period_end, report_date,
               revenue, gross_profit, operating_income, net_income,
               eps_diluted, shares_outstanding
        FROM fund_df
    """)

    row_count = con.execute("SELECT COUNT(*) FROM fundamentals_pit").fetchone()[0]
    ticker_count = con.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals_pit").fetchone()[0]
    con.close()

    print(f"Stored in DuckDB: {row_count} fundamentals rows, {ticker_count} tickers")


def ingest_fundamentals() -> None:
    """Full fundamentals ingestion pipeline."""
    init_db()
    income_df = fetch_simfin_income()
    if income_df.empty:
        return
    pit_df = build_pit_fundamentals(income_df)
    store_fundamentals(pit_df)


if __name__ == "__main__":
    ingest_fundamentals()
