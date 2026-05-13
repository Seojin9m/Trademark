-- fundamentals_pit primary key fix.
--
-- The original PK was (ticker, report_date). That's wrong: report_date is
-- the filing/publish date (PIT metadata), not the natural identifier for a
-- quarterly report. Two distinct quarters can share a filing_date when a
-- company files Q-current alongside an amended Q-prior on the same day —
-- which is exactly what Polygon's data surfaces for tickers like ADUS.
--
-- The correct natural key is (ticker, fiscal_period_end): one quarterly
-- report per company per fiscal period end. report_date stays as a
-- non-key column for PIT signaling.
--
-- Side effects:
--   * fiscal_period_end becomes NOT NULL (was nullable). Existing rows
--     with NULL fiscal_period_end get deleted up-front — those rows are
--     unusable for YoY computation anyway.
--   * Existing rows that collide on (ticker, fiscal_period_end) get
--     deduplicated, keeping the most recent report_date.

-- Step 1: clear NULL fiscal_period_end rows (broken inputs).
DELETE FROM fundamentals_pit WHERE fiscal_period_end IS NULL;

-- Step 2: collapse legacy duplicates on the new key, keeping the most
-- recent report_date (PIT convention: latest filing wins for a quarter).
DELETE FROM fundamentals_pit f
USING fundamentals_pit g
WHERE  f.ticker = g.ticker
  AND  f.fiscal_period_end = g.fiscal_period_end
  AND  (f.report_date < g.report_date
        OR (f.report_date = g.report_date AND f.ctid < g.ctid));

-- Step 3: swap the PK.
ALTER TABLE fundamentals_pit DROP CONSTRAINT IF EXISTS fundamentals_pit_pkey;
ALTER TABLE fundamentals_pit ALTER COLUMN fiscal_period_end SET NOT NULL;
ALTER TABLE fundamentals_pit ADD PRIMARY KEY (ticker, fiscal_period_end);

-- Step 4: keep an index on report_date for "what arrived on date X" queries.
CREATE INDEX IF NOT EXISTS fundamentals_pit_report_date_idx
    ON fundamentals_pit (report_date);
