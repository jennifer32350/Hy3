"""Immutable environment configuration for the MCP server."""

from collections.abc import Mapping
from os import environ
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hy3_data_analyst_mcp.errors import ConfigurationError

TOKENHUB_BASE_URL = "https://tokenhub.tencentmaas.com/v1"

_FIELD_TO_ENV = {
    "api_key": "HY3_API_KEY",
    "base_url": "HY3_BASE_URL",
    "model_name": "HY3_MODEL",
    "timeout_seconds": "HY3_TIMEOUT_SECONDS",
    "max_retries": "HY3_MAX_RETRIES",
    "reasoning_effort": "HY3_REASONING_EFFORT",
    "data_dir": "HY3_DATA_DIR",
    "max_file_size_mb": "HY3_MAX_FILE_SIZE_MB",
    "max_rows": "HY3_MAX_ROWS",
    "max_columns": "HY3_MAX_COLUMNS",
    "max_workflow_steps": "HY3_MAX_WORKFLOW_STEPS",
    "max_evidence_records_per_step": "HY3_MAX_EVIDENCE_RECORDS_PER_STEP",
    "max_evidence_records_total": "HY3_MAX_EVIDENCE_RECORDS_TOTAL",
    "output_dir": "HY3_OUTPUT_DIR",
    "max_charts": "HY3_MAX_CHARTS",
    "max_chart_file_size_mb": "HY3_MAX_CHART_FILE_SIZE_MB",
}


class Settings(BaseModel):
    """Validated, immutable server settings."""

    model_config = ConfigDict(frozen=True)

    api_key: str | None = None
    base_url: str = TOKENHUB_BASE_URL
    model_name: str = "hy3"
    timeout_seconds: int = Field(default=60, gt=0)
    max_retries: int = Field(default=2, gt=0)
    reasoning_effort: Literal["low", "high"] = "high"
    data_dir: Path
    max_file_size_mb: int = Field(default=20, gt=0)
    max_rows: int = Field(default=100_000, gt=0)
    max_columns: int = Field(default=200, gt=0)
    max_workflow_steps: int = Field(default=6, ge=1, le=6)
    max_evidence_records_per_step: int = Field(default=100, ge=1, le=100)
    max_evidence_records_total: int = Field(default=300, ge=1, le=300)
    output_dir: Path | None = None
    max_charts: int = Field(default=3, ge=1, le=3)
    max_chart_file_size_mb: int = Field(default=5, ge=1, le=5)

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        """Treat an empty API key as absent rather than usable credentials."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Require an absolute HTTP(S) OpenAI-compatible endpoint."""
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        return normalized

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        """Reject an empty model identifier."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("model name must not be empty")
        return normalized

    @field_validator("data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, value: object) -> Path:
        """Resolve the configured data directory to an existing absolute path."""
        if value is None or not str(value).strip():
            raise ValueError("data directory is required")
        try:
            path = Path(str(value)).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("data directory does not exist or cannot be resolved") from exc
        if not path.is_dir():
            raise ValueError("data directory must be a directory")
        return path

    @field_validator("output_dir", mode="before")
    @classmethod
    def resolve_output_dir(cls, value: object) -> Path | None:
        """Resolve an optional pre-existing chart output directory."""
        if value is None or not str(value).strip():
            return None
        supplied = str(value).strip()
        if supplied.startswith(("\\\\", "//")) or "://" in supplied:
            raise ValueError("output directory must be a local filesystem path")
        candidate = Path(supplied).expanduser()
        try:
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
            if candidate.is_symlink() or attributes & 0x400:
                raise ValueError("output directory must not be a link or reparse point")
            path = candidate.resolve(strict=True)
        except ValueError:
            raise
        except (OSError, RuntimeError) as exc:
            raise ValueError("output directory does not exist or cannot be resolved") from exc
        if not path.is_dir():
            raise ValueError("output directory must be a directory")
        return path

    def require_output_dir(self) -> Path:
        """Return the safe chart directory or raise only for rendering calls."""
        if self.output_dir is None:
            raise ConfigurationError(
                "HY3_OUTPUT_DIR is required for render_visualization.",
                "Set HY3_OUTPUT_DIR to an existing writable directory and retry.",
            )
        return self.output_dir

    def require_api_key(self) -> str:
        """Return the API key or raise an actionable error for Hy3-backed tools."""
        if self.api_key is None:
            raise ConfigurationError(
                "HY3_API_KEY is required for this Hy3-backed tool.",
                "Set HY3_API_KEY in the MCP client's server environment and retry.",
            )
        return self.api_key


def load_settings(source: Mapping[str, str] | None = None) -> Settings:
    """Build settings from explicit environment values without loading a .env file."""
    values = environ if source is None else source
    payload = {
        "api_key": values.get("HY3_API_KEY"),
        "base_url": values.get("HY3_BASE_URL", TOKENHUB_BASE_URL),
        "model_name": values.get("HY3_MODEL", "hy3"),
        "timeout_seconds": values.get("HY3_TIMEOUT_SECONDS", "60"),
        "max_retries": values.get("HY3_MAX_RETRIES", "2"),
        "reasoning_effort": values.get("HY3_REASONING_EFFORT", "high"),
        "data_dir": values.get("HY3_DATA_DIR"),
        "max_file_size_mb": values.get("HY3_MAX_FILE_SIZE_MB", "20"),
        "max_rows": values.get("HY3_MAX_ROWS", "100000"),
        "max_columns": values.get("HY3_MAX_COLUMNS", "200"),
        "max_workflow_steps": values.get("HY3_MAX_WORKFLOW_STEPS", "6"),
        "max_evidence_records_per_step": values.get("HY3_MAX_EVIDENCE_RECORDS_PER_STEP", "100"),
        "max_evidence_records_total": values.get("HY3_MAX_EVIDENCE_RECORDS_TOTAL", "300"),
        "output_dir": values.get("HY3_OUTPUT_DIR"),
        "max_charts": values.get("HY3_MAX_CHARTS", "3"),
        "max_chart_file_size_mb": values.get("HY3_MAX_CHART_FILE_SIZE_MB", "5"),
    }
    try:
        return Settings.model_validate(payload)
    except ValidationError as exc:
        invalid = sorted(
            {
                _FIELD_TO_ENV.get(str(error["loc"][0]), str(error["loc"][0]))
                for error in exc.errors()
                if error["loc"]
            }
        )
        fields = ", ".join(invalid) or "environment values"
        raise ConfigurationError(
            f"Invalid Hy3 Data Analyst configuration: {fields}.",
            "Set the listed environment variables to valid values and restart the MCP server.",
        ) from None
