"""Whitelist-only deterministic Pandas analysis executor."""

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from hy3_data_analyst_mcp.analysis.models import AnalysisEvidence, AnalysisPlan
from hy3_data_analyst_mcp.data.profiler import _json_value
from hy3_data_analyst_mcp.errors import UnsupportedAnalysisOperationError

MAX_RESULT_RECORDS = 100


def execute_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    """Dispatch a validated plan to one of the fixed local operations."""
    handlers: dict[str, Callable[[pd.DataFrame, AnalysisPlan], AnalysisEvidence]] = {
        "describe": _describe,
        "groupby_aggregate": _groupby_aggregate,
        "top_k": _top_k,
        "correlation": _correlation,
        "time_trend": _time_trend,
        "missing_values": _missing_values,
        "outlier_iqr": _outlier_iqr,
    }
    handler = handlers.get(plan.operation)
    if handler is None:
        raise UnsupportedAnalysisOperationError(
            f"Unsupported analysis operation: {plan.operation}.",
            "Ask for a descriptive, grouped, top-k, correlation, trend, "
            "missing-value, or IQR analysis.",
        )
    return handler(frame, plan)


def _describe(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    columns = plan.target_columns or [str(column) for column in frame.columns]
    records: list[dict[str, Any]] = []
    for column in columns:
        series = frame[column]
        record: dict[str, Any] = {
            "column": column,
            "count": int(series.notna().sum()),
            "missing": int(series.isna().sum()),
            "unique": int(series.nunique(dropna=True)),
        }
        if ptypes.is_numeric_dtype(series.dtype):
            numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
            record.update(
                mean=_json_value(numeric.mean()),
                median=_json_value(numeric.median()),
                min=_json_value(numeric.min()),
                max=_json_value(numeric.max()),
                std=_json_value(numeric.std()),
            )
        records.append(record)
    return _evidence(plan, f"Described {len(records)} columns.", records)


def _groupby_aggregate(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    assert plan.aggregation is not None
    numeric_required = plan.aggregation != "count"
    if numeric_required:
        _require_numeric(frame, plan.target_columns)
    grouped = frame.groupby(plan.group_by, dropna=False)[plan.target_columns].agg(plan.aggregation)
    result = grouped.reset_index()
    sort_columns = plan.target_columns
    result = result.sort_values(sort_columns, ascending=plan.sort_order == "asc")
    records, truncated = _records(result, plan.limit)
    return _evidence(
        plan, f"Computed {plan.aggregation} by {', '.join(plan.group_by)}.", records, truncated
    )


def _top_k(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    sort_column = plan.target_columns[0]
    result = frame.sort_values(sort_column, ascending=plan.sort_order == "asc")
    selected = list(dict.fromkeys([*plan.group_by, *plan.target_columns]))
    if not selected:
        selected = [str(column) for column in frame.columns]
    records, truncated = _records(result[selected], plan.limit)
    return _evidence(plan, f"Selected top records ordered by {sort_column}.", records, truncated)


def _correlation(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    _require_numeric(frame, plan.target_columns)
    matrix = frame[plan.target_columns].corr()
    records: list[dict[str, Any]] = []
    for index, left in enumerate(plan.target_columns):
        for right in plan.target_columns[index + 1 :]:
            records.append(
                {
                    "column_a": left,
                    "column_b": right,
                    "correlation": _json_value(matrix.loc[left, right]),
                }
            )
    return _evidence(
        plan,
        "Computed pairwise Pearson correlations.",
        records[: plan.limit],
        len(records) > plan.limit,
    )


def _time_trend(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    assert plan.time_column is not None and plan.aggregation is not None
    if plan.aggregation != "count":
        _require_numeric(frame, plan.target_columns)
    dates = pd.to_datetime(frame[plan.time_column], errors="coerce", format="mixed")
    if dates.notna().sum() == 0:
        raise UnsupportedAnalysisOperationError(
            f"Column {plan.time_column} contains no valid dates.",
            "Choose a date-like time_column and retry.",
        )
    working = frame.loc[dates.notna(), plan.target_columns].copy()
    working.insert(0, plan.time_column, dates[dates.notna()].dt.to_period("M").astype(str))
    result = (
        working.groupby(plan.time_column, dropna=False)[plan.target_columns]
        .agg(plan.aggregation)
        .reset_index()
    )
    result = result.sort_values(plan.time_column, ascending=plan.sort_order == "asc")
    records, truncated = _records(result, plan.limit)
    return _evidence(plan, "Computed monthly time trend.", records, truncated)


def _missing_values(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    columns = plan.target_columns or [str(column) for column in frame.columns]
    records = [
        {
            "column": column,
            "missing_count": int(frame[column].isna().sum()),
            "missing_rate": _json_value(frame[column].isna().mean()),
        }
        for column in columns
    ]
    records.sort(key=lambda item: int(item["missing_count"]), reverse=plan.sort_order == "desc")
    return _evidence(
        plan,
        "Computed missing-value counts and rates.",
        records[: plan.limit],
        len(records) > plan.limit,
    )


def _outlier_iqr(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisEvidence:
    _require_numeric(frame, plan.target_columns)
    records: list[dict[str, Any]] = []
    for column in plan.target_columns:
        series = (
            pd.to_numeric(frame[column], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = series[(series < lower) | (series > upper)]
        records.append(
            {
                "column": column,
                "q1": _json_value(q1),
                "q3": _json_value(q3),
                "lower_bound": _json_value(lower),
                "upper_bound": _json_value(upper),
                "outlier_count": len(outliers),
                "outlier_values": [_json_value(value) for value in outliers.head(10)],
            }
        )
    return _evidence(plan, "Detected outliers using the 1.5xIQR rule.", records)


def _require_numeric(frame: pd.DataFrame, columns: list[str]) -> None:
    invalid = [column for column in columns if not ptypes.is_numeric_dtype(frame[column].dtype)]
    if invalid:
        raise UnsupportedAnalysisOperationError(
            f"Numeric analysis requires numeric columns; invalid: {', '.join(invalid)}.",
            "Choose numeric target_columns and retry.",
        )


def _records(frame: pd.DataFrame, limit: int) -> tuple[list[dict[str, Any]], bool]:
    bounded = min(limit, MAX_RESULT_RECORDS)
    records = [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.head(bounded).to_dict(orient="records")
    ]
    return records, len(frame) > bounded


def _evidence(
    plan: AnalysisPlan,
    summary: str,
    records: list[dict[str, Any]],
    truncated: bool = False,
) -> AnalysisEvidence:
    warnings = ["Result records were truncated to the configured limit."] if truncated else []
    return AnalysisEvidence(
        operation=plan.operation, summary=summary, records=records, warnings=warnings
    )
