"""DuckDB schema initialization for trade4me."""

import time
import duckdb

from config.settings import settings

SCHEMA_SQL = """
-- Prices (adjusted daily OHLCV)
CREATE TABLE IF NOT EXISTS prices (
    ticker VARCHAR,
    date DATE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    adj_close DOUBLE,
    PRIMARY KEY (ticker, date)
);

-- Fundamentals (point-in-time)
CREATE TABLE IF NOT EXISTS fundamentals_pit (
    ticker VARCHAR,
    fiscal_period_end DATE,
    report_date DATE,
    revenue DOUBLE,
    gross_profit DOUBLE,
    operating_income DOUBLE,
    net_income DOUBLE,
    eps_diluted DOUBLE,
    shares_outstanding BIGINT,
    PRIMARY KEY (ticker, report_date)
);

-- Factor scores (daily, computed)
CREATE TABLE IF NOT EXISTS factor_scores (
    ticker VARCHAR,
    date DATE,
    momentum_12m1m DOUBLE,
    eps_growth_yoy DOUBLE,
    revenue_growth_yoy DOUBLE,
    gross_margin_trend DOUBLE,
    relative_valuation DOUBLE,
    composite_score DOUBLE,
    score_decile INTEGER,
    PRIMARY KEY (ticker, date)
);

-- Trade proposals
CREATE TABLE IF NOT EXISTS trade_proposals (
    proposal_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    created_at TIMESTAMP,
    ticker VARCHAR,
    action VARCHAR,
    shares INTEGER,
    signal_data JSON,
    constraint_check JSON,
    status VARCHAR,
    judge_response JSON,
    human_decision VARCHAR,
    human_notes TEXT
);

-- Simulated positions (updated after execution)
CREATE TABLE IF NOT EXISTS simulated_positions (
    ticker VARCHAR PRIMARY KEY,
    shares INTEGER,
    avg_cost_basis DOUBLE,
    last_updated TIMESTAMP
);

-- Macro data (FRED series)
CREATE TABLE IF NOT EXISTS macro_data (
    series_id VARCHAR,
    date DATE,
    value DOUBLE,
    PRIMARY KEY (series_id, date)
);

-- News research (Phase 6)
CREATE TABLE IF NOT EXISTS news_research (
    ticker VARCHAR,
    research_date DATE,
    headlines JSON,
    ai_summary TEXT,
    sentiment VARCHAR,
    binary_events JSON,
    risk_factors JSON,
    opportunities JSON,
    data_sources JSON,
    confidence DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, research_date)
);

-- Decision outcomes (Phase 7 - Self-Learning)
CREATE TABLE IF NOT EXISTS decision_outcomes (
    proposal_id VARCHAR PRIMARY KEY,
    execution_id VARCHAR,
    ticker VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    decision_date DATE NOT NULL,
    entry_price DOUBLE,
    shares INTEGER,
    composite_score DOUBLE,
    score_decile INTEGER,
    prior_decile INTEGER,
    judge_verdict VARCHAR,
    judge_confidence DOUBLE,
    sector VARCHAR,
    sub_sector VARCHAR,
    factor_snapshot JSON,
    return_1w DOUBLE,
    return_1m DOUBLE,
    return_3m DOUBLE,
    benchmark_return_1w DOUBLE,
    benchmark_return_1m DOUBLE,
    benchmark_return_3m DOUBLE,
    excess_return_1w DOUBLE,
    excess_return_1m DOUBLE,
    excess_return_3m DOUBLE,
    outcome_1m VARCHAR,
    proposal_status VARCHAR,
    measured_at_1w DATE,
    measured_at_1m DATE,
    measured_at_3m DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trade executions (actual executed trades with full audit trail)
CREATE TABLE IF NOT EXISTS trade_executions (
    execution_id VARCHAR PRIMARY KEY,
    proposal_id VARCHAR NOT NULL,
    run_id VARCHAR,
    ticker VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    shares INTEGER NOT NULL,
    execution_price DOUBLE NOT NULL,
    total_value DOUBLE NOT NULL,
    execution_source VARCHAR NOT NULL,
    pre_cash DOUBLE,
    post_cash DOUBLE,
    pre_position_shares INTEGER DEFAULT 0,
    post_position_shares INTEGER DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    failure_reason TEXT,
    executed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio value snapshots (daily time series)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    total_value DOUBLE NOT NULL,
    cash DOUBLE NOT NULL,
    positions_value DOUBLE NOT NULL,
    n_positions INTEGER NOT NULL,
    total_cost_basis DOUBLE,
    unrealized_pnl DOUBLE,
    total_return_pct DOUBLE,
    benchmark_value DOUBLE,
    benchmark_return_pct DOUBLE,
    snapshot_source VARCHAR NOT NULL DEFAULT 'pipeline',
    positions_detail JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, snapshot_source)
);

-- Decision patterns (Phase 7 - Self-Learning)
CREATE TABLE IF NOT EXISTS decision_patterns (
    pattern_id VARCHAR PRIMARY KEY,
    dimension VARCHAR NOT NULL,
    dimension_value VARCHAR NOT NULL,
    sample_size INTEGER NOT NULL,
    win_rate DOUBLE,
    avg_excess_return_1m DOUBLE,
    avg_excess_return_3m DOUBLE,
    best_ticker VARCHAR,
    worst_ticker VARCHAR,
    is_alert BOOLEAN DEFAULT FALSE,
    alert_message TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Editable stock metrics (user-correctable numeric data)
CREATE TABLE IF NOT EXISTS stock_metrics (
    ticker VARCHAR,
    metric_name VARCHAR,
    raw_value DOUBLE,
    user_value DOUBLE,
    source VARCHAR DEFAULT 'computed',
    as_of_date DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, metric_name, as_of_date)
);

-- Stock quality assessment (pre-computed good-stock filter)
CREATE TABLE IF NOT EXISTS stock_quality_assessment (
    ticker VARCHAR,
    date DATE,
    is_good_stock BOOLEAN,
    quality_score DOUBLE,
    quality_reasons JSON,
    per_ratio DOUBLE,
    per_vs_peer DOUBLE,
    per_absolute_pass BOOLEAN,
    per_relative_pass BOOLEAN,
    price_opportunity_score DOUBLE,
    PRIMARY KEY (ticker, date)
);

-- Ingestion log (tracks when each data type was last ingested)
CREATE TABLE IF NOT EXISTS ingestion_log (
    data_type VARCHAR PRIMARY KEY,
    last_ingested_at TIMESTAMP,
    record_count INTEGER,
    notes TEXT
);

"""


def get_connection(max_retries: int = 8, retry_delay: float = 0.3) -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection, retrying on transient lock contention."""
    db_path = str(settings.paths.duckdb_path)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return duckdb.connect(db_path)
        except Exception as exc:
            msg = str(exc).lower()
            if any(kw in msg for kw in ("lock", "busy", "already open", "cannot open")):
                last_exc = exc
                time.sleep(retry_delay * (attempt + 1))
            else:
                raise
    raise RuntimeError(f"Could not acquire DuckDB connection after {max_retries} retries: {last_exc}")


def init_db() -> None:
    """Create all tables if they don't exist."""
    con = get_connection()
    con.execute(SCHEMA_SQL)

    # Migrations: add columns that may not exist on older databases
    migrations = [
        ("decision_outcomes", "execution_id", "VARCHAR"),
        ("decision_outcomes", "proposal_status", "VARCHAR"),
        ("trade_proposals", "run_id", "VARCHAR"),
        ("fundamentals_pit", "fiscal_year", "INTEGER"),
        ("fundamentals_pit", "fiscal_quarter", "VARCHAR"),
        ("fundamentals_pit", "source", "VARCHAR"),
        ("fundamentals_pit", "created_at", "TIMESTAMP"),
        ("fundamentals_pit", "updated_at", "TIMESTAMP"),
        ("trade_proposals", "reason", "TEXT"),
    ]
    for table, col, col_type in migrations:
        try:
            con.execute(f"SELECT {col} FROM {table} LIMIT 0")
        except Exception:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                print(f"  Migration: added {col} to {table}")
            except Exception:
                pass

    con.close()
    print(f"Database initialized at {settings.paths.duckdb_path}")


if __name__ == "__main__":
    init_db()
