"""Filesystem security boundary for local datasets."""

from pathlib import Path

from hy3_data_analyst_mcp.errors import (
    ConfigurationError,
    DataAccessDeniedError,
    DataFileNotFoundError,
    DataLimitExceededError,
    UnsupportedDataFormatError,
)

ALLOWED_EXTENSIONS = frozenset({".csv", ".json", ".jsonl"})


def resolve_allowed_directory(directory: str | Path) -> Path:
    """Resolve and validate the configured filesystem security root."""
    try:
        resolved = Path(directory).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigurationError(
            "The configured HY3_DATA_DIR cannot be resolved.",
            "Set HY3_DATA_DIR to an existing readable directory.",
        ) from exc
    if not resolved.is_dir():
        raise ConfigurationError(
            "The configured HY3_DATA_DIR is not a directory.",
            "Set HY3_DATA_DIR to an existing readable directory.",
        )
    return resolved


def resolve_data_file(
    file_path: str | Path,
    *,
    allowed_directory: str | Path,
    max_file_size_mb: int,
) -> Path:
    """Resolve a regular supported file contained by the configured data root."""
    if max_file_size_mb <= 0:
        raise ConfigurationError(
            "HY3_MAX_FILE_SIZE_MB must be positive.",
            "Set HY3_MAX_FILE_SIZE_MB to a positive integer and restart the server.",
        )

    root = resolve_allowed_directory(allowed_directory)
    supplied = Path(file_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        raise DataFileNotFoundError(
            f"The requested data file was not found: {file_path}.",
            "Check the file name and ensure it exists under HY3_DATA_DIR.",
        ) from None
    except (OSError, RuntimeError) as exc:
        raise DataAccessDeniedError(
            f"The requested data file cannot be resolved safely: {file_path}.",
            "Use a readable CSV, JSON, or JSONL file under HY3_DATA_DIR.",
        ) from exc

    if not resolved.is_relative_to(root):
        raise DataAccessDeniedError(
            f"The requested path is outside HY3_DATA_DIR: {file_path}.",
            "Choose a file contained by the configured data directory.",
        )

    relative_parts = resolved.relative_to(root).parts
    if any(part.startswith(".") for part in relative_parts):
        raise DataAccessDeniedError(
            f"Hidden data files are not allowed: {file_path}.",
            "Choose a visible CSV, JSON, or JSONL file under HY3_DATA_DIR.",
        )

    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsupportedDataFormatError(
            f"Unsupported data file extension: {resolved.suffix or '<none>'}.",
            "Use a .csv, .json, or .jsonl file.",
        )

    if not resolved.is_file():
        raise DataAccessDeniedError(
            f"The requested path is not a regular file: {file_path}.",
            "Choose a regular CSV, JSON, or JSONL file.",
        )

    try:
        size_bytes = resolved.stat().st_size
    except OSError as exc:
        raise DataAccessDeniedError(
            f"The requested data file cannot be inspected: {file_path}.",
            "Check the file permissions and retry.",
        ) from exc
    limit_bytes = max_file_size_mb * 1024 * 1024
    if size_bytes > limit_bytes:
        raise DataLimitExceededError(
            f"The data file exceeds the {max_file_size_mb} MB size limit.",
            "Use a smaller file or raise HY3_MAX_FILE_SIZE_MB intentionally.",
        )
    return resolved
