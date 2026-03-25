"""Cross-sectional ranker: score and rank the entire universe for today."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.features.composite import compute_composite_scores
from src.db.schema import get_connection


def rank_universe(as_of_date: str | None = None) -> pd.DataFrame:
    """Score and rank all universe tickers as of a given date.

    Returns DataFrame sorted by composite_score descending with columns:
    ticker, date, momentum_12m1m, eps_growth_yoy, revenue_growth_yoy,
    gross_margin_trend, relative_valuation, composite_score, score_decile
    """
    scores = compute_composite_scores(as_of_date)

    if scores.empty:
        print("WARNING: No scores computed")
        return pd.DataFrame()

    scores = scores.sort_values("composite_score", ascending=False).reset_index(drop=True)
    scores["rank"] = range(1, len(scores) + 1)

    return scores


def store_scores(scores: pd.DataFrame) -> None:
    """Persist today's factor scores to DuckDB."""
    if scores.empty:
        return

    con = get_connection()
    date_val = scores["date"].iloc[0]

    # Delete existing scores for this date
    con.execute("DELETE FROM factor_scores WHERE date = $1", [str(date_val)])

    con.register("scores_df", scores)
    con.execute("""
        INSERT INTO factor_scores
        SELECT ticker, date, momentum_12m1m, eps_growth_yoy,
               revenue_growth_yoy, gross_margin_trend, relative_valuation,
               composite_score, score_decile
        FROM scores_df
    """)
    con.close()
    print(f"Stored {len(scores)} factor scores for {date_val}")


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
