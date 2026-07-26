"""Strict v0.2 structured analysis-report schemas."""

from __future__ import annotations

from collections.abc import Collection
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BoundedText = Annotated[str, Field(min_length=1, max_length=2000)]
EvidenceId = Annotated[str, Field(pattern=r"^E0[1-9]$")]
ColumnName = Annotated[str, Field(min_length=1, max_length=255)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DataScope(_StrictModel):
    """Human-readable row and column scope without exposing an absolute path."""

    source_file_name: str = Field(min_length=1, max_length=255)
    source_rows: int = Field(ge=0)
    used_rows: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    referenced_columns: list[ColumnName] = Field(default_factory=list, max_length=20)
    filters_applied: list[BoundedText] = Field(default_factory=list, max_length=20)
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    notes: list[BoundedText] = Field(default_factory=list, max_length=20)

    @field_validator("source_file_name")
    @classmethod
    def validate_base_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or ":" in value:
            raise ValueError("source_file_name must be a base name without path components")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> DataScope:
        if self.used_rows + self.excluded_rows != self.source_rows:
            raise ValueError("used_rows plus excluded_rows must equal source_rows")
        if len(self.referenced_columns) != len(set(self.referenced_columns)):
            raise ValueError("referenced_columns must be unique")
        return self


class Finding(_StrictModel):
    finding_id: str = Field(pattern=r"^F\d{2}$")
    kind: Literal["fact", "interpretation", "risk"]
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=6)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def validate_grounding_requirement(self) -> Finding:
        if self.kind in {"fact", "risk"} and not self.evidence_ids:
            raise ValueError("fact and risk findings require at least one Evidence ID")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("finding Evidence IDs must be unique")
        return self


class Recommendation(_StrictModel):
    recommendation_id: str = Field(pattern=r"^R\d{2}$")
    statement: str = Field(min_length=1, max_length=2000)
    basis_evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=5)
    priority: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> Recommendation:
        if len(self.basis_evidence_ids) != len(set(self.basis_evidence_ids)):
            raise ValueError("recommendation Evidence IDs must be unique")
        return self


class AnalysisReport(_StrictModel):
    executive_summary: str = Field(min_length=1, max_length=4000)
    findings: list[Finding] = Field(min_length=1, max_length=8)
    anomalies: list[Finding] = Field(default_factory=list, max_length=8)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=8)
    data_scope: DataScope
    limitations: list[BoundedText] = Field(default_factory=list, max_length=20)
    warnings: list[BoundedText] = Field(default_factory=list, max_length=20)
    suggested_follow_ups: list[BoundedText] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_ids(self) -> AnalysisReport:
        finding_ids = [finding.finding_id for finding in [*self.findings, *self.anomalies]]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding IDs must be unique across findings and anomalies")
        recommendation_ids = [item.recommendation_id for item in self.recommendations]
        if len(recommendation_ids) != len(set(recommendation_ids)):
            raise ValueError("recommendation IDs must be unique")
        return self


def validate_report_evidence_references(
    report: AnalysisReport,
    evidence_ids: Collection[str],
) -> None:
    """Reject report references that are absent from the current workflow ledger."""
    known = set(evidence_ids)
    referenced = {
        evidence_id
        for finding in [*report.findings, *report.anomalies]
        for evidence_id in finding.evidence_ids
    }
    referenced.update(
        evidence_id
        for recommendation in report.recommendations
        for evidence_id in recommendation.basis_evidence_ids
    )
    unknown = sorted(referenced - known)
    if unknown:
        raise ValueError(f"report references unknown Evidence IDs: {', '.join(unknown)}")
