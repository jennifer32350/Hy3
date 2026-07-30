"""Shared JSON-serializable models returned by public MCP tools."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SemanticType = Literal["numeric", "categorical", "datetime", "boolean", "text", "unknown"]
SemanticHint = Literal[
    "identifier",
    "currency",
    "percentage",
    "numeric_string",
    "date_string",
]
QualitySeverity = Literal["info", "warning", "error"]


class QualityIssue(BaseModel):
    """One deterministic, bounded dataset-quality observation."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    severity: QualitySeverity
    message: str = Field(min_length=1, max_length=500)
    impact: str = Field(min_length=1, max_length=500)
    column: str | None = Field(default=None, max_length=255)
    affected_count: int = Field(ge=0)
    affected_rate: float = Field(ge=0, le=1)


class DatasetQuality(BaseModel):
    """Locally scored quality summary; never a substitute for user judgment."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    severity: QualitySeverity
    issues: list[QualityIssue] = Field(default_factory=list, max_length=100)
    analyzed_rows: int = Field(ge=0)
    source_modified: Literal[False] = False


class FileInfo(BaseModel):
    """Non-sensitive information about the inspected file."""

    name: str = Field(description="Base name of the inspected data file.")
    format: str = Field(description="Lowercase file format without the leading dot.")
    size_bytes: int = Field(ge=0, description="File size in bytes.")


class ColumnProfile(BaseModel):
    """Deterministic quality and summary information for one column."""

    name: str = Field(description="Column name exactly as it appears in the dataset.")
    pandas_dtype: str = Field(description="Pandas dtype used for the loaded column.")
    semantic_type: SemanticType = Field(description="Coarse semantic type inferred locally.")
    non_null_count: int = Field(ge=0, description="Number of non-null values.")
    missing_rate: float = Field(ge=0, le=1, description="Fraction of values that are null.")
    unique_count: int = Field(ge=0, description="Number of distinct non-null values.")
    semantic_hints: list[SemanticHint] = Field(
        default_factory=list,
        description="Deterministic hints such as identifier, percentage, or conversion risk.",
    )
    statistics: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific, JSON-compatible deterministic statistics.",
    )


class DatasetProfile(BaseModel):
    """Bounded dataset overview returned by ``inspect_dataset``."""

    file: FileInfo = Field(description="Information about the inspected file.")
    row_count: int = Field(ge=0, description="Number of loaded data rows.")
    column_count: int = Field(ge=0, description="Number of loaded columns.")
    column_names: list[str] = Field(description="Dataset columns in source order.")
    duplicate_row_count: int = Field(ge=0, description="Number of duplicate rows.")
    columns: list[ColumnProfile] = Field(description="Per-column profiles.")
    sample_rows: list[dict[str, Any]] = Field(
        description="A bounded sample converted to JSON-compatible values."
    )
    quality: DatasetQuality = Field(description="Deterministic, non-mutating quality summary.")
