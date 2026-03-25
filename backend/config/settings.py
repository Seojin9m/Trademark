import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent

# Load .env from backend/ first, fall back to repo root
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(REPO_ROOT / ".env")


class APIKeys(BaseSettings):
    polygon_api_key: str = Field(default="")
    simfin_api_key: str = Field(default="")
    fred_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")


class PathSettings(BaseSettings):
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    prices_raw_dir: Path = PROJECT_ROOT / "data" / "raw" / "prices"
    fundamentals_raw_dir: Path = PROJECT_ROOT / "data" / "raw" / "fundamentals"
    events_raw_dir: Path = PROJECT_ROOT / "data" / "raw" / "events"
    portfolio_state_path: Path = PROJECT_ROOT / "data" / "portfolio_state.json"
    universe_path: Path = PROJECT_ROOT / "config" / "universe.csv"
    factor_weights_path: Path = PROJECT_ROOT / "config" / "factor_weights.json"
    duckdb_path: Path = PROJECT_ROOT / "data" / "trade4me.duckdb"
    judge_log_path: Path = PROJECT_ROOT / "logs" / "judge_log.db"


class StrategySettings(BaseSettings):
    # Factor weights (equal weight default)
    factor_weights: dict[str, float] = {
        "momentum_12m1m": 0.20,
        "eps_growth_yoy": 0.20,
        "revenue_growth_yoy": 0.20,
        "gross_margin_trend": 0.20,
        "relative_valuation": 0.20,
    }

    # Position sizing
    max_single_position_weight: float = 0.10
    min_position_size_pct: float = 0.01
    max_cash_pct: float = 0.20
    min_positions: int = 8
    max_positions: int = 25

    # Sub-sector concentration limits
    max_subsector_weight: dict[str, float] = {
        "semiconductors": 0.35,
        "cloud_software": 0.35,
        "internet_platforms": 0.30,
        "hardware": 0.25,
        "enterprise_software": 0.30,
        "cybersecurity": 0.20,
        "fintech": 0.20,
        "ai_infrastructure": 0.30,
    }

    # Drawdown controls
    max_portfolio_drawdown_alert: float = -0.15
    max_portfolio_drawdown_halt: float = -0.20

    # Turnover controls
    max_turnover_per_week_pct: float = 0.15
    min_holding_days: int = 5
    min_decile_change_to_trade: int = 2
    max_new_positions_per_run: int = 3
    max_trades_per_run: int = 5

    # Winsorization
    winsorize_std: float = 3.0

    # Transaction cost assumptions (bps)
    round_trip_cost_bps_large: int = 10  # >$5B market cap
    round_trip_cost_bps_mid: int = 20  # <$5B market cap


class ScheduleSettings(BaseSettings):
    # Daily EOD run time (ET)
    eod_run_hour: int = 17
    eod_run_minute: int = 30
    timezone: str = "US/Eastern"


class JudgeSettings(BaseSettings):
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.0
    max_reject_rate_30d: float = 0.30  # investigate if >30% rejects


class Settings(BaseSettings):
    api_keys: APIKeys = APIKeys()
    paths: PathSettings = PathSettings()
    strategy: StrategySettings = StrategySettings()
    schedule: ScheduleSettings = ScheduleSettings()
    judge: JudgeSettings = JudgeSettings()

    # Benchmarks
    primary_benchmark: str = "QQQ"
    secondary_benchmark: str = "XLK"


# Singleton
settings = Settings()
