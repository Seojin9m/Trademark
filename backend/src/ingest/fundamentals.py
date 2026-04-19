"""Fundamentals ingestion from Simfin with yfinance fallback and PIT tagging."""

import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import simfin as sf
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection, init_db
from config.settings import settings

# Yahoo's quarterly_income_stmt labels for each field we need. Try a couple
# aliases per field because Yahoo occasionally renames rows.
_YF_FIELD_ALIASES = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": [
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    ],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income"],
    "eps_diluted": ["Diluted EPS", "Basic EPS"],
    "shares_diluted": ["Diluted Average Shares", "Basic Average Shares"],
}

# PIT lag proxy for yfinance (Yahoo only exposes period-end, not publish date).
# 50 days matches the convention used for Simfin Publish-Date fallback and is
# conservative enough to cover typical 10-Q filing windows.
_YF_PIT_LAG_DAYS = 50

# Thresholds for routing a ticker off Simfin and onto the yfinance fallback.
# Simfin free-tier has uneven per-ticker coverage (e.g. AEP/WFC/PGR arrive
# with just 1 quarter, CB arrives ~2 years behind the rest of the dataset).
#
# We need two checks:
#   1. Fewer than 5 quarters -> can't compute YoY (needs Q0 and Q-4).
#   2. Newest quarter lags the dataset's overall newest quarter by more than
#      ~3 quarters -> this ticker has silently fallen off Simfin's refresh.
#
# The staleness check is RELATIVE (vs the dataset newest), not ABSOLUTE (vs
# today), because Simfin's bulk data is always a quarter or two behind real
# time — an absolute "newest < today - 180d" check would flag every ticker.
_MIN_SIMFIN_QUARTERS = 5
_MAX_STALENESS_BEHIND_DATASET_DAYS = 270


def fetch_simfin_income() -> pd.DataFrame:
    """Download quarterly income statements from all three Simfin datasets.

    Simfin splits financial-statement data into general / banks / insurance
    because the income-statement structure is fundamentally different (banks
    have net interest income, insurers have claims & losses, etc.). Loading
    only the general dataset silently drops every bank and insurance company,
    so we union all three here. Banks and insurance lack a Gross Profit line
    — that's expected; the gross-margin factor will simply be NaN for them.
    """
    sf.set_api_key(settings.api_keys.simfin_api_key)
    sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))

    frames = []
    for label, loader in [
        ("general", sf.load_income),
        ("banks", sf.load_income_banks),
        ("insurance", sf.load_income_insurance),
    ]:
        print(f"Downloading Simfin quarterly income ({label})...")
        try:
            df = loader(variant="quarterly", market="us")
        except Exception as e:
            print(f"  WARNING: Simfin {label} fetch failed: {e}")
            continue
        if df is None or df.empty:
            print(f"  WARNING: Simfin {label} returned empty data")
            continue
        df = df.reset_index()
        print(f"  Raw Simfin {label} income rows: {len(df)}")
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    # Outer concat — schemas overlap on the columns we care about
    # (Ticker, Report Date, Publish Date, Revenue, Operating Income (Loss),
    # Net Income, Shares (Diluted)/Basic). Gross Profit only exists for the
    # general schema and will be NaN for bank/insurance rows.
    combined = pd.concat(frames, ignore_index=True, sort=False)
    print(f"  Combined Simfin income rows: {len(combined)}")
    return combined


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
    result["source"] = "simfin"

    # Drop rows without valid dates
    result = result.dropna(subset=["ticker", "report_date"])

    # Deduplicate: keep latest report_date per ticker + fiscal_period_end
    result = result.sort_values("report_date").drop_duplicates(
        subset=["ticker", "fiscal_period_end"], keep="last"
    )

    print(f"  PIT fundamentals: {len(result)} rows for {result['ticker'].nunique()} tickers")
    return result


def _yf_row(stmt: pd.DataFrame, aliases: list[str]) -> pd.Series | None:
    """Return the first alias row present in a yfinance statement, else None."""
    for alias in aliases:
        if alias in stmt.index:
            return stmt.loc[alias]
    return None


def fetch_yfinance_fundamentals(tickers: list[str]) -> pd.DataFrame:
    """Pull quarterly income statements from yfinance for gap tickers.

    Yahoo only exposes 5-7 quarters and period-end dates (no publish date), so
    we stamp report_date = fiscal_period_end + _YF_PIT_LAG_DAYS as a PIT proxy.
    This is the same fallback convention build_pit_fundamentals uses when the
    Simfin Publish Date is missing. It overestimates the lag for fast filers
    (hurts recency slightly) but never creates look-ahead bias.

    Banks return NaN gross_profit — expected, matches Simfin's bank handling.
    Tickers with <2 quarters are dropped (can't compute YoY growth factors).
    """
    warnings.filterwarnings("ignore", module="yfinance")
    print(f"Downloading yfinance quarterly fundamentals for {len(tickers)} tickers...")

    rows = []
    skipped = []
    for i, ticker in enumerate(tickers, 1):
        try:
            stmt = yf.Ticker(ticker).quarterly_income_stmt
        except Exception as e:
            skipped.append((ticker, f"fetch failed: {type(e).__name__}"))
            continue

        if stmt is None or stmt.empty:
            skipped.append((ticker, "empty"))
            continue

        # Columns = period-end dates. yfinance returns them newest-first, but
        # sort defensively in case that changes.
        cols_sorted = sorted(stmt.columns, reverse=True)
        if len(cols_sorted) < 2:
            skipped.append((ticker, f"only {len(cols_sorted)} quarter(s)"))
            continue

        revenue_row = _yf_row(stmt, _YF_FIELD_ALIASES["revenue"])
        netinc_row = _yf_row(stmt, _YF_FIELD_ALIASES["net_income"])
        gross_row = _yf_row(stmt, _YF_FIELD_ALIASES["gross_profit"])
        opinc_row = _yf_row(stmt, _YF_FIELD_ALIASES["operating_income"])
        eps_row = _yf_row(stmt, _YF_FIELD_ALIASES["eps_diluted"])
        shares_row = _yf_row(stmt, _YF_FIELD_ALIASES["shares_diluted"])

        # Revenue and net income are load-bearing — if Yahoo returns neither,
        # the ticker is useless for our factor model.
        if revenue_row is None or netinc_row is None:
            skipped.append((ticker, "missing revenue or net_income row"))
            continue

        for col in cols_sorted:
            rev = revenue_row.get(col)
            # Yahoo sometimes populates the newest column with NaN for
            # everything (e.g. FDX). Skip those rows — the second-newest column
            # will still get picked up normally.
            if pd.isna(rev):
                continue
            try:
                period_end = pd.Timestamp(col)
            except Exception:
                continue

            def _num(series, key):
                if series is None:
                    return None
                v = series.get(key)
                return None if pd.isna(v) else float(v)

            rows.append({
                "ticker": ticker,
                "fiscal_period_end": period_end,
                "report_date": period_end + pd.Timedelta(days=_YF_PIT_LAG_DAYS),
                "revenue": float(rev),
                "gross_profit": _num(gross_row, col),
                "operating_income": _num(opinc_row, col),
                "net_income": _num(netinc_row, col),
                "eps_diluted": _num(eps_row, col),
                "shares_outstanding": _num(shares_row, col),
            })

        # Be polite to Yahoo — bulk hammering trips rate limits
        if i % 10 == 0:
            print(f"  yfinance progress: {i}/{len(tickers)}")
        time.sleep(0.3)

    if skipped:
        print(f"  yfinance skipped {len(skipped)} tickers:")
        for t, reason in skipped[:10]:
            print(f"    {t}: {reason}")
        if len(skipped) > 10:
            print(f"    ... and {len(skipped) - 10} more")

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result["fiscal_period_end"] = pd.to_datetime(result["fiscal_period_end"]).dt.date
    result["report_date"] = pd.to_datetime(result["report_date"]).dt.date

    # shares_outstanding column in DuckDB is BIGINT; coerce floats to int where
    # present, leave NaN as None.
    result["shares_outstanding"] = result["shares_outstanding"].apply(
        lambda v: int(v) if pd.notna(v) else None
    )

    result = result.dropna(subset=["ticker", "report_date"])
    result["source"] = "yfinance"
    result = result.sort_values("report_date").drop_duplicates(
        subset=["ticker", "fiscal_period_end"], keep="last"
    )
    print(f"  yfinance PIT fundamentals: {len(result)} rows for {result['ticker'].nunique()} tickers")
    return result


def store_fundamentals(df: pd.DataFrame) -> None:
    """Store PIT fundamentals into DuckDB with source tracking."""
    if df.empty:
        print("No fundamentals to store.")
        return

    # Ensure source column exists
    if "source" not in df.columns:
        df["source"] = "unknown"

    con = get_connection()

    # Check if the migration columns exist yet
    cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'fundamentals_pit'").fetchall()]
    has_source_col = "source" in cols

    con.register("fund_df", df)
    con.execute("DELETE FROM fundamentals_pit")

    if has_source_col:
        con.execute("""
            INSERT INTO fundamentals_pit
            (ticker, fiscal_period_end, report_date,
             revenue, gross_profit, operating_income, net_income,
             eps_diluted, shares_outstanding, source)
            SELECT ticker, fiscal_period_end, report_date,
                   revenue, gross_profit, operating_income, net_income,
                   eps_diluted, shares_outstanding, source
            FROM fund_df
        """)
    else:
        con.execute("""
            INSERT INTO fundamentals_pit
            (ticker, fiscal_period_end, report_date,
             revenue, gross_profit, operating_income, net_income,
             eps_diluted, shares_outstanding)
            SELECT ticker, fiscal_period_end, report_date,
                   revenue, gross_profit, operating_income, net_income,
                   eps_diluted, shares_outstanding
            FROM fund_df
        """)

    row_count = con.execute("SELECT COUNT(*) FROM fundamentals_pit").fetchone()[0]
    ticker_count = con.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals_pit").fetchone()[0]

    # Log ingestion — use delete+insert instead of ON CONFLICT for DuckDB compat
    from datetime import datetime
    now = datetime.now().isoformat()
    con.execute("DELETE FROM ingestion_log WHERE data_type = 'fundamentals'")
    con.execute("""
        INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes)
        VALUES ('fundamentals', $1, $2, $3)
    """, [now, int(row_count), f"{ticker_count} tickers"])
    con.close()

    print(f"Stored in DuckDB: {row_count} fundamentals rows, {ticker_count} tickers")


def should_ingest_fundamentals() -> tuple[bool, str]:
    """Check if fundamentals should be re-ingested based on cooldown period.

    Returns (should_ingest, reason).
    """
    cooldown = settings.strategy.fundamentals_cooldown_days
    try:
        con = get_connection()
        row = con.execute("""
            SELECT last_ingested_at FROM ingestion_log
            WHERE data_type = 'fundamentals'
        """).fetchone()
        con.close()

        if row is None:
            return True, "No prior ingestion found"

        from datetime import datetime
        last = row[0]
        if isinstance(last, str):
            last = datetime.fromisoformat(last)
        days_ago = (datetime.now() - last).days

        if days_ago >= cooldown:
            return True, f"Last ingestion was {days_ago} days ago (cooldown: {cooldown}d)"
        else:
            return False, f"Last ingestion was {days_ago} days ago (cooldown: {cooldown}d, {cooldown - days_ago}d remaining)"
    except Exception as e:
        return True, f"Could not check ingestion log: {e}"


def identify_thin_simfin_tickers(simfin_pit: pd.DataFrame) -> set[str]:
    """Return tickers whose Simfin coverage is too thin or too stale to trust.

    Either condition disqualifies a ticker:
      * fewer than _MIN_SIMFIN_QUARTERS quarters (needed for YoY growth)
      * newest quarter lags the dataset's overall newest quarter by more
        than _MAX_STALENESS_BEHIND_DATASET_DAYS (this ticker silently fell
        off Simfin's refresh cycle while the rest of the dataset moved on)

    These tickers get routed through the yfinance fallback instead, where
    Yahoo typically ships 5-7 fresh quarters. Spotted cases: AEP, CWAN, WFC,
    PGR each have 1 Simfin quarter; CB has 5 but they're 2+ years behind
    the rest of the Simfin insurance dataset.
    """
    if simfin_pit.empty:
        return set()
    stats = (
        simfin_pit.groupby("ticker")["fiscal_period_end"]
        .agg(n="count", newest="max")
        .reset_index()
    )
    stats["newest"] = pd.to_datetime(stats["newest"])

    dataset_newest = stats["newest"].max()
    stale_cutoff = dataset_newest - pd.Timedelta(days=_MAX_STALENESS_BEHIND_DATASET_DAYS)

    thin = stats[
        (stats["n"] < _MIN_SIMFIN_QUARTERS) | (stats["newest"] < stale_cutoff)
    ]
    return set(thin["ticker"])


def ingest_fundamentals() -> None:
    """Full fundamentals ingestion pipeline.

    Simfin is the primary source (~175 tickers, includes banks/insurance).
    yfinance fills the gap for:
      (a) tickers Simfin doesn't carry at all (foreign ADRs, spinoffs, mega-caps)
      (b) tickers where Simfin's coverage is too thin or too stale for YoY
          growth factors to compute (see identify_thin_simfin_tickers)

    For thin Simfin tickers we fully replace the Simfin rows with yfinance
    rather than merging — mixing 1 old Simfin quarter with 5 fresh yfinance
    quarters would just create a stale-vs-fresh dedup hazard for no gain.
    """
    init_db()

    # Primary: Simfin
    income_df = fetch_simfin_income()
    simfin_pit = pd.DataFrame()
    if not income_df.empty:
        simfin_pit = build_pit_fundamentals(income_df)

    # Drop thin Simfin tickers so yfinance can fully own them
    thin = identify_thin_simfin_tickers(simfin_pit)
    if thin:
        print(f"\nThin Simfin coverage (<{_MIN_SIMFIN_QUARTERS}q or >{_MAX_STALENESS_BEHIND_DATASET_DAYS}d behind dataset newest): "
              f"{len(thin)} tickers -> {sorted(thin)}")
        simfin_pit = simfin_pit[~simfin_pit["ticker"].isin(thin)].copy()

    simfin_tickers = set(simfin_pit["ticker"]) if not simfin_pit.empty else set()

    # Fallback: yfinance for missing + thin tickers
    universe = pd.read_csv(settings.paths.universe_path)["ticker"].tolist()
    gap = sorted((set(universe) - simfin_tickers) | thin)
    yf_pit = pd.DataFrame()
    if gap:
        print(f"\nyfinance fallback: {len(gap)} tickers "
              f"(missing from Simfin or routed away from thin coverage)")
        yf_pit = fetch_yfinance_fundamentals(gap)
    else:
        print("\nNo Simfin gap — skipping yfinance fallback")

    # Combine. Simfin already had thin tickers dropped, so no collision risk.
    frames = [f for f in [simfin_pit, yf_pit] if not f.empty]
    if not frames:
        print("No fundamentals fetched from any source.")
        return
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["ticker", "fiscal_period_end"], keep="first"
    )

    store_fundamentals(combined)


if __name__ == "__main__":
    ingest_fundamentals()
