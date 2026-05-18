-- Multi-user scoping: add user_id to every per-user table.
--
-- DESTRUCTIVE: this migration TRUNCATEs all per-user tables before adding
-- the required NOT NULL user_id column. The user explicitly chose "wipe and
-- start fresh" — see the planning thread — because there is no existing
-- production data worth preserving and a clean schema is much simpler than
-- a backfill-with-default-user flow.
--
-- Tables touched:
--   per-user portfolio   : portfolio_state, portfolio_snapshots, simulated_positions
--   per-user trading     : trade_proposals, trade_executions, judge_log,
--                          decision_outcomes
--   per-user config      : factor_weights_state, watchlist
--   per-user ops         : pipeline_runs
--   new per-user tables  : user_notes, analyst_reviews
--                          (previously in-memory dict / JSON file)
--
-- Untouched (intentionally global):
--   market data          : prices, fundamentals_pit, macro_data, news_research,
--                          forward_estimates, universe(_history), ingestion_log
--   global signals       : factor_scores, stock_quality_assessment,
--                          stock_metrics, decision_patterns, sector_signals,
--                          market_summary, signal_quality_log
--   discovery            : discovery_candidates

-- ===========================================================================
-- 1. Wipe per-user data so we can add NOT NULL user_id without backfilling.
-- ===========================================================================
TRUNCATE TABLE
    portfolio_state,
    portfolio_snapshots,
    simulated_positions,
    trade_proposals,
    trade_executions,
    judge_log,
    decision_outcomes,
    factor_weights_state,
    watchlist,
    pipeline_runs
RESTART IDENTITY;

-- ===========================================================================
-- 2. portfolio_state — was a singleton (CHECK id=1). Now one row per user.
-- ===========================================================================
ALTER TABLE portfolio_state DROP CONSTRAINT IF EXISTS portfolio_state_id_check;
ALTER TABLE portfolio_state DROP CONSTRAINT IF EXISTS portfolio_state_pkey;
ALTER TABLE portfolio_state DROP COLUMN IF EXISTS id;
ALTER TABLE portfolio_state
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD PRIMARY KEY (user_id);

-- ===========================================================================
-- 3. factor_weights_state — same singleton-to-per-user pattern as above.
-- ===========================================================================
ALTER TABLE factor_weights_state DROP CONSTRAINT IF EXISTS factor_weights_state_id_check;
ALTER TABLE factor_weights_state DROP CONSTRAINT IF EXISTS factor_weights_state_pkey;
ALTER TABLE factor_weights_state DROP COLUMN IF EXISTS id;
ALTER TABLE factor_weights_state
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD PRIMARY KEY (user_id);

-- ===========================================================================
-- 4. simulated_positions — was PK (ticker). Now PK (user_id, ticker).
-- ===========================================================================
ALTER TABLE simulated_positions DROP CONSTRAINT IF EXISTS simulated_positions_pkey;
ALTER TABLE simulated_positions
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD PRIMARY KEY (user_id, ticker);

-- ===========================================================================
-- 5. portfolio_snapshots — UNIQUE (snapshot_date, snapshot_source) becomes
-- UNIQUE (user_id, snapshot_date, snapshot_source).
-- ===========================================================================
ALTER TABLE portfolio_snapshots
    DROP CONSTRAINT IF EXISTS portfolio_snapshots_snapshot_date_snapshot_source_key;
ALTER TABLE portfolio_snapshots
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD CONSTRAINT portfolio_snapshots_user_date_source_key
        UNIQUE (user_id, snapshot_date, snapshot_source);

CREATE INDEX IF NOT EXISTS portfolio_snapshots_user_date_idx
    ON portfolio_snapshots (user_id, snapshot_date DESC);

-- ===========================================================================
-- 6. trade_proposals, trade_executions, judge_log, decision_outcomes —
-- per-user trading lifecycle. PKs stay (proposal_id / execution_id are
-- already globally unique UUIDs); we just add user_id + an index.
-- ===========================================================================
ALTER TABLE trade_proposals
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS trade_proposals_user_created_idx
    ON trade_proposals (user_id, created_at DESC);

ALTER TABLE trade_executions
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS trade_executions_user_executed_idx
    ON trade_executions (user_id, executed_at DESC);

ALTER TABLE judge_log
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS judge_log_user_created_idx
    ON judge_log (user_id, created_at DESC);

ALTER TABLE decision_outcomes
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS decision_outcomes_user_date_idx
    ON decision_outcomes (user_id, decision_date DESC);

-- ===========================================================================
-- 7. watchlist — PK was (ticker). Now (user_id, ticker). A ticker can be
-- on multiple users' watchlists independently.
-- ===========================================================================
ALTER TABLE watchlist DROP CONSTRAINT IF EXISTS watchlist_pkey;
ALTER TABLE watchlist
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD PRIMARY KEY (user_id, ticker);

-- ===========================================================================
-- 8. pipeline_runs — was process-memory in main.py. Now per-user, persisted.
-- ===========================================================================
ALTER TABLE pipeline_runs
    ADD COLUMN user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS pipeline_runs_user_started_idx
    ON pipeline_runs (user_id, started_at DESC);

-- ===========================================================================
-- 9. user_notes — promoting the in-memory `_user_notes` dict from
-- backend/src/api/main.py into a real per-user table.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS user_notes (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    text        TEXT NOT NULL DEFAULT '',
    images      JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ===========================================================================
-- 10. analyst_reviews — promoting the JSON file (data/analyst_review.json)
-- into a per-user table. Each user gets their own analyst opinion history.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS analyst_reviews (
    review_id              VARCHAR PRIMARY KEY,
    user_id                UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    portfolio_value        DOUBLE PRECISION,
    overall_stance         VARCHAR,
    summary                TEXT,
    market_context         TEXT,
    portfolio_health_score DOUBLE PRECISION,
    position_reviews       JSONB,
    strengths              JSONB,
    concerns               JSONB,
    opportunities          JSONB,
    risk_factors           JSONB,
    pipeline_guidance      JSONB,
    apply_to_pipeline      BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS analyst_reviews_user_created_idx
    ON analyst_reviews (user_id, created_at DESC);

-- ===========================================================================
-- 11. brokerage_connections — replaces backend/data/snaptrade_state.json.
-- One row per (user, broker) pair; tokens stored as TEXT and should be
-- written/read via Supabase Vault (pgsodium) on the application side.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS brokerage_connections (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    broker                  VARCHAR NOT NULL,
    snaptrade_user_id       VARCHAR NOT NULL,
    snaptrade_user_secret   TEXT NOT NULL,
    connected_at            TIMESTAMPTZ DEFAULT now(),
    last_sync_at            TIMESTAMPTZ,
    status                  VARCHAR DEFAULT 'active',
    selected_account_ids    JSONB DEFAULT '[]'::jsonb,
    UNIQUE (user_id, broker)
);
CREATE INDEX IF NOT EXISTS brokerage_connections_user_idx
    ON brokerage_connections (user_id);

-- ===========================================================================
-- 12. user_settings — preferences not tied to portfolio or trading (timezone,
-- currency, notification opt-ins). Single row per user, free-form JSON so
-- the UI can add new toggles without DDL.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS user_settings (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
