"""Cross-sectional ranker: score and rank the entire universe for today."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.features.composite import compute_composite_scores, store_quality_assessments, store_stock_metrics
from src.db.schema import get_connection


def rank_universe(
    as_of_date: str | None = None,
    factor_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Score and rank all universe tickers as of a given date.

    Returns DataFrame sorted by composite_score descending with all factor
    columns plus quality assessment fields (is_good_stock, quality_score, etc).

    Args:
        as_of_date: Scoring date. Defaults to latest available.
        factor_weights: IC-optimized weights from prior adaptive analysis.
    """
    scores = compute_composite_scores(as_of_date, factor_weights=factor_weights)

    if scores.empty:
        print("WARNING: No scores computed")
        return pd.DataFrame()

    scores = scores.sort_values("composite_score", ascending=False).reset_index(drop=True)
    scores["rank"] = range(1, len(scores) + 1)

    return scores


def store_scores(scores: pd.DataFrame) -> None:
    """Persist today's factor scores to DuckDB and store quality assessments + metrics."""
    if scores.empty:
        return

    con = get_connection()
    date_val = scores["date"].iloc[0]

    con.execute("DELETE FROM factor_scores WHERE date = $1", [str(date_val)])

    # Only insert the columns that factor_scores table expects
    score_cols = scores[["ticker", "date", "momentum_12m1m", "eps_growth_yoy",
                         "revenue_growth_yoy", "gross_margin_trend", "relative_valuation",
                         "composite_score", "score_decile"]].copy()

    con.register("scores_df", score_cols)
    con.execute("""
        INSERT INTO factor_scores
        SELECT ticker, date, momentum_12m1m, eps_growth_yoy,
               revenue_growth_yoy, gross_margin_trend, relative_valuation,
               composite_score, score_decile
        FROM scores_df
    """)
    con.close()
    print(f"Stored {len(scores)} factor scores for {date_val}")

    # Also store quality assessments and stock metrics for the data grid
    store_quality_assessments(scores)
    store_stock_metrics(scores)


def get_prior_deciles(as_of_date: str) -> dict[str, int]:
    """Get the most recent prior deciles for turnover control."""
    con = get_connection()
    result = con.execute("""
        SELECT ticker, score_decile
        FROM factor_scores
        WHERE date = (
            SELECT MAX(date) FROM factor_scores WHERE date < CAST($1 AS DATE)
        )
    """, [as_of_date]).fetchdf()
    con.close()

    if result.empty:
        return {}

    return dict(zip(result["ticker"], result["score_decile"]))
