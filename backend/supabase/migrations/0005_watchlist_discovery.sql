-- Watchlist + discovery_candidates tables (introduced on main).
--
-- watchlist: user-curated list of tickers to track. Separate from universe
-- because a user may want to follow a ticker that's outside the active
-- trading universe (e.g. a foreign listing, a recent IPO).
--
-- discovery_candidates: output of the auto-screener (src/discovery/screener.py).
-- Tickers that pass the screen sit here until promoted into universe.

CREATE TABLE IF NOT EXISTS watchlist (
    ticker          VARCHAR PRIMARY KEY,
    company_name    VARCHAR,
    sub_sector      VARCHAR,
    added_at        TIMESTAMPTZ DEFAULT now(),
    notes           TEXT,
    priority        INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    ticker              VARCHAR NOT NULL,
    company_name        VARCHAR,
    sector              VARCHAR,
    industry            VARCHAR,
    market_cap          VARCHAR,
    discovery_source    VARCHAR,
    discovery_date      DATE,
    discovery_reason    TEXT,
    metrics             JSONB,
    status              VARCHAR DEFAULT 'new',
    risk_tier           VARCHAR DEFAULT 'standard',
    PRIMARY KEY (ticker, discovery_source, discovery_date)
);

CREATE INDEX IF NOT EXISTS discovery_candidates_status_idx
    ON discovery_candidates (status, discovery_date DESC);
