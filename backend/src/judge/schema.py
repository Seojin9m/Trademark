"""Pydantic models for LLM judge input/output."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"


class EvaluationContext(BaseModel):
    date: str
    portfolio_value_usd: float
    portfolio_drawdown_from_peak_pct: float
    cash_pct: float


class ProposedTrade(BaseModel):
    ticker: str
    action: str
    current_shares: int = 0
    proposed_shares: int = 0
    current_weight_pct: float = 0.0
    proposed_weight_pct: float = 0.0
    estimated_cost_usd: float = 0.0


class FactorScores(BaseModel):
    momentum_12m1m: float | None = None
    eps_growth_yoy: float | None = None
    revenue_growth_yoy: float | None = None
    gross_margin_trend: float | None = None
    relative_valuation: float | None = None


class SignalContext(BaseModel):
    composite_score: float
    score_decile: int
    prior_decile: int
    factor_scores: FactorScores
    reason: str


class ConstraintCheck(BaseModel):
    passes_all_constraints: bool
    violations: list[str] = Field(default_factory=list)


class JudgeInput(BaseModel):
    evaluation_context: EvaluationContext
    proposed_trade: ProposedTrade
    signal_context: SignalContext
    constraint_check: ConstraintCheck
    strategy_rules_summary: str


class JudgeOutput(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    violated_rules: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    binary_event_warning: bool = False
    data_quality_concerns: list[str] = Field(default_factory=list)
    judge_model: str = ""
    evaluation_timestamp: str = ""
    input_hash: str = ""


class JudgeLogEntry(BaseModel):
    log_id: str
    created_at: str
    proposal_id: str
    ticker: str
    action: str
    input_payload: str  # JSON string
    output_payload: str  # JSON string
    verdict: str
    confidence: float
    model_used: str
    input_hash: str
