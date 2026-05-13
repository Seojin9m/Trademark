"""Fundamentals ingestion from Polygon /vX/reference/financials.

Primary source is Polygon Stocks Starter (single API, point-in-time data,
unlimited calls). The legacy SimFin + yfinance fallback path is preserved
below for rollback but ingest_fundamentals() now calls the Polygon path.
"""

import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import simfin as sf
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection, init_db
from src.db.state import load_universe_df
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
_MAX_ABSOLUTE_STALENESS_DAYS = 150


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
    universe = load_universe_df()["ticker"].tolist()

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
    """Store PIT fundamentals into the configured backend (DuckDB or Postgres).

    Both backends fully replace the fundamentals_pit table content (DELETE
    then INSERT) — the existing pipeline assumes a fresh snapshot each run
    rather than incremental upserts, because thin-coverage tickers can flip
    between SimFin and the yfinance fallback between runs and we don't want
    stale rows surviving across that switch.
    """
    import os
    if df.empty:
        print("No fundamentals to store.")
        return

    if "source" not in df.columns:
        df["source"] = "unknown"

    backend = (os.getenv("DB_BACKEND") or "duckdb").lower()
    con = get_connection()

    if backend == "postgres":
        _store_fundamentals_postgres(con, df)
    else:
        _store_fundamentals_duckdb(con, df)


def _store_fundamentals_duckdb(con, df: pd.DataFrame) -> None:
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'fundamentals_pit'"
    ).fetchall()]
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

    from datetime import datetime
    now = datetime.now().isoformat()
    con.execute("DELETE FROM ingestion_log WHERE data_type = 'fundamentals'")
    con.execute("""
        INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes)
        VALUES ('fundamentals', $1, $2, $3)
    """, [now, int(row_count), f"{ticker_count} tickers"])
    con.close()

    print(f"Stored in DuckDB: {row_count} fundamentals rows, {ticker_count} tickers")


def _store_fundamentals_postgres(con, df: pd.DataFrame) -> None:
    """Postgres path — TRUNCATE + COPY in a single atomic transaction.

    Opens a fresh raw psycopg2 connection because `con` is a
    PgConnectionAdapter with autocommit=True (good for app queries, deadly
    here — TRUNCATE would commit before COPY runs, and if COPY fails the
    table is left empty). With autocommit=False, the whole TRUNCATE +
    COPY + ingestion_log update is one transaction that either fully
    commits or fully rolls back.
    """
    import io
    from src.db.postgres import get_pg_connection

    cols = [
        "ticker", "fiscal_period_end", "report_date",
        "revenue", "gross_profit", "operating_income", "net_income",
        "eps_diluted", "shares_outstanding", "source",
    ]
    payload = df.reindex(columns=cols).copy()
    # shares_outstanding is BIGINT in Postgres; pandas would serialize float
    # values like 485000000.0 which Postgres rejects. Cast via Int64 (nullable
    # int) so NaN -> NULL and integers stay integer. Round() first because
    # Polygon's diluted_average_shares is a period AVERAGE and can be
    # fractional (e.g. 14725873500.5) — a strict Int64 cast on that raises
    # "cannot safely cast non-equivalent float64 to int64".
    payload["shares_outstanding"] = pd.to_numeric(
        payload["shares_outstanding"], errors="coerce"
    ).round().astype("Int64")

    buf = io.StringIO()
    payload.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    # Bypass the adapter's autocommit by opening a fresh raw connection.
    raw_conn = get_pg_connection(role="pooled")
    raw_conn.autocommit = False
    try:
        with raw_conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE fundamentals_pit")
            cur.copy_expert(
                "COPY fundamentals_pit (" + ", ".join(cols) + ") "
                "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )

            cur.execute("SELECT COUNT(*) FROM fundamentals_pit")
            row_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals_pit")
            ticker_count = cur.fetchone()[0]

            cur.execute("DELETE FROM ingestion_log WHERE data_type = 'fundamentals'")
            cur.execute(
                "INSERT INTO ingestion_log (data_type, last_ingested_at, record_count, notes) "
                "VALUES ('fundamentals', now(), %s, %s)",
                (int(row_count), f"{ticker_count} tickers"),
            )

        raw_conn.commit()
        print(f"Stored in Postgres: {row_count} fundamentals rows, {ticker_count} tickers")
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
        try:
            con.close()
        except Exception:
            pass


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

        from datetime import datetime, timezone
        last = row[0]
        if isinstance(last, str):
            last = datetime.fromisoformat(last)
        # Postgres returns TIMESTAMPTZ (tz-aware); DuckDB returns naive
        # datetime; .isoformat() strings may or may not have a tz. Normalize
        # to naive UTC before subtracting from datetime.now() (which is also
        # naive local). The "days_ago" calculation tolerates the small drift.
        if last.tzinfo is not None:
            last = last.astimezone(timezone.utc).replace(tzinfo=None)
        days_ago = (datetime.utcnow() - last).days

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
    relative_cutoff = dataset_newest - pd.Timedelta(days=_MAX_STALENESS_BEHIND_DATASET_DAYS)
    absolute_cutoff = pd.Timestamp.now() - pd.Timedelta(days=_MAX_ABSOLUTE_STALENESS_DAYS)

    thin = stats[
        (stats["n"] < _MIN_SIMFIN_QUARTERS)
        | (stats["newest"] < relative_cutoff)
        | (stats["newest"] < absolute_cutoff)
    ]
    return set(thin["ticker"])


# ============================================================================
# Polygon Financials (primary source as of the Starter-tier upgrade)
# ============================================================================

def _polygon_extract_value(node, field):
    """Safely read .value from a Polygon financials node.

    Polygon nests every numeric field under {value, unit, label, order}.
    Returns None if the field is absent or malformed.
    """
    if not node:
        return None
    obj = node.get(field) if isinstance(node, dict) else getattr(node, field, None)
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get("value")
    return getattr(obj, "value", None)


def fetch_polygon_financials_one(ticker: str) -> list[dict]:
    """Pull all quarterly financial reports for one ticker.

    Returns a list of rows in our fundamentals_pit schema. Skips reports
    where the income statement is empty or where fiscal_period is annual
    (we only store quarterly snapshots; annuals would dilute YoY math).
    """
    from polygon import RESTClient
    client = RESTClient(api_key=settings.api_keys.polygon_api_key)

    rows: list[dict] = []
    try:
        results = client.vx.list_stock_financials(
            ticker=ticker, timeframe="quarterly", limit=100, order="desc", sort="period_of_report_date"
        )
        for r in results:
            # Polygon's response model may expose attributes (model) or dicts
            # depending on client version; getattr() works for both.
            financials = getattr(r, "financials", None)
            if financials is None:
                continue
            income = (
                financials.get("income_statement")
                if isinstance(financials, dict)
                else getattr(financials, "income_statement", None)
            )

            revenue = _polygon_extract_value(income, "revenues")
            net_income = _polygon_extract_value(income, "net_income_loss")
            if revenue is None and net_income is None:
                # No usable income data — skip.
                continue

            fiscal_period_end = getattr(r, "end_date", None)
            filing_date = getattr(r, "filing_date", None) or fiscal_period_end
            rows.append({
                "ticker": ticker,
                "fiscal_period_end": fiscal_period_end,
                "report_date": filing_date,
                "fiscal_year": getattr(r, "fiscal_year", None),
                "fiscal_quarter": getattr(r, "fiscal_period", None),
                "revenue": revenue,
                "gross_profit": _polygon_extract_value(income, "gross_profit"),
                "operating_income": _polygon_extract_value(income, "operating_income_loss"),
                "net_income": net_income,
                "eps_diluted": _polygon_extract_value(income, "diluted_earnings_per_share"),
                "shares_outstanding": _polygon_extract_value(income, "diluted_average_shares"),
                "source": "polygon",
            })
    except Exception:
        # Per-ticker failures are silent — log at the batch level.
        return []
    return rows


def fetch_polygon_financials(tickers: list[str], workers: int | None = None) -> pd.DataFrame:
    """Fetch quarterly financials for every ticker in parallel.

    Polygon Stocks Starter tolerates moderate concurrency; 8 workers
    completes ~2,000 tickers in ~3-5 minutes. Each ticker yields up to
    20 quarterly rows (5 years × 4 quarters).
    """
    if workers is None:
        workers = int(os.getenv("POLYGON_FUND_WORKERS", "8"))

    print(f"Polygon financials: {len(tickers)} tickers, {workers} workers")
    all_rows: list[dict] = []
    completed = 0
    empty = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_polygon_financials_one, t): t for t in tickers}
        for fut in as_completed(futures):
            completed += 1
            rows = fut.result()
            if rows:
                all_rows.extend(rows)
            else:
                empty += 1
            if completed % 200 == 0 or completed == len(tickers):
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(tickers) - completed) / rate if rate > 0 else 0
                print(
                    f"  Polygon financials: {completed}/{len(tickers)} "
                    f"({rate:.1f}/s, ETA {eta:.0f}s, {empty} empty, {len(all_rows):,} rows)"
                )

    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    # Normalize dates: Polygon returns ISO date strings; convert for downstream code.
    df["fiscal_period_end"] = pd.to_datetime(df["fiscal_period_end"], errors="coerce")
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    return df


# ============================================================================
# Orchestrator
# ============================================================================

def ingest_fundamentals() -> None:
    """Full fundamentals ingestion pipeline (Polygon /vX/reference/financials).

    The legacy SimFin + yfinance flow is preserved below (fetch_simfin_*,
    fetch_yfinance_fundamentals, build_pit_fundamentals) for rollback if
    Polygon coverage proves insufficient — set
    FUNDAMENTALS_SOURCE=legacy to use it.
    """
    init_db()
    source = (os.getenv("FUNDAMENTALS_SOURCE") or "polygon").lower()

    if source == "legacy":
        _ingest_fundamentals_legacy()
        return

    universe = load_universe_df()["ticker"].tolist()
    df = fetch_polygon_financials(universe)
    if df.empty:
        print("No fundamentals fetched from Polygon.")
        return
    # Drop rows missing the natural key, then dedupe to one row per
    # (ticker, fiscal_period_end) keeping the latest report_date — PIT
    # convention: most recently published value for that quarter wins.
    df = df.dropna(subset=["fiscal_period_end"])
    df = (
        df.sort_values(["ticker", "fiscal_period_end", "report_date"])
          .drop_duplicates(subset=["ticker", "fiscal_period_end"], keep="last")
    )
    store_fundamentals(df)


def _ingest_fundamentals_legacy() -> None:
    """Legacy SimFin + yfinance fallback flow.

    Kept as a safety net while the Polygon Financials path matures. Re-enable
    by setting FUNDAMENTALS_SOURCE=legacy in env.
    """
    income_df = fetch_simfin_income()
    simfin_pit = pd.DataFrame()
    if not income_df.empty:
        simfin_pit = build_pit_fundamentals(income_df)

    thin = identify_thin_simfin_tickers(simfin_pit)
    if thin:
        print(
            f"\nThin Simfin coverage (<{_MIN_SIMFIN_QUARTERS}q or >{_MAX_STALENESS_BEHIND_DATASET_DAYS}d behind dataset newest): "
            f"{len(thin)} tickers -> {sorted(thin)}"
        )
        simfin_pit = simfin_pit[~simfin_pit["ticker"].isin(thin)].copy()

    simfin_tickers = set(simfin_pit["ticker"]) if not simfin_pit.empty else set()
    universe = load_universe_df()["ticker"].tolist()
    gap = sorted((set(universe) - simfin_tickers) | thin)
    yf_pit = pd.DataFrame()
    if gap:
        print(
            f"\nyfinance fallback: {len(gap)} tickers "
            f"(missing from Simfin or routed away from thin coverage)"
        )
        yf_pit = fetch_yfinance_fundamentals(gap)
    else:
        print("\nNo Simfin gap — skipping yfinance fallback")

    frames = [f for f in [simfin_pit, yf_pit] if not f.empty]
    if not frames:
        print("No fundamentals fetched from any source.")
        return
    combined = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["ticker", "fiscal_period_end"], keep="first"
    )
    store_fundamentals(combined)


if __name__ == "__main__":
    ingest_fundamentals()
