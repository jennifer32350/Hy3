"""Deterministic, bounded, JSON-safe dataset profiling."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from hy3_data_analyst_mcp.models import (
    ColumnProfile,
    DatasetProfile,
    DatasetQuality,
    FileInfo,
    QualityIssue,
    SemanticHint,
    SemanticType,
)

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
        quality=_assess_quality(frame, columns),
    )


def _profile_column(name: str, series: pd.Series[Any], top_values: int) -> ColumnProfile:
    semantic_type, values = _semantic_type(series)
    semantic_hints = _semantic_hints(name, series, semantic_type)
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
        semantic_hints=semantic_hints,
        statistics=statistics,
    )


def _semantic_hints(
    name: str, series: pd.Series[Any], semantic_type: SemanticType
) -> list[SemanticHint]:
    """Return stable hints without coercing or rewriting source values."""
    hints: list[SemanticHint] = []
    non_null = series.dropna()
    normalized_name = name.casefold()
    unique_count = int(non_null.nunique(dropna=True))
    unique_ratio = unique_count / len(non_null) if len(non_null) else 0.0
    if re.search(r"(?:^|[_\-\s])(id|uuid|key)(?:$|[_\-\s])", normalized_name) or (
        len(non_null) >= 2 and unique_ratio == 1.0 and "id" in normalized_name
    ):
        hints.append("identifier")
    if semantic_type == "datetime" and not ptypes.is_datetime64_any_dtype(series.dtype):
        hints.append("date_string")
    if ptypes.is_object_dtype(series.dtype) or ptypes.is_string_dtype(series.dtype):
        text = non_null.astype("string").str.strip()
        if not text.empty:
            numeric = pd.to_numeric(text.str.replace(",", "", regex=False), errors="coerce")
            if numeric.notna().all():
                hints.append("numeric_string")
            if text.str.match(r"^[+-]?(?:[$¥€£])\s*[\d,]+(?:\.\d+)?$").all():
                hints.append("currency")
            if text.str.match(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*%$").all():
                hints.append("percentage")
    return hints


def _assess_quality(frame: pd.DataFrame, columns: list[ColumnProfile]) -> DatasetQuality:
    """Score transparent risks with fixed local rules; never reject data by score alone."""
    issues: list[QualityIssue] = []
    row_count = len(frame)
    deductions = 0
    duplicate_count = int(frame.duplicated().sum())
    if duplicate_count:
        duplicate_rate = duplicate_count / row_count
        issues.append(
            QualityIssue(
                code="duplicate_rows",
                severity="warning",
                message=f"Found {duplicate_count} duplicate rows.",
                impact="Duplicates can inflate counts and aggregates unless handled explicitly.",
                affected_count=duplicate_count,
                affected_rate=duplicate_rate,
            )
        )
        deductions += min(20, max(5, math.ceil(duplicate_rate * 20)))

    for column in columns:
        series = frame[column.name]
        missing_count = int(series.isna().sum())
        if missing_count:
            if column.missing_rate >= 0.5:
                severity: Literal["info", "warning", "error"] = "error"
                penalty = 15
            elif column.missing_rate >= 0.1:
                severity = "warning"
                penalty = 8
            else:
                severity = "info"
                penalty = 3
            issues.append(
                QualityIssue(
                    code="missing_values",
                    severity=severity,
                    column=column.name,
                    message=f"Column {column.name} has {missing_count} missing values.",
                    impact=(
                        "Missing values can change denominators or exclude rows from calculations."
                    ),
                    affected_count=missing_count,
                    affected_rate=column.missing_rate,
                )
            )
            deductions += penalty

        non_null = series.dropna()
        if len(non_null) and column.unique_count <= 1:
            issues.append(
                QualityIssue(
                    code="constant_column",
                    severity="info",
                    column=column.name,
                    message=f"Column {column.name} is constant among non-null rows.",
                    impact=(
                        "Constant columns do not explain variation and can invalidate correlations."
                    ),
                    affected_count=len(non_null),
                    affected_rate=len(non_null) / row_count,
                )
            )
            deductions += 1

        unique_ratio = column.unique_count / len(non_null) if len(non_null) else 0.0
        if column.semantic_type in {"categorical", "text"} and (
            column.unique_count > 50 or (len(non_null) >= 20 and unique_ratio >= 0.8)
        ):
            issues.append(
                QualityIssue(
                    code="high_cardinality",
                    severity="warning",
                    column=column.name,
                    message=f"Column {column.name} has high cardinality ({column.unique_count}).",
                    impact=(
                        "Grouping or charting this field may create oversized or unreadable output."
                    ),
                    affected_count=column.unique_count,
                    affected_rate=min(1.0, unique_ratio),
                )
            )
            deductions += 5

        if "identifier" in column.semantic_hints:
            issues.append(
                QualityIssue(
                    code="suspected_identifier",
                    severity="info",
                    column=column.name,
                    message=f"Column {column.name} appears to be an identifier.",
                    impact="Identifiers should normally be grouped or counted, not averaged.",
                    affected_count=len(non_null),
                    affected_rate=len(non_null) / row_count,
                )
            )

        conversion_issue = _conversion_risk(column.name, series)
        if conversion_issue is not None:
            issues.append(conversion_issue)
            deductions += 8

        if ptypes.is_numeric_dtype(series.dtype):
            numeric = pd.to_numeric(series, errors="coerce")
            infinity_count = int(np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).sum())
            if infinity_count:
                issues.append(
                    QualityIssue(
                        code="infinite_values",
                        severity="error",
                        column=column.name,
                        message=f"Column {column.name} has {infinity_count} infinite values.",
                        impact="Infinite values are excluded from deterministic numeric analysis.",
                        affected_count=infinity_count,
                        affected_rate=infinity_count / row_count,
                    )
                )
                deductions += 15

    overall: Literal["info", "warning", "error"] = "info"
    if any(issue.severity == "error" for issue in issues):
        overall = "error"
    elif any(issue.severity == "warning" for issue in issues):
        overall = "warning"
    return DatasetQuality(
        score=max(0, 100 - min(100, deductions)),
        severity=overall,
        issues=issues[:100],
        analyzed_rows=row_count,
    )


def _conversion_risk(name: str, series: pd.Series[Any]) -> QualityIssue | None:
    if not (ptypes.is_object_dtype(series.dtype) or ptypes.is_string_dtype(series.dtype)):
        return None
    text = series.dropna().astype("string").str.strip()
    if len(text) < 2:
        return None
    numeric = pd.to_numeric(text.str.replace(",", "", regex=False), errors="coerce")
    numeric_valid = int(numeric.notna().sum())
    date_candidates = text.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T].*)?$")
    date_valid = int(pd.to_datetime(text.where(date_candidates), errors="coerce").notna().sum())
    parsed_count = max(numeric_valid, date_valid)
    invalid_count = len(text) - parsed_count
    if not (0 < parsed_count < len(text)):
        return None
    kind = "numeric" if numeric_valid >= date_valid else "date"
    return QualityIssue(
        code=f"{kind}_conversion_risk",
        severity="warning",
        column=name,
        message=(
            f"Column {name} mixes {parsed_count} {kind}-like values with "
            f"{invalid_count} invalid values."
        ),
        impact=(
            f"Explicit {kind} conversion may coerce invalid values to null or fail in strict mode."
        ),
        affected_count=invalid_count,
        affected_rate=invalid_count / len(text),
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
