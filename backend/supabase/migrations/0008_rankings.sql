-- Rankings page infrastructure.
--
-- Adds the 11-sector Yahoo-style taxonomy column to universe and creates two
-- new tables — sector_signals and market_summary — that the EOD pipeline
-- writes once per trading day and the Rankings page reads.
--
-- The existing universe.sub_sector column (e.g. 'semiconductors', 'pharma')
-- is too granular for the top-of-funnel Rankings view, which buckets into the
-- 11 standard sectors (Technology, Consumer Cyclical, etc.). We keep both:
-- sub_sector for per-ticker analysis, sector for sector-level rollups.

ALTER TABLE universe          ADD COLUMN IF NOT EXISTS sector VARCHAR;
ALTER TABLE universe_history  ADD COLUMN IF NOT EXISTS sector VARCHAR;

-- Backfill from sub_sector. The mapping is deliberately a single CASE so
-- adding a new sub_sector means editing one place.
UPDATE universe SET sector = CASE
    WHEN sub_sector IN ('semiconductors','hardware','enterprise_software',
                        'cloud_software','ai_infrastructure','cybersecurity')
        THEN 'Technology'
    WHEN sub_sector IN ('internet_platforms','media_entertainment','telecom')
        THEN 'Consumer Services'
    WHEN sub_sector IN ('retail','restaurants','autos')
        THEN 'Consumer Cyclical'
    WHEN sub_sector IN ('food_beverage','household_products')
        THEN 'Consumer Defensive'
    WHEN sub_sector IN ('aerospace_defense','industrial_machinery','transports')
        THEN 'Industrials'
    WHEN sub_sector IN ('payments','banks','capital_markets','insurance')
        THEN 'Financial'
    WHEN sub_sector IN ('pharma','biotech','managed_care',
                        'healthcare_equipment','healthcare_services')
        THEN 'Healthcare'
    WHEN sub_sector = 'materials'       THEN 'Basic Materials'
    WHEN sub_sector IN ('energy_majors','midstream','oil_services')
        THEN 'Energy'
    WHEN sub_sector = 'utilities'       THEN 'Utilities'
    WHEN sub_sector = 'reits'           THEN 'Real Estate'
    ELSE 'Consumer Cyclical'
END
WHERE sector IS NULL;

-- Per-ticker overrides where sub_sector→sector misclassifies vs Yahoo.
-- Amazon and Shopify are e-commerce platforms but Yahoo files them under
-- Consumer Cyclical, not Communication / Internet.
UPDATE universe SET sector = 'Consumer Cyclical'
    WHERE ticker IN ('AMZN','SHOP') AND sector <> 'Consumer Cyclical';

-- ===========================================================================
-- sector_signals — one row per (sector, date). Daily snapshot of how the
-- pipeline's stock-selection signal is positioning each sector.
--   alpha_pct: weighted avg composite_score for the sector minus the
--              universe-wide avg, scaled to a percent-like number.
--   breadth_d1_3: count of names in deciles 1-3 (the bullish tail).
--   action: derived 'BUY' (alpha >= 0) or 'SELL' (alpha < 0).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS sector_signals (
    sector       VARCHAR NOT NULL,
    date         DATE NOT NULL,
    alpha_pct    DOUBLE PRECISION,
    breadth_d1_3 INTEGER,
    total_names  INTEGER,
    action       VARCHAR,
    PRIMARY KEY (sector, date)
);

CREATE INDEX IF NOT EXISTS sector_signals_date_idx
    ON sector_signals (date DESC);

-- ===========================================================================
-- market_summary — one row per trading date. Drives the right-hand "Market
-- Stance" card on the Rankings page.
--   stance: 'CONSTRUCTIVE' | 'NEUTRAL' | 'DEFENSIVE'.
--   spx_close / spx_change: latest close and pct change (decimal, e.g. 0.0042).
--   vix: last-known VIX print.
--   buy_sectors / sell_sectors: counts derived from sector_signals.
--   narrative: optional Claude-generated paragraph; empty string is fine.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS market_summary (
    date         DATE PRIMARY KEY,
    stance       VARCHAR,
    spx_close    DOUBLE PRECISION,
    spx_change   DOUBLE PRECISION,
    vix          DOUBLE PRECISION,
    buy_sectors  INTEGER,
    sell_sectors INTEGER,
    narrative    TEXT,
    created_at   TIMESTAMPTZ DEFAULT now()
);
