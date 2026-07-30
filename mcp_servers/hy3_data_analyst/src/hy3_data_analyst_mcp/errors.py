"""Project exception hierarchy with safe, actionable user messages."""

from typing import Any


class Hy3DataAnalystError(Exception):
    """Base class for errors that may be shown safely to MCP users."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}"

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-serializable error representation."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "hint": self.hint,
        }


class ConfigurationError(Hy3DataAnalystError):
    """The environment configuration is absent or invalid."""


class DataFileNotFoundError(Hy3DataAnalystError):
    """A user-requested data file does not exist."""


class DataAccessDeniedError(Hy3DataAnalystError):
    """A data path is outside the allowed security boundary."""


class UnsupportedDataFormatError(Hy3DataAnalystError):
    """A file format or text encoding is not supported."""


class DataLimitExceededError(Hy3DataAnalystError):
    """A configured file, row, or column limit was exceeded."""


class DataParseError(Hy3DataAnalystError):
    """A supported data file could not be parsed safely."""


class InvalidAnalysisPlanError(Hy3DataAnalystError):
    """Hy3 returned an invalid constrained analysis plan."""


class InvalidAnalysisWorkflowError(Hy3DataAnalystError):
    """A v0.2 workflow failed safe static validation."""

    def __init__(self, message: str, hint: str, *, step_id: str | None = None) -> None:
        super().__init__(message, hint)
        self.step_id = step_id

    def as_dict(self) -> dict[str, Any]:
        payload = super().as_dict()
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        return payload


class WorkflowExecutionError(InvalidAnalysisWorkflowError):
    """A validated workflow failed during deterministic local execution."""

    def __init__(
        self,
        message: str,
        hint: str,
        *,
        step_id: str,
        completed_evidence: list[dict[str, Any]] | None = None,
        completed_step_audits: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message, hint, step_id=step_id)
        self.completed_evidence = completed_evidence or []
        self.completed_step_audits = completed_step_audits or []

    def as_dict(self) -> dict[str, Any]:
        payload = super().as_dict()
        if self.completed_evidence:
            payload["completed_evidence"] = self.completed_evidence
        if self.completed_step_audits:
            payload["completed_step_audits"] = self.completed_step_audits
        return payload


class DataQualityPolicyError(Hy3DataAnalystError):
    """An explicit data-quality policy rejected or exhausted the analysis data."""


class InvalidAnalysisReportError(Hy3DataAnalystError):
    """Hy3 could not produce a fully grounded structured report."""

    def __init__(
        self,
        message: str,
        hint: str,
        *,
        evidence_ledger: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, hint)
        self.evidence_ledger = evidence_ledger

    def as_dict(self) -> dict[str, Any]:
        payload = super().as_dict()
        if self.evidence_ledger is not None:
            payload["evidence_ledger"] = self.evidence_ledger
        return payload


class VisualizationRenderError(Hy3DataAnalystError):
    """A validated chart could not be rendered within deterministic limits."""


class OutputAccessDeniedError(VisualizationRenderError):
    """A chart output path failed the configured filesystem safety boundary."""


class UnsupportedAnalysisOperationError(Hy3DataAnalystError):
    """An analysis plan requested a non-whitelisted operation."""


class Hy3APIError(Hy3DataAnalystError):
    """Base class for safe Hy3 API failures."""


class Hy3AuthenticationError(Hy3APIError):
    """Hy3 rejected the configured credentials."""


class Hy3RateLimitError(Hy3APIError):
    """The Hy3 endpoint rate-limited a request."""


class Hy3TimeoutError(Hy3APIError):
    """A Hy3 request exceeded its configured timeout."""


class Hy3ResponseError(Hy3APIError):
    """A Hy3 response was absent, malformed, or schema-invalid."""
