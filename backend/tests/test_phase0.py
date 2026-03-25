"""Phase 0 validation tests -- verify config, universe, and data sources."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


def test_settings_load():
    assert settings.primary_benchmark == "QQQ"
    assert settings.secondary_benchmark == "XLK"


def test_paths_exist():
    assert settings.paths.project_root.exists()
    assert settings.paths.universe_path.exists()
    assert settings.paths.factor_weights_path.exists()


def test_universe_csv():
    import pandas as pd
    df = pd.read_csv(settings.paths.universe_path)
    assert len(df) >= 70
    assert "ticker" in df.columns
    assert "sub_sector" in df.columns
    assert df["ticker"].duplicated().sum() == 0


def test_factor_weights():
    import json
    with open(settings.paths.factor_weights_path) as f:
        weights = json.load(f)
    assert len(weights) == 5
    assert abs(sum(weights.values()) - 1.0) < 0.01


def test_strategy_settings():
    assert settings.strategy.max_single_position_weight == 0.10
    assert settings.strategy.max_positions == 25
    assert settings.strategy.min_decile_change_to_trade == 2


def test_portfolio_state():
    import json
    with open(settings.paths.portfolio_state_path) as f:
        portfolio = json.load(f)
    assert "cash" in portfolio
    assert "positions" in portfolio
    assert isinstance(portfolio["positions"], list)
