"""Data quality report: coverage, missing values, anomalies."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection
from src.db.state import load_universe_df
from config.settings import settings


def price_coverage_report() -> pd.DataFrame:
    """Report price data coverage per ticker."""
    con = get_connection()
    df = con.execute("""
        SELECT
            ticker,
            MIN(date) as first_date,
            MAX(date) as last_date,
            COUNT(*) as trading_days,
            COUNT(CASE WHEN adj_close IS NULL OR adj_close = 0 THEN 1 END) as null_prices,
            COUNT(CASE WHEN volume = 0 THEN 1 END) as zero_volume_days
        FROM prices
        GROUP BY ticker
        ORDER BY ticker
    """).fetchdf()
    con.close()

    # Expected trading days (approx 252/year * 10 years = ~2520)
    if not df.empty:
        df["years_of_data"] = (
            (pd.to_datetime(df["last_date"]) - pd.to_datetime(df["first_date"])).dt.days / 365.25
        ).round(1)

    return df


def fundamentals_coverage_report() -> pd.DataFrame:
    """Report fundamentals coverage per ticker."""
    con = get_connection()
    df = con.execute("""
        SELECT
            ticker,
            COUNT(*) as quarters,
            MIN(fiscal_period_end) as first_period,
            MAX(fiscal_period_end) as last_period,
            MIN(report_date) as first_report,
            MAX(report_date) as last_report,
            COUNT(CASE WHEN revenue IS NULL THEN 1 END) as null_revenue,
            COUNT(CASE WHEN eps_diluted IS NULL THEN 1 END) as null_eps
        FROM fundamentals_pit
        GROUP BY ticker
        ORDER BY ticker
    """).fetchdf()
    con.close()
    return df


def macro_coverage_report() -> pd.DataFrame:
    """Report macro data coverage per series."""
    con = get_connection()
    df = con.execute("""
        SELECT
            series_id,
            COUNT(*) as observations,
            MIN(date) as first_date,
            MAX(date) as last_date,
            COUNT(CASE WHEN value IS NULL THEN 1 END) as null_values
        FROM macro_data
        GROUP BY series_id
        ORDER BY series_id
    """).fetchdf()
    con.close()
    return df


def pit_validation() -> pd.DataFrame:
    """Check for potential future-looking bias in fundamentals.

    report_date should always be AFTER fiscal_period_end.
    Typical lag is 30-60 days.
    """
    con = get_connection()
    df = con.execute("""
        SELECT
            ticker,
            fiscal_period_end,
            report_date,
            report_date - fiscal_period_end as lag_days
        FROM fundamentals_pit
        WHERE report_date < fiscal_period_end
        ORDER BY ticker, fiscal_period_end
    """).fetchdf()
    con.close()

    if df.empty:
        print("  PIT validation: PASS (no report_date before fiscal_period_end)")
    else:
        print(f"  PIT validation: WARNING - {len(df)} rows have report_date before fiscal_period_end")

    return df


def generate_full_report() -> None:
    """Generate and print the full data quality report."""
    universe = load_universe_df()
    universe_tickers = set(universe["ticker"].tolist())

    print("=" * 70)
    print("DATA QUALITY REPORT")
    print("=" * 70)

    # --- Prices ---
    print("\n--- PRICE DATA ---")
    price_df = price_coverage_report()
    if price_df.empty:
        print("  NO PRICE DATA IN DATABASE")
    else:
        tickers_with_prices = set(price_df["ticker"].tolist())
        missing = universe_tickers - tickers_with_prices
        coverage_pct = len(tickers_with_prices & universe_tickers) / len(universe_tickers) * 100

        print(f"  Universe tickers: {len(universe_tickers)}")
        print(f"  Tickers with price data: {len(tickers_with_prices & universe_tickers)}")
        print(f"  Coverage: {coverage_pct:.1f}%")
        if missing:
            print(f"  Missing tickers: {sorted(missing)}")

        # Summary stats
        print(f"  Avg trading days per ticker: {price_df['trading_days'].mean():.0f}")
        print(f"  Avg years of data: {price_df['years_of_data'].mean():.1f}")
        short = price_df[price_df["years_of_data"] < 5]
        if not short.empty:
            print(f"  Tickers with <5 years: {short['ticker'].tolist()}")

        null_issues = price_df[price_df["null_prices"] > 0]
        if not null_issues.empty:
            print(f"  Tickers with null prices: {null_issues[['ticker', 'null_prices']].to_string(index=False)}")

    # --- Fundamentals ---
    print("\n--- FUNDAMENTALS DATA ---")
    fund_df = fundamentals_coverage_report()
    if fund_df.empty:
        print("  NO FUNDAMENTALS DATA IN DATABASE")
    else:
        tickers_with_fund = set(fund_df["ticker"].tolist())
        missing_fund = universe_tickers - tickers_with_fund
        fund_coverage = len(tickers_with_fund & universe_tickers) / len(universe_tickers) * 100

        print(f"  Tickers with fundamentals: {len(tickers_with_fund & universe_tickers)}")
        print(f"  Coverage: {fund_coverage:.1f}%")
        if missing_fund:
            print(f"  Missing tickers: {sorted(missing_fund)}")
        print(f"  Avg quarters per ticker: {fund_df['quarters'].mean():.1f}")

        low_quarters = fund_df[fund_df["quarters"] < 8]
        if not low_quarters.empty:
            print(f"  Tickers with <8 quarters: {low_quarters['ticker'].tolist()}")

    # --- PIT Validation ---
    print("\n--- POINT-IN-TIME VALIDATION ---")
    pit_issues = pit_validation()

    # --- Macro ---
    print("\n--- MACRO DATA ---")
    macro_df = macro_coverage_report()
    if macro_df.empty:
        print("  NO MACRO DATA IN DATABASE")
    else:
        for _, row in macro_df.iterrows():
            print(f"  {row['series_id']}: {row['observations']} obs ({row['first_date']} to {row['last_date']})")

    print("\n" + "=" * 70)
    print("END OF DATA QUALITY REPORT")
    print("=" * 70)


if __name__ == "__main__":
    generate_full_report()
