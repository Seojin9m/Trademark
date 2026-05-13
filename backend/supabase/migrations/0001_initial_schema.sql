-- Trademark — initial Postgres schema (mirror of DuckDB schema with Postgres types).
--
-- This is the Phase 2 lift-and-shift schema: same column names and key
-- structure as the existing DuckDB tables in src/db/schema.py, with the
-- following type adjustments:
--   - DuckDB DOUBLE        -> Postgres DOUBLE PRECISION
--   - DuckDB JSON          -> Postgres JSONB (faster query, indexable)
--   - DuckDB TIMESTAMP     -> Postgres TIMESTAMPTZ (always store with TZ)
--
-- Three new tables vs DuckDB:
--   - universe              (replaces config/universe.csv)
--   - universe_history      (audit trail for monthly rebuilds)
--   - portfolio_state       (replaces data/portfolio_state.json)
--   - factor_weights_state  (replaces config/factor_weights.json)
--
-- Indexes live in 0002_indexes.sql so this file stays focused on shape.

-- ===========================================================================
-- Market data
-- ===========================================================================

CREATE TABLE IF NOT EXISTS prices (
    ticker          VARCHAR NOT NULL,
    date            DATE NOT NULL,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          BIGINT,
    adj_close       DOUBLE PRECISION,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS fundamentals_pit (
    ticker              VARCHAR NOT NULL,
    fiscal_period_end   DATE,
    report_date         DATE NOT NULL,
    revenue             DOUBLE PRECISION,
    gross_profit        DOUBLE PRECISION,
    operating_income    DOUBLE PRECISION,
    net_income          DOUBLE PRECISION,
    eps_diluted         DOUBLE PRECISION,
    shares_outstanding  BIGINT,
    fiscal_year         INTEGER,
    fiscal_quarter      VARCHAR,
    source              VARCHAR,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, report_date)
);

CREATE TABLE IF NOT EXISTS macro_data (
    series_id   VARCHAR NOT NULL,
    date        DATE NOT NULL,
    value       DOUBLE PRECISION,
    PRIMARY KEY (series_id, date)
);

-- ===========================================================================
-- Computed signals
-- ===========================================================================

CREATE TABLE IF NOT EXISTS factor_scores (
    ticker              VARCHAR NOT NULL,
    date                DATE NOT NULL,
    momentum_12m1m      DOUBLE PRECISION,
    eps_growth_yoy      DOUBLE PRECISION,
    revenue_growth_yoy  DOUBLE PRECISION,
    gross_margin_trend  DOUBLE PRECISION,
    relative_valuation  DOUBLE PRECISION,
    composite_score     DOUBLE PRECISION,
    score_decile        INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS stock_quality_assessment (
    ticker                     VARCHAR NOT NULL,
    date                       DATE NOT NULL,
    is_good_stock              BOOLEAN,
    quality_score              DOUBLE PRECISION,
    quality_reasons            JSONB,
    per_ratio                  DOUBLE PRECISION,
    per_vs_peer                DOUBLE PRECISION,
    per_absolute_pass          BOOLEAN,
    per_relative_pass          BOOLEAN,
    price_opportunity_score    DOUBLE PRECISION,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS stock_metrics (
    ticker         VARCHAR NOT NULL,
    metric_name    VARCHAR NOT NULL,
    raw_value      DOUBLE PRECISION,
    user_value     DOUBLE PRECISION,
    source         VARCHAR DEFAULT 'computed',
    as_of_date     DATE NOT NULL,
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, metric_name, as_of_date)
);

-- ===========================================================================
-- Trading state
-- ===========================================================================

CREATE TABLE IF NOT EXISTS trade_proposals (
    proposal_id        VARCHAR PRIMARY KEY,
    run_id             VARCHAR,
    created_at         TIMESTAMPTZ DEFAULT now(),
    ticker             VARCHAR,
    action             VARCHAR,
    shares             INTEGER,
    signal_data        JSONB,
    constraint_check   JSONB,
    status             VARCHAR,
    judge_response     JSONB,
    human_decision     VARCHAR,
    human_notes        TEXT,
    reason             TEXT
);

CREATE TABLE IF NOT EXISTS simulated_positions (
    ticker            VARCHAR PRIMARY KEY,
    shares            INTEGER,
    avg_cost_basis    DOUBLE PRECISION,
    last_updated      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_executions (
    execution_id           VARCHAR PRIMARY KEY,
    proposal_id            VARCHAR NOT NULL,
    run_id                 VARCHAR,
    ticker                 VARCHAR NOT NULL,
    action                 VARCHAR NOT NULL,
    shares                 INTEGER NOT NULL,
    execution_price        DOUBLE PRECISION NOT NULL,
    total_value            DOUBLE PRECISION NOT NULL,
    execution_source       VARCHAR NOT NULL,
    pre_cash               DOUBLE PRECISION,
    post_cash              DOUBLE PRECISION,
    pre_position_shares    INTEGER DEFAULT 0,
    post_position_shares   INTEGER DEFAULT 0,
    success                BOOLEAN NOT NULL DEFAULT TRUE,
    failure_reason         TEXT,
    executed_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id          VARCHAR PRIMARY KEY,
    snapshot_date        DATE NOT NULL,
    total_value          DOUBLE PRECISION NOT NULL,
    cash                 DOUBLE PRECISION NOT NULL,
    positions_value      DOUBLE PRECISION NOT NULL,
    n_positions          INTEGER NOT NULL,
    total_cost_basis     DOUBLE PRECISION,
    unrealized_pnl       DOUBLE PRECISION,
    total_return_pct     DOUBLE PRECISION,
    benchmark_value      DOUBLE PRECISION,
    benchmark_return_pct DOUBLE PRECISION,
    snapshot_source      VARCHAR NOT NULL DEFAULT 'pipeline',
    positions_detail     JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_date, snapshot_source)
);

-- ===========================================================================
-- Learning / outcomes
-- ===========================================================================

CREATE TABLE IF NOT EXISTS decision_outcomes (
    proposal_id                 VARCHAR PRIMARY KEY,
    execution_id                VARCHAR,
    ticker                      VARCHAR NOT NULL,
    action                      VARCHAR NOT NULL,
    decision_date               DATE NOT NULL,
    entry_price                 DOUBLE PRECISION,
    shares                      INTEGER,
    composite_score             DOUBLE PRECISION,
    score_decile                INTEGER,
    prior_decile                INTEGER,
    judge_verdict               VARCHAR,
    judge_confidence            DOUBLE PRECISION,
    sector                      VARCHAR,
    sub_sector                  VARCHAR,
    factor_snapshot             JSONB,
    return_1w                   DOUBLE PRECISION,
    return_1m                   DOUBLE PRECISION,
    return_3m                   DOUBLE PRECISION,
    benchmark_return_1w         DOUBLE PRECISION,
    benchmark_return_1m         DOUBLE PRECISION,
    benchmark_return_3m         DOUBLE PRECISION,
    excess_return_1w            DOUBLE PRECISION,
    excess_return_1m            DOUBLE PRECISION,
    excess_return_3m            DOUBLE PRECISION,
    outcome_1m                  VARCHAR,
    proposal_status             VARCHAR,
    measured_at_1w              DATE,
    measured_at_1m              DATE,
    measured_at_3m              DATE,
    created_at                  TIMESTAMPTZ DEFAULT now(),
    updated_at                  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_patterns (
    pattern_id              VARCHAR PRIMARY KEY,
    dimension               VARCHAR NOT NULL,
    dimension_value         VARCHAR NOT NULL,
    sample_size             INTEGER NOT NULL,
    win_rate                DOUBLE PRECISION,
    avg_excess_return_1m    DOUBLE PRECISION,
    avg_excess_return_3m    DOUBLE PRECISION,
    best_ticker             VARCHAR,
    worst_ticker            VARCHAR,
    is_alert                BOOLEAN DEFAULT FALSE,
    alert_message           TEXT,
    computed_at             TIMESTAMPTZ DEFAULT now()
);

-- ===========================================================================
-- Research / news
-- ===========================================================================

CREATE TABLE IF NOT EXISTS news_research (
    ticker            VARCHAR NOT NULL,
    research_date     DATE NOT NULL,
    headlines         JSONB,
    ai_summary        TEXT,
    sentiment         VARCHAR,
    binary_events     JSONB,
    risk_factors      JSONB,
    opportunities     JSONB,
    data_sources      JSONB,
    confidence        DOUBLE PRECISION,
    created_at        TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, research_date)
);

-- ===========================================================================
-- Operational metadata
-- ===========================================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
    data_type           VARCHAR PRIMARY KEY,
    last_ingested_at    TIMESTAMPTZ,
    record_count        INTEGER,
    notes               TEXT
);

-- ===========================================================================
-- New tables (vs DuckDB) — replace config files + add history audit
-- ===========================================================================

-- Universe: replaces config/universe.csv. One row per active ticker.
-- The monthly rebuilder writes to this table; downstream code reads from it
-- instead of parsing CSV (faster, transactional, query-able).
CREATE TABLE IF NOT EXISTS universe (
    ticker                  VARCHAR PRIMARY KEY,
    name                    VARCHAR,
    sub_sector              VARCHAR,
    market_cap_tier         VARCHAR,
    median_dollar_volume    DOUBLE PRECISION,
    quarters_available      INTEGER,
    last_updated            TIMESTAMPTZ DEFAULT now()
);

-- Universe history: every monthly rebuild snapshots the universe into this
-- table so we can answer "what was tradable on date X" — essential for
-- avoiding survivorship bias in any future backtest, and for auditing how
-- the universe rule has evolved over time.
CREATE TABLE IF NOT EXISTS universe_history (
    snapshot_date           DATE NOT NULL,
    ticker                  VARCHAR NOT NULL,
    name                    VARCHAR,
    sub_sector              VARCHAR,
    market_cap_tier         VARCHAR,
    median_dollar_volume    DOUBLE PRECISION,
    quarters_available      INTEGER,
    PRIMARY KEY (snapshot_date, ticker)
);

-- Portfolio state: replaces data/portfolio_state.json. Singleton row.
-- Stored as JSONB so we don't have to break the existing in-memory shape
-- into N relational tables right away — the shape can evolve without DDL.
-- The `id = 1` CHECK ensures only one row ever exists.
CREATE TABLE IF NOT EXISTS portfolio_state (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    state       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    CHECK (id = 1)
);

-- Factor weights: replaces config/factor_weights.json. Singleton row.
CREATE TABLE IF NOT EXISTS factor_weights_state (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    weights     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    CHECK (id = 1)
);

-- ===========================================================================
-- Run audit (new — was previously implicit in in-memory _pipeline_runs)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          VARCHAR PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR NOT NULL DEFAULT 'running',  -- running | done | error
    scored_count    INTEGER,
    proposal_count  INTEGER,
    error_message   TEXT,
    events          JSONB  -- step-by-step SSE event log
);
