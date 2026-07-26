"""Strict, bounded v0.2 Evidence Ledger schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from hy3_data_analyst_mcp.analysis.workflow_models import EVIDENCE_OPERATIONS, Operation

BoundedText = Annotated[str, Field(min_length=1, max_length=1000)]
ColumnName = Annotated[str, Field(min_length=1, max_length=255)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EvidenceLineage(_StrictModel):
    """Non-sensitive provenance for one deterministic Evidence item."""

    source_file_name: str = Field(min_length=1, max_length=255)
    input_ref: str = Field(pattern=r"^(?:source|S0[1-6])$")
    referenced_columns: list[ColumnName] = Field(default_factory=list, max_length=20)
    quality_actions: list[BoundedText] = Field(default_factory=list, max_length=20)

    @field_validator("source_file_name")
    @classmethod
    def validate_base_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or ":" in value:
            raise ValueError("source_file_name must be a base name without path components")
        return value

    @model_validator(mode="after")
    def validate_columns(self) -> EvidenceLineage:
        if len(self.referenced_columns) != len(set(self.referenced_columns)):
            raise ValueError("referenced_columns must be unique")
        return self


class EvidenceItem(_StrictModel):
    """One bounded deterministic result produced by an Evidence step."""

    evidence_id: str = Field(pattern=r"^E0[1-9]$")
    step_id: str = Field(pattern=r"^S0[1-6]$")
    operation: Operation
    summary: BoundedText
    metrics: dict[str, JsonValue] = Field(default_factory=dict, max_length=100)
    records: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=100)
    source_rows: int = Field(ge=0)
    used_rows: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    truncated: bool
    warnings: list[BoundedText] = Field(default_factory=list, max_length=20)
    lineage: EvidenceLineage

    @model_validator(mode="after")
    def validate_row_accounting(self) -> EvidenceItem:
        if self.operation not in EVIDENCE_OPERATIONS:
            raise ValueError("View operations must not produce Evidence items")
        if self.used_rows + self.excluded_rows != self.source_rows:
            raise ValueError("used_rows plus excluded_rows must equal source_rows")
        _validate_bounded_json(self.metrics)
        _validate_bounded_json(self.records)
        return self


def _validate_bounded_json(value: object, *, depth: int = 0) -> None:
    if depth > 5:
        raise ValueError("Evidence JSON nesting must not exceed five levels")
    if isinstance(value, str) and len(value) > 4000:
        raise ValueError("Evidence string values must not exceed 4000 characters")
    if isinstance(value, (list, dict)):
        if len(value) > 100:
            raise ValueError("Evidence JSON collections must not exceed 100 items")
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            _validate_bounded_json(child, depth=depth + 1)


class EvidenceLedger(_StrictModel):
    """Workflow-level bounded Evidence collection."""

    items: list[EvidenceItem] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_ledger(self) -> EvidenceLedger:
        evidence_ids = [item.evidence_id for item in self.items]
        expected_ids = [f"E{index:02d}" for index in range(1, len(self.items) + 1)]
        if evidence_ids != expected_ids:
            raise ValueError("evidence IDs must be continuous and ordered from E01")
        step_ids = [item.step_id for item in self.items]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("each workflow step may produce at most one Evidence item")
        if sum(len(item.records) for item in self.items) > 300:
            raise ValueError("Evidence Ledger records must not exceed 300")
        return self
