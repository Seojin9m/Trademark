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
    """Persist today's factor scores. Routes to DuckDB or Postgres path."""
    if scores.empty:
        return

    import os
    backend = (os.getenv("DB_BACKEND") or "duckdb").lower()

    date_val = scores["date"].iloc[0]
    factor_cols = ["ticker", "date", "momentum_12m1m", "eps_growth_yoy",
                   "revenue_growth_yoy", "gross_margin_trend", "relative_valuation",
                   "composite_score", "score_decile"]
    if "forward_estimate_revision" in scores.columns:
        factor_cols.insert(-2, "forward_estimate_revision")

    score_cols = scores[factor_cols].copy()
    _d = pd.to_datetime(score_cols["date"], errors="coerce")
    if _d.isna().any():
        raise ValueError("factor_scores insert: null or invalid date in scores dataframe")
    score_cols["date"] = _d.dt.date

    if backend == "postgres":
        _store_scores_postgres(score_cols, factor_cols, date_val)
    else:
        _store_scores_duckdb(score_cols, factor_cols, date_val)

    # Quality + per-ticker metrics derived from `scores` (the unfiltered
    # DataFrame; score_cols has only the factor_scores columns). Backend-
    # agnostic — these functions go through get_connection() themselves.
    store_quality_assessments(scores)
    store_stock_metrics(scores)

    print(f"Stored {len(scores)} factor scores for {date_val}")


def _store_scores_duckdb(score_cols: pd.DataFrame, factor_cols: list[str], date_val) -> None:
    con = get_connection()
    con.execute("DELETE FROM factor_scores WHERE date = $1", [str(date_val)])
    col_list = ", ".join(factor_cols)
    con.register("scores_df", score_cols)
    con.execute(f"""
        INSERT INTO factor_scores ({col_list})
        SELECT {col_list}
        FROM scores_df
    """)
    con.close()


def _store_scores_postgres(score_cols: pd.DataFrame, factor_cols: list[str], date_val) -> None:
    """Postgres path — DELETE current date + COPY in one atomic transaction.

    Mirrors the pattern used in store_prices/store_fundamentals: open a raw
    psycopg2 connection (autocommit=False) so the DELETE + COPY either both
    commit or both roll back.
    """
    import io
    from src.db.postgres import get_pg_connection

    buf = io.StringIO()
    score_cols.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    raw_conn = get_pg_connection(role="pooled")
    raw_conn.autocommit = False
    try:
        with raw_conn.cursor() as cur:
            cur.execute("DELETE FROM factor_scores WHERE date = %s", [str(date_val)])
            cur.copy_expert(
                f"COPY factor_scores ({', '.join(factor_cols)}) "
                "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()


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
