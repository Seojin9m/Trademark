"""DuckDB schema initialization for trade4me."""

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
    measured_at_1w DATE,
    measured_at_1m DATE,
    measured_at_3m DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
"""


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection to the main database."""
    db_path = str(settings.paths.duckdb_path)
    return duckdb.connect(db_path)


def init_db() -> None:
    """Create all tables if they don't exist."""
    con = get_connection()
    con.execute(SCHEMA_SQL)
    con.close()
    print(f"Database initialized at {settings.paths.duckdb_path}")


if __name__ == "__main__":
    init_db()
