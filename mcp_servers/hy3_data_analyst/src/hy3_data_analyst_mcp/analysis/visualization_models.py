"""Strict model-facing schemas for deterministic visualization plans."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hy3_data_analyst_mcp.analysis.workflow_models import (
    Aggregation,
    AnalysisWorkflow,
    QualityPolicy,
)

ChartType: TypeAlias = Literal["bar", "line", "scatter", "histogram", "box"]
ChartSort: TypeAlias = Literal["asc", "desc", "none"]


class ChartSpec(BaseModel):
    """One chart whose data is produced by a constrained local workflow."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    chart_type: ChartType
    title: str = Field(min_length=1, max_length=200)
    x: str | None = Field(default=None, min_length=1, max_length=255)
    y: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = Field(default=None, min_length=1, max_length=255)
    aggregation: Aggregation | None = None
    rationale: str = Field(min_length=1, max_length=1000)
    data_plan: AnalysisWorkflow
    evidence_id: str = Field(default="E01", pattern=r"^E0[1-6]$")
    sort: ChartSort = "none"
    limit: int = Field(default=100, ge=1, le=100)
    notes: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_encodings(self) -> ChartSpec:
        if self.chart_type in {"bar", "line", "scatter"} and (self.x is None or self.y is None):
            raise ValueError(f"{self.chart_type} requires x and y")
        if self.chart_type == "histogram" and self.x is None and self.y is None:
            raise ValueError("histogram requires x or y")
        if self.chart_type == "box" and self.y is None:
            raise ValueError("box requires y; x may optionally group boxes")
        if self.color is not None and self.color in {self.x, self.y}:
            raise ValueError("color must be distinct from x and y")
        return self


class ChartSpecSet(BaseModel):
    """A bounded set of chart specifications selected by Hy3."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    quality_policy: QualityPolicy
    charts: list[ChartSpec] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_quality_policies(self) -> ChartSpecSet:
        if any(chart.data_plan.quality_policy != self.quality_policy for chart in self.charts):
            raise ValueError("every data_plan must copy the requested quality_policy")
        return self
