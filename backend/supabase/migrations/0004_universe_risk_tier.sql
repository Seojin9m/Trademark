-- Add risk_tier column to universe + universe_history.
--
-- Main introduced this column to classify tickers by trading-risk profile
-- (standard / moderate_risk / high_risk). Values are produced by
-- src/discovery/screener.py:classify_risk_tier() when a new ticker is
-- promoted into the universe. For existing rows we default to 'standard',
-- matching main's pre-classification baseline.

ALTER TABLE universe
    ADD COLUMN IF NOT EXISTS risk_tier VARCHAR NOT NULL DEFAULT 'standard';

ALTER TABLE universe_history
    ADD COLUMN IF NOT EXISTS risk_tier VARCHAR NOT NULL DEFAULT 'standard';
