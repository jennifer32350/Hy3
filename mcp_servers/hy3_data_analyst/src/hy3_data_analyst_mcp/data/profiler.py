"""Deterministic, bounded, JSON-safe dataset profiling."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from hy3_data_analyst_mcp.models import ColumnProfile, DatasetProfile, FileInfo, SemanticType

DEFAULT_TOP_VALUES = 10
MAX_SAMPLE_ROWS = 20


def profile_dataset(
    frame: pd.DataFrame,
    *,
    source_path: Path,
    sample_rows: int = 5,
    top_values: int = DEFAULT_TOP_VALUES,
) -> DatasetProfile:
    """Build a bounded overview without retaining the full DataFrame."""
    if not 0 <= sample_rows <= MAX_SAMPLE_ROWS:
        raise ValueError(f"sample_rows must be between 0 and {MAX_SAMPLE_ROWS}")
    if top_values <= 0:
        raise ValueError("top_values must be positive")

    columns = [_profile_column(str(name), frame[name], top_values) for name in frame.columns]
    samples = [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in frame.head(sample_rows).to_dict(orient="records")
    ]
    return DatasetProfile(
        file=FileInfo(
            name=source_path.name,
            format=source_path.suffix.lower().removeprefix("."),
            size_bytes=source_path.stat().st_size,
        ),
        row_count=len(frame),
        column_count=len(frame.columns),
        column_names=[str(name) for name in frame.columns],
        duplicate_row_count=int(frame.duplicated().sum()),
        columns=columns,
        sample_rows=samples,
    )


def _profile_column(name: str, series: pd.Series[Any], top_values: int) -> ColumnProfile:
    semantic_type, values = _semantic_type(series)
    non_null = series.dropna()
    statistics: dict[str, Any]
    if semantic_type == "numeric":
        finite = (
            pd.to_numeric(non_null, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        )
        statistics = _numeric_statistics(finite)
    elif semantic_type == "datetime":
        dates = pd.to_datetime(values.dropna(), errors="coerce").dropna()
        statistics = {
            "min": _json_value(dates.min()) if not dates.empty else None,
            "max": _json_value(dates.max()) if not dates.empty else None,
        }
    elif semantic_type in {"categorical", "boolean", "text"}:
        counts = non_null.value_counts(dropna=True).head(top_values)
        statistics = {
            "top_values": [
                {"value": _json_value(value), "count": int(count)}
                for value, count in counts.items()
            ]
        }
    else:
        statistics = {}

    return ColumnProfile(
        name=name,
        pandas_dtype=str(series.dtype),
        semantic_type=semantic_type,
        non_null_count=int(series.notna().sum()),
        missing_rate=float(series.isna().mean()),
        unique_count=int(non_null.nunique(dropna=True)),
        statistics=statistics,
    )


def _semantic_type(series: pd.Series[Any]) -> tuple[SemanticType, pd.Series[Any]]:
    if ptypes.is_bool_dtype(series.dtype):
        return "boolean", series
    if ptypes.is_numeric_dtype(series.dtype):
        return "numeric", series
    if ptypes.is_datetime64_any_dtype(series.dtype):
        return "datetime", series
    non_null = series.dropna()
    if non_null.empty:
        return "unknown", series
    if ptypes.is_object_dtype(series.dtype) or ptypes.is_string_dtype(series.dtype):
        text = non_null.astype("string")
        date_like = text.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T].*)?$")
        if date_like.all():
            converted = pd.to_datetime(non_null, errors="coerce")
            if converted.notna().all():
                return "datetime", converted
        unique_ratio = non_null.nunique(dropna=True) / len(non_null)
        if non_null.nunique(dropna=True) <= 20 or unique_ratio <= 0.5:
            return "categorical", series
        return "text", series
    return "unknown", series


def _numeric_statistics(series: pd.Series[Any]) -> dict[str, Any]:
    if series.empty:
        return {key: None for key in ("min", "max", "mean", "median", "std", "q1", "q3")}
    return {
        "min": _json_value(series.min()),
        "max": _json_value(series.max()),
        "mean": _json_value(series.mean()),
        "median": _json_value(series.median()),
        "std": _json_value(series.std()),
        "q1": _json_value(series.quantile(0.25)),
        "q3": _json_value(series.quantile(0.75)),
    }


def _json_value(value: Any) -> Any:
    """Convert Pandas/NumPy scalars and non-finite values to strict JSON values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return cast(Any, str(value))
