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
    tiingo_api_key: str = Field(default="")
    fred_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    snaptrade_client_id: str = Field(default="")
    snaptrade_consumer_key: str = Field(default="")


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
    duckdb_path: Path = PROJECT_ROOT / "data" / "trademark.duckdb"
    judge_log_path: Path = PROJECT_ROOT / "logs" / "judge_log.db"


class StrategySettings(BaseSettings):
    # Factor weights (equal weight default)
    factor_weights: dict[str, float] = {
        "momentum_12m1m": 0.15,
        "eps_growth_yoy": 0.15,
        "revenue_growth_yoy": 0.15,
        "gross_margin_trend": 0.10,
        "relative_valuation": 0.20,
        "forward_estimate_revision": 0.25,
    }

    # Position sizing
    max_single_position_weight: float = 0.10
    min_position_size_pct: float = 0.01
    max_cash_pct: float = 0.20
    min_positions: int = 8
    max_positions: int = 25

    # Sub-sector concentration limits. Caps tightened relative to the
    # tech-only era because the universe now spans 11 GICS sectors, so
    # leaning 35% into semis or cloud would defeat the diversification.
    max_subsector_weight: dict[str, float] = {
        # Tech
        "semiconductors": 0.50,
        "cloud_software": 0.50,
        "internet_platforms": 0.50,
        "hardware": 0.50,
        "enterprise_software": 0.50,
        "cybersecurity": 0.50,
        "fintech": 0.50,
        "ai_infrastructure": 0.50,
        # Healthcare
        "pharma": 0.50,
        "biotech": 0.50,
        "healthcare_equipment": 0.50,
        "managed_care": 0.50,
        "healthcare_services": 0.50,
        # Financials
        "banks": 0.50,
        "capital_markets": 0.50,
        "insurance": 0.50,
        "payments": 0.50,
        # Communication services
        "media_entertainment": 0.50,
        "telecom": 0.50,
        # Consumer
        "retail": 0.50,
        "restaurants": 0.50,
        "autos": 0.50,
        "food_beverage": 0.50,
        "household_products": 0.50,
        # Industrials
        "aerospace_defense": 0.50,
        "industrial_machinery": 0.50,
        "transports": 0.50,
        # Energy
        "energy_majors": 0.50,
        "midstream": 0.50,
        "oil_services": 0.50,
        # Utilities / REITs / Materials
        "utilities": 0.50,
        "reits": 0.50,
        "materials": 0.50,
    }

    # Drawdown controls
    max_portfolio_drawdown_alert: float = -0.15
    max_portfolio_drawdown_halt: float = -0.20

    # Turnover controls
    max_turnover_per_week_pct: float = 0.15
    min_holding_days: int = 20
    min_decile_change_to_trade: int = 2
    max_new_positions_per_run: int = 3
    max_trades_per_run: int = 5

    # Winsorization
    winsorize_std: float = 3.0

    # Sector-neutral z-scoring blend.
    #   1.0 = factors are z-scored within each sub-sector (no sector tilts)
    #   0.0 = factors are z-scored across the whole universe (legacy behavior)
    # Anything in between is a linear blend of the two scores. Sub-sectors
    # smaller than sector_neutral_min_group_size always fall back to global
    # because z-scores on n<5 are too noisy to be meaningful.
    sector_neutral_blend: float = 1.0
    sector_neutral_min_group_size: int = 5

    # PER / valuation filtering
    max_absolute_per: float = 40.0
    max_relative_per_vs_peer: float = 1.5

    # Quality gate: minimum quality z-score to be considered a "good stock"
    min_quality_zscore: float = -0.5

    # Recent quarters for quality/growth computation (2-4)
    quality_recent_quarters: int = 4

    # Fundamentals ingestion cooldown (days) — skip re-ingestion if recent
    fundamentals_cooldown_days: int = 14

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


class ChatbotSettings(BaseSettings):
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.3
    max_history: int = 50  # messages per session
    session_ttl_minutes: int = 60


class Settings(BaseSettings):
    api_keys: APIKeys = APIKeys()
    paths: PathSettings = PathSettings()
    strategy: StrategySettings = StrategySettings()
    schedule: ScheduleSettings = ScheduleSettings()
    judge: JudgeSettings = JudgeSettings()
    chatbot: ChatbotSettings = ChatbotSettings()

    # Benchmarks. Primary is broad-market SPY now that the universe spans
    # all GICS sectors; QQQ kept as the tech-tilt secondary for context.
    primary_benchmark: str = "SPY"
    secondary_benchmark: str = "QQQ"


# Singleton
settings = Settings()
