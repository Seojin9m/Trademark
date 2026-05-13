-- Forward analyst estimates (weekly snapshots) + signal quality log.
--
-- These two tables existed in the DuckDB schema (src/db/schema.py) but were
-- never ported to Postgres in the initial migration. The forward_estimates
-- module silently fell back to "table doesn't exist" errors until now.

CREATE TABLE IF NOT EXISTS forward_estimates (
    ticker                  VARCHAR NOT NULL,
    fetch_date              DATE NOT NULL,
    eps_est_current_q       DOUBLE PRECISION,
    eps_est_next_q          DOUBLE PRECISION,
    eps_est_current_y       DOUBLE PRECISION,
    eps_est_next_y          DOUBLE PRECISION,
    num_analysts            INTEGER,
    price_target_mean       DOUBLE PRECISION,
    price_target_high       DOUBLE PRECISION,
    price_target_low        DOUBLE PRECISION,
    price_target_current    DOUBLE PRECISION,
    growth_est_next_y       DOUBLE PRECISION,
    recommendation_mean     DOUBLE PRECISION,
    source                  VARCHAR DEFAULT 'yahoo',
    created_at              TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, fetch_date)
);

CREATE INDEX IF NOT EXISTS forward_estimates_fetch_date_idx
    ON forward_estimates (fetch_date DESC);

-- Signal quality log: per-factor IC and hit-rate snapshots used by the
-- adaptive learning loop. Same omission from the initial migration.
CREATE TABLE IF NOT EXISTS signal_quality_log (
    run_date            DATE NOT NULL,
    factor_name         VARCHAR NOT NULL,
    ic_value            DOUBLE PRECISION,
    hit_rate            DOUBLE PRECISION,
    avg_excess_return   DOUBLE PRECISION,
    n_signals           INTEGER,
    computed_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (run_date, factor_name)
);
