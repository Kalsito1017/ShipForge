"""AI incident assistant schemas (PLAN.md §26)."""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

Category = Literal[
    "DEPENDENCY",
    "ARTIFACT",
    "VALIDATION",
    "BUILD",
    "SCAN",
    "TIMEOUT",
    "INFRASTRUCTURE",
    "CONFIGURATION",
    "UNKNOWN",
]


class IncidentAnalysis(BaseModel):
    """Structured LLM output, validated with Pydantic before use.

    Advisory only: recommendations are suggestions for a human operator and
    must never be executed automatically.
    """

    category: Category
    root_cause: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    recommendations: list[str] = Field(min_length=1, max_length=10)


class AnalyzeResponse(BaseModel):
    """API response for POST /api/v1/shipments/{id}/analyze."""

    shipment_id: str
    analysis: IncidentAnalysis
    source: Literal["llm", "mock"] = Field(
        description="Which analyzer produced this: a real LLM or the offline mock."
    )
    advisory: bool = Field(
        default=True,
        description="Always true: the AI is advisory only and takes no action.",
    )
