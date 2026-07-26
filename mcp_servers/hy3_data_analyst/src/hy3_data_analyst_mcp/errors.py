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
