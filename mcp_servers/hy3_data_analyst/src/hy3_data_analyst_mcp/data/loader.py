"""Deterministic CSV, JSON-array, and JSONL loading."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import (
    DataLimitExceededError,
    DataParseError,
    Hy3DataAnalystError,
    UnsupportedDataFormatError,
)

SUPPORTED_ENCODINGS = frozenset({"utf-8", "utf-8-sig", "gb18030"})


def load_dataset(
    file_path: str | Path,
    *,
    settings: Settings,
    encoding: str = "utf-8",
) -> pd.DataFrame:
    """Load a supported local dataset within all configured safety limits."""
    normalized_encoding = encoding.lower()
    if normalized_encoding not in SUPPORTED_ENCODINGS:
        raise UnsupportedDataFormatError(
            f"Unsupported text encoding: {encoding}.",
            "Use utf-8, utf-8-sig, or explicitly choose gb18030.",
        )

    path = resolve_data_file(
        file_path,
        allowed_directory=settings.data_dir,
        max_file_size_mb=settings.max_file_size_mb,
    )
    try:
        if path.suffix.lower() == ".csv":
            frame = _load_csv(path, normalized_encoding, settings.max_rows)
        elif path.suffix.lower() == ".json":
            frame = _load_json_array(path, normalized_encoding)
        else:
            frame = _load_jsonl(path, normalized_encoding, settings.max_rows)
    except Hy3DataAnalystError:
        raise
    except UnicodeError as exc:
        raise DataParseError(
            f"The data file is not valid {encoding} text.",
            "Choose the correct supported encoding and retry.",
        ) from exc
    except OSError as exc:
        raise DataParseError(
            "The data file could not be read.",
            "Check that the file is readable and not locked, then retry.",
        ) from exc

    _validate_shape(frame, settings.max_rows, settings.max_columns)
    return frame


def _load_csv(path: Path, encoding: str, max_rows: int) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, encoding=encoding, nrows=max_rows + 1)
    except EmptyDataError as exc:
        raise DataParseError(
            "The CSV file is empty or has no columns.",
            "Provide a CSV file with a header row and at least one data row.",
        ) from exc
    except ParserError as exc:
        raise DataParseError(
            "The CSV file is malformed and could not be parsed.",
            "Check its delimiter, quoting, and row structure, then retry.",
        ) from exc
    return frame


def _load_json_array(path: Path, encoding: str) -> pd.DataFrame:
    try:
        payload: Any = json.loads(path.read_text(encoding=encoding))
    except json.JSONDecodeError as exc:
        raise DataParseError(
            f"The JSON file is malformed near line {exc.lineno}, column {exc.colno}.",
            "Fix the JSON syntax and retry with an array of flat objects.",
        ) from exc
    records = _validate_records(payload, format_name="JSON")
    return pd.DataFrame.from_records(records)


def _load_jsonl(path: Path, encoding: str, max_rows: int) -> pd.DataFrame:
    records: list[Mapping[str, Any]] = []
    with path.open("r", encoding=encoding) as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataParseError(
                    f"The JSONL file is malformed at line {line_number}.",
                    "Ensure every non-empty line contains one flat JSON object.",
                ) from exc
            validated = _validate_record(record, format_name="JSONL", line_number=line_number)
            records.append(validated)
            if len(records) > max_rows:
                raise DataLimitExceededError(
                    f"The dataset exceeds the {max_rows} row limit.",
                    "Use a smaller dataset or raise HY3_MAX_ROWS intentionally.",
                )
    if not records:
        raise DataParseError(
            "The JSONL file contains no data records.",
            "Provide at least one line containing a flat JSON object.",
        )
    return pd.DataFrame.from_records(records)


def _validate_records(payload: Any, *, format_name: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list) or not payload:
        raise DataParseError(
            f"The {format_name} file must contain a non-empty array of objects.",
            "Provide a JSON array with at least one flat object.",
        )
    return [
        _validate_record(record, format_name=format_name, line_number=index)
        for index, record in enumerate(payload, start=1)
    ]


def _validate_record(
    record: Any,
    *,
    format_name: str,
    line_number: int,
) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise DataParseError(
            f"The {format_name} record at position {line_number} is not an object.",
            "Use flat JSON objects for every record.",
        )
    if any(isinstance(value, (dict, list)) for value in record.values()):
        raise DataParseError(
            f"The {format_name} record at position {line_number} contains nested data.",
            "Flatten nested objects and arrays before loading this first-version server.",
        )
    return record


def _validate_shape(frame: pd.DataFrame, max_rows: int, max_columns: int) -> None:
    rows, columns = frame.shape
    if rows == 0:
        raise DataParseError(
            "The data file contains columns but no data rows.",
            "Provide at least one data row.",
        )
    if rows > max_rows:
        raise DataLimitExceededError(
            f"The dataset exceeds the {max_rows} row limit.",
            "Use a smaller dataset or raise HY3_MAX_ROWS intentionally.",
        )
    if columns == 0:
        raise DataParseError(
            "The data file contains no columns.",
            "Provide records with at least one field.",
        )
    if columns > max_columns:
        raise DataLimitExceededError(
            f"The dataset exceeds the {max_columns} column limit.",
            "Use fewer columns or raise HY3_MAX_COLUMNS intentionally.",
        )
