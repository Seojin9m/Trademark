"""Pydantic models for AI news research."""

from pydantic import BaseModel, Field


class BinaryEvent(BaseModel):
    event_type: str  # "earnings" | "regulatory" | "product_launch" | "legal" | "management"
    expected_date: str | None = None
    description: str
    potential_impact: str = "medium"  # "high" | "medium" | "low"


class NewsResearch(BaseModel):
    ticker: str
    research_date: str
    headlines: list[str] = Field(default_factory=list)
    ai_summary: str = ""
    sentiment: str = "neutral"  # "positive" | "negative" | "neutral" | "mixed"
    binary_events: list[BinaryEvent] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0  # 0-1, how much news was found
