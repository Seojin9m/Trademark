-- Trademark — performance indexes.
--
-- Postgres auto-creates an index for every PRIMARY KEY and UNIQUE constraint,
-- so the indexes below are only for non-key lookup patterns the app uses.
-- Reviewed against actual queries in:
--   src/ingest/*.py, src/signals/*.py, src/api/main.py, src/learning/*.py

-- prices is the hottest table (7M+ rows). PK is (ticker, date). We also
-- frequently query "latest date across all tickers" and "all bars for a
-- single ticker over a range" — the PK covers the second; the first
-- benefits from a date-only index.
CREATE INDEX IF NOT EXISTS prices_date_idx ON prices (date);

-- fundamentals_pit PK is (ticker, report_date). Quarter-count lookups
-- (used by universe builder + quality probes) group by ticker, which the
-- PK leading column already handles. Add a fiscal_period_end index for
-- "find all rows for Q1 2024 across all tickers" queries.
CREATE INDEX IF NOT EXISTS fundamentals_pit_period_idx
    ON fundamentals_pit (fiscal_period_end);

-- factor_scores PK is (ticker, date). Most queries scan "latest scoring
-- date" — date-leading index helps.
CREATE INDEX IF NOT EXISTS factor_scores_date_idx ON factor_scores (date);

-- trade_proposals: filter by run_id + status is the dominant query.
CREATE INDEX IF NOT EXISTS trade_proposals_run_status_idx
    ON trade_proposals (run_id, status);
CREATE INDEX IF NOT EXISTS trade_proposals_created_idx
    ON trade_proposals (created_at DESC);

-- trade_executions: lookup by proposal_id (for joins) and by run_id.
CREATE INDEX IF NOT EXISTS trade_executions_proposal_idx
    ON trade_executions (proposal_id);
CREATE INDEX IF NOT EXISTS trade_executions_run_idx
    ON trade_executions (run_id);
CREATE INDEX IF NOT EXISTS trade_executions_executed_at_idx
    ON trade_executions (executed_at DESC);

-- decision_outcomes: ticker history + sector roll-ups.
CREATE INDEX IF NOT EXISTS decision_outcomes_ticker_idx
    ON decision_outcomes (ticker, decision_date DESC);
CREATE INDEX IF NOT EXISTS decision_outcomes_sector_idx
    ON decision_outcomes (sub_sector);

-- portfolio_snapshots: date-ordered chart queries dominate.
CREATE INDEX IF NOT EXISTS portfolio_snapshots_date_idx
    ON portfolio_snapshots (snapshot_date DESC);

-- universe_history: lookups by snapshot_date for "what was the universe on X".
-- PK already leads on snapshot_date so this is just a hint for older queries.
CREATE INDEX IF NOT EXISTS universe_history_date_idx
    ON universe_history (snapshot_date DESC);

-- pipeline_runs: most-recent-first listing on the dashboard.
CREATE INDEX IF NOT EXISTS pipeline_runs_started_idx
    ON pipeline_runs (started_at DESC);

-- news_research: ticker history scan.
CREATE INDEX IF NOT EXISTS news_research_ticker_idx
    ON news_research (ticker, research_date DESC);
