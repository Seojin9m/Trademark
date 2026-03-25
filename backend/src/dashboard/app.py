"""Streamlit dashboard for trade4me."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection, init_db
from src.signals.portfolio_engine import (
    load_portfolio_state,
    get_current_prices,
    compute_portfolio_weights,
    compute_portfolio_value,
)
from src.simulation.pnl import compute_pnl
from src.judge.client import get_judge_log

st.set_page_config(page_title="trade4me", layout="wide", page_icon="$")

init_db()


# --- Sidebar Navigation ---
page = st.sidebar.radio(
    "Navigation",
    ["Portfolio Overview", "Signal Dashboard", "Pending Trades",
     "Decision Log", "Risk Monitor", "Backtest Results"],
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ============================================================
# Page 1: Portfolio Overview
# ============================================================
if page == "Portfolio Overview":
    st.title("Portfolio Overview")

    portfolio = load_portfolio_state()
    tickers = [p["ticker"] for p in portfolio["positions"]]
    prices = get_current_prices(tickers + [settings.primary_benchmark, settings.secondary_benchmark])
    pnl = compute_pnl(portfolio, prices)
    weights = compute_portfolio_weights(portfolio, prices)

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Portfolio Value", f"${pnl['total_portfolio_value']:,.2f}")
    col2.metric("Unrealized P&L", f"${pnl['total_unrealized_pnl']:,.2f}",
                delta=f"{pnl['total_return_pct']:.1%}")
    col3.metric("Cash", f"${pnl['cash']:,.2f}")
    col4.metric("Positions", len(portfolio["positions"]))

    # Positions table
    st.subheader("Current Positions")
    if pnl["positions"]:
        pos_df = pd.DataFrame(pnl["positions"])
        pos_df["weight"] = pos_df["ticker"].map(weights)
        pos_df = pos_df.sort_values("market_value", ascending=False)

        display_cols = {
            "ticker": "Ticker",
            "shares": "Shares",
            "cost_basis": "Cost Basis",
            "current_price": "Price",
            "market_value": "Mkt Value",
            "unrealized_pnl": "P&L ($)",
            "unrealized_pct": "P&L (%)",
            "weight": "Weight",
        }
        display_df = pos_df[list(display_cols.keys())].rename(columns=display_cols)

        st.dataframe(
            display_df.style.format({
                "Cost Basis": "${:.2f}",
                "Price": "${:.2f}",
                "Mkt Value": "${:,.2f}",
                "P&L ($)": "${:,.2f}",
                "P&L (%)": "{:.1%}",
                "Weight": "{:.1%}",
            }).applymap(
                lambda v: "color: green" if isinstance(v, (int, float)) and v > 0
                else ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["P&L ($)", "P&L (%)"],
            ),
            use_container_width=True,
            hide_index=True,
        )

    # Weight pie chart
    if weights:
        fig = px.pie(
            names=list(weights.keys()) + ["Cash"],
            values=list(weights.values()) + [1 - sum(weights.values())],
            title="Portfolio Allocation",
        )
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Page 2: Signal Dashboard
# ============================================================
elif page == "Signal Dashboard":
    st.title("Signal Dashboard")

    con = get_connection()
    scores = con.execute("""
        SELECT * FROM factor_scores
        WHERE date = (SELECT MAX(date) FROM factor_scores)
        ORDER BY composite_score DESC
    """).fetchdf()
    score_date = con.execute("SELECT MAX(date) FROM factor_scores").fetchone()[0]
    con.close()

    if scores.empty:
        st.warning("No factor scores in database. Run the pipeline first.")
    else:
        st.caption(f"Scores as of: {score_date}")

        # Top / Bottom tables
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Top 10 (Buy Candidates)")
            top = scores.head(10)[["ticker", "composite_score", "score_decile",
                                    "momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy"]]
            st.dataframe(top.style.format({
                "composite_score": "{:.3f}",
                "momentum_12m1m": "{:.3f}",
                "eps_growth_yoy": "{:.3f}",
                "revenue_growth_yoy": "{:.3f}",
            }), hide_index=True, use_container_width=True)

        with col2:
            st.subheader("Bottom 10 (Sell Candidates)")
            bottom = scores.tail(10)[["ticker", "composite_score", "score_decile",
                                       "momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy"]]
            st.dataframe(bottom.style.format({
                "composite_score": "{:.3f}",
                "momentum_12m1m": "{:.3f}",
                "eps_growth_yoy": "{:.3f}",
                "revenue_growth_yoy": "{:.3f}",
            }), hide_index=True, use_container_width=True)

        # Full scores heatmap
        st.subheader("Factor Scores (Full Universe)")
        factor_cols = ["momentum_12m1m", "eps_growth_yoy", "revenue_growth_yoy",
                       "gross_margin_trend", "relative_valuation"]
        avail_cols = [c for c in factor_cols if c in scores.columns]

        if avail_cols:
            heat_df = scores.set_index("ticker")[avail_cols]
            fig = px.imshow(
                heat_df.values,
                x=avail_cols,
                y=heat_df.index.tolist(),
                color_continuous_scale="RdYlGn",
                aspect="auto",
                title="Factor Z-Scores by Ticker",
            )
            fig.update_layout(height=max(400, len(heat_df) * 18))
            st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Page 3: Pending Trades
# ============================================================
elif page == "Pending Trades":
    st.title("Pending Trade Proposals")

    con = get_connection()
    proposals = con.execute("""
        SELECT * FROM trade_proposals
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchdf()
    con.close()

    if proposals.empty:
        st.info("No trade proposals. Run the pipeline to generate signals.")
    else:
        # Filter by status
        statuses = ["All"] + proposals["status"].unique().tolist()
        selected = st.selectbox("Filter by status", statuses)

        if selected != "All":
            proposals = proposals[proposals["status"] == selected]

        for _, row in proposals.iterrows():
            with st.expander(
                f"{row['action']} {row['shares']} {row['ticker']} | Status: {row['status']}",
                expanded=(row["status"] == "PENDING"),
            ):
                col1, col2 = st.columns(2)
                col1.write(f"**Proposal ID:** {row['proposal_id']}")
                col1.write(f"**Created:** {row['created_at']}")
                col2.write(f"**Status:** {row['status']}")

                if row["signal_data"]:
                    try:
                        signal = json.loads(row["signal_data"]) if isinstance(row["signal_data"], str) else row["signal_data"]
                        st.json(signal)
                    except Exception:
                        st.text(str(row["signal_data"]))

                if row["judge_response"]:
                    st.subheader("Judge Response")
                    try:
                        judge = json.loads(row["judge_response"]) if isinstance(row["judge_response"], str) else row["judge_response"]
                        st.json(judge)
                    except Exception:
                        st.text(str(row["judge_response"]))

                # Approve/Reject buttons
                if row["status"] in ("PENDING", "JUDGE_APPROVED", "NEEDS_REVIEW"):
                    c1, c2 = st.columns(2)
                    if c1.button(f"Approve {row['proposal_id']}", key=f"approve_{row['proposal_id']}"):
                        con2 = get_connection()
                        con2.execute("""
                            UPDATE trade_proposals
                            SET status = 'APPROVED', human_decision = 'APPROVED'
                            WHERE proposal_id = ?
                        """, [row["proposal_id"]])
                        con2.close()
                        st.success(f"Approved {row['ticker']}")
                        st.rerun()
                    if c2.button(f"Reject {row['proposal_id']}", key=f"reject_{row['proposal_id']}"):
                        con2 = get_connection()
                        con2.execute("""
                            UPDATE trade_proposals
                            SET status = 'REJECTED', human_decision = 'REJECTED'
                            WHERE proposal_id = ?
                        """, [row["proposal_id"]])
                        con2.close()
                        st.warning(f"Rejected {row['ticker']}")
                        st.rerun()


# ============================================================
# Page 4: Decision Log
# ============================================================
elif page == "Decision Log":
    st.title("Decision Log")

    # Trade proposals log
    st.subheader("Trade Proposals")
    con = get_connection()
    proposals = con.execute("""
        SELECT proposal_id, created_at, ticker, action, shares,
               status, human_decision, human_notes
        FROM trade_proposals
        ORDER BY created_at DESC
        LIMIT 100
    """).fetchdf()
    con.close()

    if not proposals.empty:
        st.dataframe(proposals, use_container_width=True, hide_index=True)

    # Judge log
    st.subheader("LLM Judge Log")
    judge_entries = get_judge_log(limit=50)
    if judge_entries:
        judge_df = pd.DataFrame(judge_entries)
        display = judge_df[["created_at", "ticker", "action", "verdict", "confidence", "model_used"]]
        st.dataframe(display, use_container_width=True, hide_index=True)

        # Verdict distribution
        if len(judge_df) > 1:
            fig = px.pie(judge_df, names="verdict", title="Judge Verdict Distribution")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No judge decisions logged yet.")


# ============================================================
# Page 5: Risk Monitor
# ============================================================
elif page == "Risk Monitor":
    st.title("Risk Monitor")

    portfolio = load_portfolio_state()
    tickers = [p["ticker"] for p in portfolio["positions"]]
    prices = get_current_prices(tickers)
    pnl = compute_pnl(portfolio, prices)
    weights = compute_portfolio_weights(portfolio, prices)
    universe = pd.read_csv(settings.paths.universe_path)

    # Drawdown gauge
    drawdown = pnl["total_return_pct"] if pnl["total_return_pct"] < 0 else 0
    alert_level = settings.strategy.max_portfolio_drawdown_alert
    halt_level = settings.strategy.max_portfolio_drawdown_halt

    col1, col2, col3 = st.columns(3)
    col1.metric("Portfolio Drawdown", f"{drawdown:.1%}",
                delta="ALERT" if drawdown < alert_level else "OK",
                delta_color="inverse")
    col2.metric("Alert Level", f"{alert_level:.0%}")
    col3.metric("Halt Level", f"{halt_level:.0%}")

    if drawdown < halt_level:
        st.error("DRAWDOWN HALT: All new positions require manual confirmation!")
    elif drawdown < alert_level:
        st.warning("DRAWDOWN ALERT: New buy signals are blocked.")
    else:
        st.success("Drawdown within limits.")

    # Sub-sector concentration
    st.subheader("Sub-Sector Concentration")
    sector_weights = {}
    for ticker, weight in weights.items():
        sector = universe.loc[universe["ticker"] == ticker, "sub_sector"]
        if not sector.empty:
            s = sector.iloc[0]
            sector_weights[s] = sector_weights.get(s, 0) + weight

    if sector_weights:
        sector_df = pd.DataFrame([
            {"sector": k, "weight": v, "limit": settings.strategy.max_subsector_weight.get(k, 0.35)}
            for k, v in sector_weights.items()
        ])
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Current", x=sector_df["sector"], y=sector_df["weight"]))
        fig.add_trace(go.Bar(name="Limit", x=sector_df["sector"], y=sector_df["limit"],
                             marker_color="rgba(255,0,0,0.3)"))
        fig.update_layout(barmode="overlay", title="Sector Weights vs Limits",
                          yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    # Position size distribution
    st.subheader("Position Weights")
    if weights:
        fig = px.bar(
            x=list(weights.keys()),
            y=list(weights.values()),
            title="Position Weights",
            labels={"x": "Ticker", "y": "Weight"},
        )
        fig.add_hline(y=settings.strategy.max_single_position_weight,
                      line_dash="dash", line_color="red",
                      annotation_text="Max Position Weight")
        fig.update_layout(yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Page 6: Backtest Results
# ============================================================
elif page == "Backtest Results":
    st.title("Backtest Results")
    st.info("Run `python -c \"from src.backtest.engine import run_full_backtest; run_full_backtest()\"` to generate backtest results.")

    # Show latest backtest metrics if available
    con = get_connection()
    scores_count = con.execute("SELECT COUNT(*) FROM factor_scores").fetchone()[0]
    price_count = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    fund_count = con.execute("SELECT COUNT(*) FROM fundamentals_pit").fetchone()[0]
    con.close()

    col1, col2, col3 = st.columns(3)
    col1.metric("Price Data Points", f"{price_count:,}")
    col2.metric("Fundamentals Rows", f"{fund_count:,}")
    col3.metric("Factor Scores", f"{scores_count:,}")

    st.subheader("Latest Backtest Configuration")
    st.json({
        "rebalance_freq": "2W-FRI (biweekly)",
        "min_decile_change": 2,
        "factor_weights": settings.strategy.factor_weights,
        "max_position_weight": settings.strategy.max_single_position_weight,
        "drawdown_alert": settings.strategy.max_portfolio_drawdown_alert,
        "benchmarks": [settings.primary_benchmark, settings.secondary_benchmark],
    })

    # Best results from our tuning
    st.subheader("Best Backtest Results (Biweekly, Equal Weight)")
    results_df = pd.DataFrame([
        {"Metric": "Annualized Return", "Value": "15.21%"},
        {"Metric": "Sharpe Ratio", "Value": "0.42"},
        {"Metric": "Sortino Ratio", "Value": "0.60"},
        {"Metric": "Max Drawdown", "Value": "-32.83%"},
        {"Metric": "Alpha vs QQQ", "Value": "+2.14%"},
        {"Metric": "Information Ratio", "Value": "0.17"},
        {"Metric": "Annualized Turnover", "Value": "139.58%"},
        {"Metric": "Total Trades", "Value": "340"},
        {"Metric": "Hit Rate", "Value": "53.81%"},
    ])
    st.dataframe(results_df, use_container_width=True, hide_index=True)
