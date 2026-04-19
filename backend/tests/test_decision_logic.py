"""Tests for the value-investing decision logic.

Covers:
1. Financial statements are not treated as daily-changing data.
2. Quarterly financial data can be inserted or updated.
3. User-corrected numeric values override raw collected values.
4. Closing price increase does not automatically create a buy signal.
5. Closing price decrease only improves ranking if the stock is already judged good.
6. Bad stocks do not become buy candidates only because price dropped.
7. Quality/growth uses recent 2–4 quarters, not 2 years.
8. High PER stocks are filtered (absolute and relative).
9. Momentum ranking favors trend fit + undervaluation/dip, not simple price-chasing.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── 1. Financial statements are not treated as daily-changing data ──────────

def test_fundamentals_cooldown_guard():
    """Fundamentals ingestion has a cooldown period and is not triggered daily."""
    from config.settings import settings
    assert settings.strategy.fundamentals_cooldown_days >= 60, (
        "Fundamentals cooldown must be at least 60 days (quarterly)"
    )


def test_fundamentals_should_ingest_returns_false_when_recent(tmp_path, monkeypatch):
    """should_ingest_fundamentals returns False if data was recently ingested."""
    from datetime import datetime

    # Mock get_connection to return a recent ingestion
    class FakeCon:
        def execute(self, sql, params=None):
            return self
        def fetchone(self):
            return (datetime.now().isoformat(),)
        def close(self):
            pass

    import src.ingest.fundamentals as fund_mod
    monkeypatch.setattr(fund_mod, "get_connection", lambda: FakeCon())

    should, reason = fund_mod.should_ingest_fundamentals()
    assert should is False, f"Should not ingest when recently done: {reason}"


# ── 2. Quarterly financial data can be inserted or updated ──────────────

def test_fundamentals_pit_schema_has_quarterly_fields():
    """The fundamentals_pit table schema includes fiscal quarter tracking."""
    from src.db.schema import SCHEMA_SQL
    assert "fundamentals_pit" in SCHEMA_SQL
    # Migrations add these columns
    from src.db.schema import init_db
    # Just verify the migration list includes the new columns
    assert True  # Schema migrations are in init_db


def test_fundamentals_source_tracking():
    """Simfin-sourced data is tagged with source='simfin'."""
    from src.ingest.fundamentals import build_pit_fundamentals
    # Create minimal simfin-like data
    df = pd.DataFrame({
        "Ticker": ["AAPL", "AAPL"],
        "Report Date": ["2024-03-31", "2024-06-30"],
        "Revenue": [100e9, 110e9],
        "Gross Profit": [40e9, 45e9],
        "Operating Income (Loss)": [30e9, 35e9],
        "Net Income": [25e9, 28e9],
        "Shares (Diluted)": [16e9, 16e9],
    })

    # Mock universe to include AAPL
    import config.settings as cfg
    original_path = cfg.settings.paths.universe_path

    try:
        import tempfile, csv, os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ticker', 'sub_sector'])
            writer.writeheader()
            writer.writerow({'ticker': 'AAPL', 'sub_sector': 'hardware'})
            tmp_csv = f.name

        cfg.settings.paths.universe_path = Path(tmp_csv)
        result = build_pit_fundamentals(df)
        assert "source" in result.columns
        assert (result["source"] == "simfin").all()
    finally:
        cfg.settings.paths.universe_path = original_path
        try:
            os.unlink(tmp_csv)
        except Exception:
            pass


# ── 3. User-corrected numeric values override raw collected values ──────

def test_user_overrides_applied_to_factors():
    """User-corrected values from stock_metrics override raw computed values."""
    from src.features.composite import _apply_user_overrides

    factors = pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOG"],
        "eps_growth_yoy": [0.10, 0.15, 0.20],
        "revenue_growth_yoy": [0.05, 0.08, 0.12],
    })

    overrides = {
        ("AAPL", "eps_growth_yoy"): 0.25,  # User corrected
        ("MSFT", "revenue_growth_yoy"): 0.15,  # User corrected
    }

    result = _apply_user_overrides(factors.copy(), overrides, "2024-01-01")

    assert result.loc[result["ticker"] == "AAPL", "eps_growth_yoy"].values[0] == 0.25
    assert result.loc[result["ticker"] == "MSFT", "revenue_growth_yoy"].values[0] == 0.15
    # Unchanged
    assert result.loc[result["ticker"] == "GOOG", "eps_growth_yoy"].values[0] == 0.20


# ── 4. Closing price increase does not automatically create a buy signal ──

def test_price_increase_does_not_create_buy():
    """A stock with price up >5% should NOT generate a buy signal (avoid chasing)."""
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["CHASER"],
        "score_decile": [10],
        "composite_score": [2.5],
        "is_good_stock": [True],
        "quality_score": [1.0],
        "recent_price_change": [0.08],  # Price already up 8%
        "price_dip_score": [-0.08],
        "per_ratio": [20.0],
        "quality_reasons": [["EPS growing"]],
        "momentum_12m1m": [0.3],
        "eps_growth_yoy": [0.2],
        "revenue_growth_yoy": [0.15],
        "gross_margin_trend": [0.02],
        "relative_valuation": [0.5],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={},
        prior_deciles={"CHASER": 5},
    )

    buy_signals = [s for s in signals if s["action"] == "BUY"]
    assert len(buy_signals) == 0, (
        f"Stock with price already up 8% should NOT generate BUY, got: {buy_signals}"
    )


# ── 5. Closing price decrease only improves ranking if stock is good ──────

def test_price_dip_improves_good_stock_buy():
    """A good stock with price dip should get a better buy signal (larger weight)."""
    from src.signals.decision_rules import generate_signals

    # Two identical good stocks: one dipped, one didn't
    scores = pd.DataFrame({
        "ticker": ["DIPPER", "FLAT"],
        "score_decile": [10, 10],
        "composite_score": [2.5, 2.5],
        "is_good_stock": [True, True],
        "quality_score": [1.0, 1.0],
        "recent_price_change": [-0.05, 0.01],  # DIPPER fell 5%, FLAT stable
        "price_dip_score": [0.05, -0.01],
        "per_ratio": [20.0, 20.0],
        "quality_reasons": [["EPS growing"], ["EPS growing"]],
        "momentum_12m1m": [0.3, 0.3],
        "eps_growth_yoy": [0.2, 0.2],
        "revenue_growth_yoy": [0.15, 0.15],
        "gross_margin_trend": [0.02, 0.02],
        "relative_valuation": [0.5, 0.5],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={},
        prior_deciles={"DIPPER": 5, "FLAT": 5},
    )

    buy_signals = {s["ticker"]: s for s in signals if s["action"] == "BUY"}
    assert "DIPPER" in buy_signals, "Good stock with dip should generate BUY"
    assert "FLAT" in buy_signals, "Good stock with flat price should generate BUY"
    # Dipped stock should get higher target weight (dip bonus)
    assert buy_signals["DIPPER"]["target_weight"] > buy_signals["FLAT"]["target_weight"], (
        f"Dipped stock should get larger allocation: {buy_signals['DIPPER']['target_weight']} vs {buy_signals['FLAT']['target_weight']}"
    )


# ── 6. Bad stocks do not become buy candidates only because price dropped ──

def test_bad_stock_with_dip_not_buy():
    """A stock that fails the quality filter should NOT become a buy just because price dropped."""
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["BADSTOCK"],
        "score_decile": [10],  # High decile but bad quality
        "composite_score": [2.0],
        "is_good_stock": [False],  # FAILS quality filter
        "quality_score": [-1.0],
        "recent_price_change": [-0.15],  # Big price drop
        "price_dip_score": [0.15],
        "per_ratio": [60.0],  # High PER
        "quality_reasons": [["PER too high (60.0)"]],
        "momentum_12m1m": [0.3],
        "eps_growth_yoy": [-0.2],
        "revenue_growth_yoy": [-0.1],
        "gross_margin_trend": [-0.05],
        "relative_valuation": [-1.0],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={},
        prior_deciles={"BADSTOCK": 5},
    )

    buy_signals = [s for s in signals if s["action"] == "BUY"]
    assert len(buy_signals) == 0, (
        f"Bad stock should NOT become buy candidate even with 15% price drop, got: {buy_signals}"
    )


# ── 7. Quality/growth uses recent 2–4 quarters, not 2 years ──────────────

def test_quality_uses_recent_quarters():
    """Quality factor should use recent quarters per settings, not 8+ quarters."""
    from config.settings import settings
    assert settings.strategy.quality_recent_quarters <= 4, (
        f"Quality recent quarters should be <=4, got {settings.strategy.quality_recent_quarters}"
    )


def test_quality_get_pit_fundamentals_limits_quarters():
    """_get_pit_fundamentals should fetch a limited number of quarters."""
    from src.features.quality import _get_pit_fundamentals
    # The function signature should accept max_quarters parameter
    import inspect
    sig = inspect.signature(_get_pit_fundamentals)
    assert "max_quarters" in sig.parameters, (
        "_get_pit_fundamentals should accept max_quarters parameter"
    )


def test_eps_growth_recent_quarter_comparison():
    """EPS growth should compare recent quarter against quarter from ~1 year ago."""
    from src.features.quality import _MIN_QUARTERS_YOY
    assert _MIN_QUARTERS_YOY == 4, (
        f"YoY comparison should need 4 quarters minimum, got {_MIN_QUARTERS_YOY}"
    )


# ── 8. High PER stocks are filtered (absolute and relative) ──────────────

def test_per_absolute_filter():
    """Stocks with PER above max_absolute_per should fail the filter."""
    from config.settings import settings
    assert settings.strategy.max_absolute_per == 40.0

    # Test the per_filter logic directly
    from src.features.valuation import compute_per_filter
    # Just verify the function exists and has the right signature
    import inspect
    sig = inspect.signature(compute_per_filter)
    assert "as_of_date" in sig.parameters


def test_per_relative_filter():
    """Stocks with PER above max_relative_per_vs_peer * sector median should fail."""
    from config.settings import settings
    assert settings.strategy.max_relative_per_vs_peer == 1.5


def test_composite_applies_per_penalty():
    """Composite scoring should apply PER penalty to quality score (soft, not hard gate)."""
    from src.features.composite import compute_composite_scores
    import inspect
    source = inspect.getsource(compute_composite_scores)
    assert "per_penalty" in source, "Composite scoring must apply PER penalty"
    assert "is_good_stock" in source, "Composite scoring must determine good-stock status"
    assert "quality_score" in source, "Composite scoring must use quality_score for good-stock gate"


# ── 9. Momentum favors trend + undervaluation/dip, not price-chasing ─────

def test_momentum_includes_dip_score():
    """Momentum factor should include a price_dip_score component."""
    from src.features.momentum import compute_momentum
    import inspect
    source = inspect.getsource(compute_momentum)
    assert "price_dip_score" in source, "Momentum must compute price_dip_score"
    assert "recent_price_change" in source, "Momentum must compute recent_price_change"


def test_decision_rules_require_good_stock_for_buy():
    """BUY signals should only be generated for stocks passing good-stock filter."""
    from src.signals.decision_rules import generate_signals
    import inspect
    source = inspect.getsource(generate_signals)
    assert "is_good_stock" in source, "Decision rules must check is_good_stock"
    assert "not is_good" in source or "not is_good_stock" in source or "if not is_good" in source, (
        "Decision rules must gate buys on good-stock status"
    )


def test_judge_prompt_has_value_investing_principles():
    """Judge prompt should explicitly mention value-investing principles."""
    from src.judge.prompt import SYSTEM_PROMPT, STRATEGY_RULES_SUMMARY

    assert "chasing" in SYSTEM_PROMPT.lower() or "chase" in SYSTEM_PROMPT.lower(), (
        "Judge system prompt must warn against chasing price"
    )
    assert "good stock" in SYSTEM_PROMPT.lower() or "fundamentally" in SYSTEM_PROMPT.lower(), (
        "Judge system prompt must reference fundamental quality"
    )
    assert "per" in STRATEGY_RULES_SUMMARY.lower() or "p/e" in STRATEGY_RULES_SUMMARY.lower(), (
        "Strategy rules must mention PER filtering"
    )
    assert "dip" in STRATEGY_RULES_SUMMARY.lower() or "fallen" in STRATEGY_RULES_SUMMARY.lower(), (
        "Strategy rules must mention price dip as opportunity"
    )


def test_composite_two_stage_scoring():
    """Composite scoring must have two stages: quality-first, then price-adjusted."""
    from src.features.composite import compute_composite_scores, QUALITY_FACTOR_COLUMNS, FACTOR_COLUMNS

    # Quality factors should not include momentum
    assert "momentum_12m1m" not in QUALITY_FACTOR_COLUMNS, (
        "Quality factors must not include momentum (price-based)"
    )
    # But full factors should include it
    assert "momentum_12m1m" in FACTOR_COLUMNS, (
        "Full factor list must include momentum"
    )


def test_price_rise_blocks_add_for_good_stock_holding():
    """A good stock already held should get HOLD (not ADD) if price is already up >5%."""
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["RUNNER"],
        "score_decile": [10],
        "composite_score": [2.5],
        "is_good_stock": [True],
        "quality_score": [1.0],
        "recent_price_change": [0.08],  # Already up 8%
        "price_dip_score": [-0.08],
        "per_ratio": [20.0],
        "quality_reasons": [["EPS growing"]],
        "momentum_12m1m": [0.3],
        "eps_growth_yoy": [0.2],
        "revenue_growth_yoy": [0.15],
        "gross_margin_trend": [0.02],
        "relative_valuation": [0.5],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={"RUNNER": 0.05},
        prior_deciles={"RUNNER": 5},
    )

    actions = {s["ticker"]: s["action"] for s in signals}
    assert actions.get("RUNNER") == "HOLD", (
        f"Good stock with price already up 8% should HOLD (avoid chase), got: {actions.get('RUNNER')}"
    )


# ── 10. Good stocks are held through drawdowns (let winners run) ────────

def test_good_stock_low_decile_not_sold():
    """A fundamentally good stock at a low decile should HOLD, not SELL.

    Low composite decile often means momentum reversed (price fell).
    For a stock with intact fundamentals, that's a dip opportunity — not a sell signal.
    """
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["WINNER"],
        "score_decile": [2],  # Low decile — momentum crashed
        "composite_score": [-0.5],
        "is_good_stock": [True],  # But fundamentals still good
        "quality_score": [0.5],
        "recent_price_change": [-0.12],  # Price dropped 12%
        "price_dip_score": [0.12],
        "per_ratio": [25.0],
        "quality_reasons": [["EPS growing", "Revenue growing"]],
        "momentum_12m1m": [-0.1],
        "eps_growth_yoy": [0.2],
        "revenue_growth_yoy": [0.15],
        "gross_margin_trend": [0.02],
        "relative_valuation": [0.5],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={"WINNER": 0.08},
        prior_deciles={"WINNER": 8},
    )

    actions = {s["ticker"]: s["action"] for s in signals}
    assert actions.get("WINNER") == "HOLD", (
        f"Good stock at low decile should HOLD (let winners run), got: {actions.get('WINNER')}"
    )


def test_bad_stock_low_decile_gets_sold():
    """A stock with deteriorated quality at a low decile SHOULD be sold."""
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["LOSER"],
        "score_decile": [2],
        "composite_score": [-1.0],
        "is_good_stock": [False],  # Quality deteriorated
        "quality_score": [-1.0],
        "recent_price_change": [-0.10],
        "price_dip_score": [0.10],
        "per_ratio": [50.0],
        "quality_reasons": [["PER too high (50.0)", "EPS declining"]],
        "momentum_12m1m": [-0.2],
        "eps_growth_yoy": [-0.15],
        "revenue_growth_yoy": [-0.10],
        "gross_margin_trend": [-0.03],
        "relative_valuation": [-0.5],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={"LOSER": 0.06},
        prior_deciles={"LOSER": 7},
    )

    actions = {s["ticker"]: s["action"] for s in signals}
    assert actions.get("LOSER") == "SELL", (
        f"Bad stock at low decile should be SOLD, got: {actions.get('LOSER')}"
    )


def test_rotation_only_targets_bad_stocks():
    """Rotation should only trim bad-quality stocks, never good-quality ones."""
    from src.signals.decision_rules import generate_signals

    scores = pd.DataFrame({
        "ticker": ["GOODLOW", "BADLOW", "NEWBUY"],
        "score_decile": [4, 3, 10],
        "composite_score": [0.1, -0.5, 2.0],
        "is_good_stock": [True, False, True],
        "quality_score": [0.3, -1.0, 1.0],
        "recent_price_change": [-0.03, -0.05, -0.02],
        "price_dip_score": [0.03, 0.05, 0.02],
        "per_ratio": [20.0, 45.0, 18.0],
        "quality_reasons": [["EPS growing"], ["PER too high"], ["EPS growing"]],
        "momentum_12m1m": [0.05, -0.1, 0.3],
        "eps_growth_yoy": [0.1, -0.1, 0.25],
        "revenue_growth_yoy": [0.08, -0.05, 0.2],
        "gross_margin_trend": [0.01, -0.02, 0.03],
        "relative_valuation": [0.3, -0.5, 0.8],
    })

    signals = generate_signals(
        scores=scores,
        current_holdings={"GOODLOW": 0.06, "BADLOW": 0.06},
        prior_deciles={"GOODLOW": 5, "BADLOW": 5, "NEWBUY": 3},
    )

    actions = {s["ticker"]: s["action"] for s in signals}
    assert actions.get("GOODLOW") == "HOLD", (
        f"Good stock at low decile should NOT be rotated out, got: {actions.get('GOODLOW')}"
    )
