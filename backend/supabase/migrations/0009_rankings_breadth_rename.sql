-- Rename sector_signals.breadth_d1_3 -> breadth_top because the column
-- semantics didn't match the name: in this codebase decile 10 is the
-- best-scoring decile (compute_composite_scores uses pd.qcut bottom-up),
-- so the "top-3 deciles" count is deciles 8-10, not 1-3. The original
-- name was copied verbatim from the design mock, which assumed the
-- inverse convention.
--
-- The data populated under the old name is one-day-old and easy to
-- recompute, so we just rename. The Python writer is updated in the
-- same change to count `score_decile >= 8`.

ALTER TABLE sector_signals
    RENAME COLUMN breadth_d1_3 TO breadth_top;
