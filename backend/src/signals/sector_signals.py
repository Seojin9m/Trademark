"""Sector signals + market summary for the Rankings page.

Both products are computed once per trading day by the EOD pipeline and read
unchanged by every user. Nothing here is per-user.

Outputs:
    sector_signals  — one row per (sector, date). Per-sector alpha vs the
                      universe-wide composite_score average, breadth count
                      (D1-D3 names), and a derived BUY / SELL action.
    market_summary  — one row per date. Top-of-page stance + SPX/VIX snapshot.

The sector alpha definition is intentionally simple — sector_mean -
universe_mean of composite_score, scaled so the numbers land in the same
order-of-magnitude range the design mocks use (±3% monthly). The exact
calibration constant can be tuned later as we gather real signal data.
"""

from __future__ import annotations

import os
import sys
from datetime import date as _date_t
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.db.schema import get_connection


# Multiplier applied to (sector_mean - universe_mean) of composite_score so
# the resulting "alpha_pct" lands in a percent-like range. composite_score
# is roughly in [0, 10]; the spread between sectors is typically ~0.5, and
# we want the displayed value to read like a 1-month alpha (±3%).
ALPHA_SCALE = 6.0


def compute_sector_signals(as_of_date: str | None = None) -> pd.DataFrame:
    """Compute one alpha row per sector for the given date.

    Reads factor_scores + universe (joined on ticker). Returns a DataFrame
    with columns (sector, date, alpha_pct, breadth_d1_3, total_names, action).
    Empty DataFrame if no scores exist for the date.
    """
    con = get_connection()
    try:
        # Pick the date to score — caller may pass a specific date, else
        # use the latest available row in factor_scores.
        if as_of_date is None:
            row = con.execute("SELECT MAX(date) FROM factor_scores").fetchone()
            if not row or row[0] is None:
                return pd.DataFrame()
            as_of_date = str(row[0])

        df = con.execute(
            """
            SELECT u.sector, f.ticker, f.composite_score, f.score_decile
            FROM factor_scores f
            JOIN universe u ON u.ticker = f.ticker
            WHERE f.date = CAST($1 AS DATE)
              AND u.sector IS NOT NULL
            """,
            [as_of_date],
        ).fetchdf()
    finally:
        con.close()

    if df.empty:
        return pd.DataFrame()

    universe_mean = df["composite_score"].mean()

    # Decile 10 is the top of the universe in this codebase (compute_composite_scores
    # uses pd.qcut, so label=10 corresponds to the highest composite_score bin).
    # breadth_top counts how many of the sector's names sit in the top three deciles.
    grouped = df.groupby("sector").agg(
        mean_score=("composite_score", "mean"),
        total_names=("ticker", "count"),
        breadth_top=("score_decile", lambda s: int((s >= 8).sum())),
    ).reset_index()

    grouped["alpha_pct"] = ((grouped["mean_score"] - universe_mean) * ALPHA_SCALE).round(2)
    grouped["action"] = grouped["alpha_pct"].apply(lambda a: "BUY" if a >= 0 else "SELL")
    grouped["date"] = pd.to_datetime(as_of_date).date()

    return grouped[["sector", "date", "alpha_pct", "breadth_top", "total_names", "action"]]


def store_sector_signals(df: pd.DataFrame) -> None:
    """Upsert sector_signals rows for a single date. Replaces same-date rows."""
    if df.empty:
        return

    as_of = df["date"].iloc[0]
    con = get_connection()
    try:
        con.execute("DELETE FROM sector_signals WHERE date = CAST($1 AS DATE)", [str(as_of)])
        for _, row in df.iterrows():
            con.execute(
                """
                INSERT INTO sector_signals
                    (sector, date, alpha_pct, breadth_top, total_names, action)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                [
                    row["sector"],
                    str(row["date"]),
                    float(row["alpha_pct"]),
                    int(row["breadth_top"]),
                    int(row["total_names"]),
                    row["action"],
                ],
            )
    finally:
        con.close()

    print(f"Stored {len(df)} sector_signals rows for {as_of}")


def compute_market_summary(
    as_of_date: str | None = None,
    sector_signals_df: pd.DataFrame | None = None,
    with_narrative: bool = True,
) -> dict | None:
    """Build a single market_summary row for the given date.

    Pulls latest SPX (via SPY) close + 1d change from prices and latest VIX
    from macro_data. Stance is derived from how many sectors signal BUY.
    """
    con = get_connection()
    try:
        if as_of_date is None:
            row = con.execute("SELECT MAX(date) FROM factor_scores").fetchone()
            if not row or row[0] is None:
                return None
            as_of_date = str(row[0])

        # SPY: latest two closes for 1d change.
        spy = con.execute(
            """
            SELECT date, close
            FROM prices
            WHERE ticker = 'SPY' AND date <= CAST($1 AS DATE)
            ORDER BY date DESC
            LIMIT 2
            """,
            [as_of_date],
        ).fetchdf()

        spx_close: float | None = None
        spx_change: float | None = None
        if not spy.empty:
            spx_close = float(spy["close"].iloc[0])
            if len(spy) >= 2 and float(spy["close"].iloc[1]) > 0:
                spx_change = (spx_close - float(spy["close"].iloc[1])) / float(spy["close"].iloc[1])

        # VIX from macro_data (FRED series VIXCLS).
        vix_row = con.execute(
            """
            SELECT value
            FROM macro_data
            WHERE series_id = 'VIXCLS' AND date <= CAST($1 AS DATE)
            ORDER BY date DESC
            LIMIT 1
            """,
            [as_of_date],
        ).fetchone()
        vix = float(vix_row[0]) if vix_row and vix_row[0] is not None else None
    finally:
        con.close()

    if sector_signals_df is None or sector_signals_df.empty:
        sector_signals_df = compute_sector_signals(as_of_date)

    if sector_signals_df.empty:
        return None

    buy_sectors = int((sector_signals_df["action"] == "BUY").sum())
    sell_sectors = int((sector_signals_df["action"] == "SELL").sum())

    stance = _derive_stance(buy_sectors, sell_sectors)
    narrative = ""
    if with_narrative:
        try:
            narrative = _generate_narrative(stance, sector_signals_df, spx_change, vix)
        except Exception as exc:
            print(f"  WARNING: narrative generation failed, using fallback: {exc}")
            narrative = _fallback_narrative(stance, buy_sectors, sell_sectors)
    else:
        narrative = _fallback_narrative(stance, buy_sectors, sell_sectors)

    return {
        "date": str(pd.to_datetime(as_of_date).date()),
        "stance": stance,
        "spx_close": spx_close,
        "spx_change": spx_change,
        "vix": vix,
        "buy_sectors": buy_sectors,
        "sell_sectors": sell_sectors,
        "narrative": narrative,
    }


def store_market_summary(summary: dict) -> None:
    """Upsert a single market_summary row, replacing any existing row for the date."""
    con = get_connection()
    try:
        con.execute("DELETE FROM market_summary WHERE date = CAST($1 AS DATE)", [summary["date"]])
        con.execute(
            """
            INSERT INTO market_summary
                (date, stance, spx_close, spx_change, vix, buy_sectors, sell_sectors, narrative)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            [
                summary["date"],
                summary["stance"],
                summary["spx_close"],
                summary["spx_change"],
                summary["vix"],
                summary["buy_sectors"],
                summary["sell_sectors"],
                summary["narrative"],
            ],
        )
    finally:
        con.close()

    print(f"Stored market_summary for {summary['date']} (stance={summary['stance']})")


def _derive_stance(buy: int, sell: int) -> str:
    if buy >= 7:
        return "CONSTRUCTIVE"
    if sell >= 7:
        return "DEFENSIVE"
    return "NEUTRAL"


def _fallback_narrative(stance: str, buy: int, sell: int) -> str:
    return (
        f"Pipeline favors {buy} sector{'s' if buy != 1 else ''} as BUY and "
        f"flags {sell} as SELL. Overall stance: {stance.lower()}."
    )


def _generate_narrative(
    stance: str,
    sectors: pd.DataFrame,
    spx_change: float | None,
    vix: float | None,
) -> str:
    """Two-sentence Claude-generated market narrative. ~$0.01 / day at sonnet-4-6."""
    import anthropic
    from config.settings import settings

    if not getattr(settings.api_keys, "anthropic_api_key", None):
        return _fallback_narrative(
            stance,
            int((sectors["action"] == "BUY").sum()),
            int((sectors["action"] == "SELL").sum()),
        )

    top_buys = sectors[sectors["action"] == "BUY"].nlargest(3, "alpha_pct")
    top_sells = sectors[sectors["action"] == "SELL"].nsmallest(2, "alpha_pct")

    buys_str = ", ".join(f"{r.sector} (+{r.alpha_pct:.1f}%)" for r in top_buys.itertuples())
    sells_str = ", ".join(f"{r.sector} ({r.alpha_pct:.1f}%)" for r in top_sells.itertuples())

    spx_str = f"{spx_change*100:+.2f}% on SPX" if spx_change is not None else "SPX unchanged"
    vix_str = f"VIX {vix:.1f}" if vix is not None else "VIX n/a"

    user_prompt = (
        f"Market stance: {stance}. {spx_str}. {vix_str}.\n"
        f"Strongest sector signals (BUY): {buys_str or 'none'}.\n"
        f"Weakest sector signals (SELL): {sells_str or 'none'}.\n\n"
        "Write a 2-sentence market narrative for a trader dashboard. Be specific "
        "about which sectors are leading vs lagging. No preamble, no quote marks, "
        "no markdown. Plain text under 60 words."
    )

    client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)
    resp = client.messages.create(
        model=settings.judge.model,
        max_tokens=200,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip() if resp.content else ""
    return text or _fallback_narrative(
        stance,
        int((sectors["action"] == "BUY").sum()),
        int((sectors["action"] == "SELL").sum()),
    )


def run_rankings_eod(as_of_date: str | None = None, with_narrative: bool = True) -> dict:
    """One-shot helper used by the EOD scheduler to refresh both products."""
    sigs = compute_sector_signals(as_of_date)
    if sigs.empty:
        print("  No sector_signals computed (factor_scores empty?)")
        return {"sector_signals": 0, "market_summary": None}
    store_sector_signals(sigs)

    summary = compute_market_summary(
        as_of_date=str(sigs["date"].iloc[0]),
        sector_signals_df=sigs,
        with_narrative=with_narrative,
    )
    if summary is not None:
        store_market_summary(summary)

    return {"sector_signals": len(sigs), "market_summary": summary}


if __name__ == "__main__":
    out = run_rankings_eod()
    print(out)
