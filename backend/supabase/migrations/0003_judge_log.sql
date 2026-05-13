-- judge_log was historically a separate SQLite database at logs/judge_log.db.
-- Migrating it to Postgres lets us drop the only non-DuckDB legacy persistence
-- and have one source of truth.
--
-- The original SQLite schema is mirrored 1:1 with Postgres-flavored types.
-- judge.client.py code that did `sqlite3.connect()` switches to the same
-- get_connection() abstraction used everywhere else.

CREATE TABLE IF NOT EXISTS judge_log (
    log_id          VARCHAR PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposal_id     VARCHAR,
    ticker          VARCHAR,
    action          VARCHAR,
    input_payload   JSONB,
    output_payload  JSONB,
    verdict         VARCHAR,
    confidence      DOUBLE PRECISION,
    model_used      VARCHAR,
    input_hash      VARCHAR
);

CREATE INDEX IF NOT EXISTS judge_log_proposal_idx ON judge_log (proposal_id);
CREATE INDEX IF NOT EXISTS judge_log_ticker_idx   ON judge_log (ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS judge_log_created_idx  ON judge_log (created_at DESC);
