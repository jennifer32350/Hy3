"""Shared JSON-serializable models returned by public MCP tools."""

from typing import Any, Literal

from pydantic import BaseModel, Field

SemanticType = Literal["numeric", "categorical", "datetime", "boolean", "text", "unknown"]


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
