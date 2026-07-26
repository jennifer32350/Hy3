"""Deterministic, whitelist-only execution for v0.2-alpha workflows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, NoReturn, cast

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hy3_data_analyst_mcp.analysis.evidence import (
    EvidenceItem,
    EvidenceLedger,
    EvidenceLineage,
)
from hy3_data_analyst_mcp.analysis.workflow_models import (
    AnalysisStep,
    AnalysisWorkflow,
    CorrelationStep,
    DescribeStep,
    FilterCondition,
    FilterRowsStep,
    GroupByAggregateStep,
    MissingValuesStep,
    MultiAggregateStep,
    OutlierIQRStep,
    PeriodCompareStep,
    TimeTrendStep,
    TopKStep,
    ValueCountsStep,
)
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.data.profiler import _json_value
from hy3_data_analyst_mcp.errors import WorkflowExecutionError

PHASE_C_OPERATIONS = frozenset(
    {
        "describe",
        "groupby_aggregate",
        "multi_aggregate",
        "top_k",
        "value_counts",
        "correlation",
        "time_trend",
        "period_compare",
        "missing_values",
        "outlier_iqr",
        "filter_rows",
    }
)
_PERIOD_FREQUENCIES = {"month": "M", "quarter": "Q", "year": "Y"}


class StepAudit(BaseModel):
    """Bounded row accounting for a View-producing workflow step."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=r"^S0[1-6]$")
    operation: str
    input_ref: str
    input_rows: int = Field(ge=0)
    output_rows: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_rows(self) -> StepAudit:
        if self.output_rows + self.excluded_rows != self.input_rows:
            raise ValueError("output_rows plus excluded_rows must equal input_rows")
        return self


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Serializable execution artifacts; internal DataFrame Views are never exposed."""

    evidence_ledger: EvidenceLedger
    step_audits: tuple[StepAudit, ...]
    step_timings_ms: dict[str, float]


@dataclass(frozen=True)
class _OperationResult:
    summary: str
    records: list[dict[str, Any]]
    metrics: dict[str, Any]
    used_rows: int
    warnings: list[str]
    truncated: bool = False


def execute_workflow(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    *,
    source_file_name: str,
    dataset_schema: DatasetSchema | None = None,
    max_records_per_step: int = 100,
    max_records_total: int = 300,
) -> WorkflowExecutionResult:
    """Execute a validated workflow without mutating the caller's DataFrame."""
    if not 1 <= max_records_per_step <= 100:
        raise ValueError("max_records_per_step must be between 1 and 100")
    if not 1 <= max_records_total <= 300:
        raise ValueError("max_records_total must be between 1 and 300")

    source = frame.copy(deep=True)
    views: dict[str, pd.DataFrame] = {}
    evidence_items: list[EvidenceItem] = []
    audits: list[StepAudit] = []
    timings: dict[str, float] = {}
    serialized_records = 0

    for step in workflow.steps:
        step_started = time.monotonic()
        try:
            if step.operation not in PHASE_C_OPERATIONS:
                _fail(
                    step.step_id,
                    f"Operation {step.operation} is not available in v0.2-alpha Phase C.",
                    "Use one of the Phase C whitelist operations and retry.",
                )
            input_frame = source if step.input_ref == "source" else views[step.input_ref]
            if input_frame.empty:
                _fail(
                    step.step_id,
                    f"Input View {step.input_ref} contains zero rows.",
                    "Relax the preceding filter conditions and retry.",
                )

            if isinstance(step, FilterRowsStep):
                output = _filter_rows(input_frame, step, dataset_schema)
                views[step.step_id] = output
                audits.append(
                    StepAudit(
                        step_id=step.step_id,
                        operation=step.operation,
                        input_ref=step.input_ref,
                        input_rows=len(input_frame),
                        output_rows=len(output),
                        excluded_rows=len(input_frame) - len(output),
                    )
                )
            else:
                operation_result = _execute_evidence_step(input_frame, step)
                remaining = max(0, max_records_total - serialized_records)
                record_limit = min(max_records_per_step, remaining)
                records = operation_result.records[:record_limit]
                truncated = operation_result.truncated or len(operation_result.records) > len(
                    records
                )
                warnings = list(operation_result.warnings)
                if truncated:
                    warnings.append(
                        "Result records were truncated to the configured Evidence limit."
                    )
                item = EvidenceItem(
                    evidence_id=f"E{len(evidence_items) + 1:02d}",
                    step_id=step.step_id,
                    operation=step.operation,
                    summary=operation_result.summary,
                    metrics=_json_mapping(operation_result.metrics),
                    records=[_json_mapping(record) for record in records],
                    source_rows=len(input_frame),
                    used_rows=operation_result.used_rows,
                    excluded_rows=len(input_frame) - operation_result.used_rows,
                    truncated=truncated,
                    warnings=warnings[:20],
                    lineage=EvidenceLineage(
                        source_file_name=source_file_name,
                        input_ref=step.input_ref,
                        referenced_columns=_referenced_columns(step, input_frame),
                        quality_actions=[],
                    ),
                )
                evidence_items.append(item)
                serialized_records += len(records)
        except WorkflowExecutionError as exc:
            raise WorkflowExecutionError(
                exc.message,
                exc.hint,
                step_id=step.step_id,
                completed_evidence=[item.model_dump(mode="json") for item in evidence_items],
                completed_step_audits=[audit.model_dump(mode="json") for audit in audits],
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                f"Deterministic execution failed for operation {step.operation}.",
                "Check the step's columns, value types, and parameters, then retry.",
                step_id=step.step_id,
                completed_evidence=[item.model_dump(mode="json") for item in evidence_items],
                completed_step_audits=[audit.model_dump(mode="json") for audit in audits],
            ) from exc
        finally:
            timings[step.step_id] = round((time.monotonic() - step_started) * 1000, 2)

    return WorkflowExecutionResult(
        evidence_ledger=EvidenceLedger(items=evidence_items),
        step_audits=tuple(audits),
        step_timings_ms=timings,
    )


def _execute_evidence_step(frame: pd.DataFrame, step: AnalysisStep) -> _OperationResult:
    if isinstance(step, DescribeStep):
        return _describe(frame, step)
    if isinstance(step, GroupByAggregateStep):
        return _groupby_aggregate(frame, step)
    if isinstance(step, MultiAggregateStep):
        return _multi_aggregate(frame, step)
    if isinstance(step, TopKStep):
        return _top_k(frame, step)
    if isinstance(step, ValueCountsStep):
        return _value_counts(frame, step)
    if isinstance(step, CorrelationStep):
        return _correlation(frame, step)
    if isinstance(step, TimeTrendStep):
        return _time_trend(frame, step)
    if isinstance(step, PeriodCompareStep):
        return _period_compare(frame, step)
    if isinstance(step, MissingValuesStep):
        return _missing_values(frame, step)
    if isinstance(step, OutlierIQRStep):
        return _outlier_iqr(frame, step)
    _fail(
        step.step_id,
        f"Operation {step.operation} has no Phase C deterministic handler.",
        "Use a supported v0.2-alpha operation.",
    )


def _filter_rows(
    frame: pd.DataFrame,
    step: FilterRowsStep,
    dataset_schema: DatasetSchema | None,
) -> pd.DataFrame:
    masks = [
        _condition_mask(
            frame[condition.column],
            condition,
            is_datetime=(
                dataset_schema is not None and condition.column in dataset_schema.datetime_columns
            ),
        )
        for condition in step.params.conditions
    ]
    combined = masks[0].copy()
    for mask in masks[1:]:
        combined = combined & mask if step.params.combine == "all" else combined | mask
    return frame.loc[combined.fillna(False)].copy(deep=True)


def _condition_mask(
    series: pd.Series[Any], condition: FilterCondition, *, is_datetime: bool
) -> pd.Series[bool]:
    operator = condition.operator
    if operator == "is_null":
        return series.isna()
    if operator == "not_null":
        return series.notna()
    if operator == "contains":
        return series.astype("string").str.contains(
            str(condition.value),
            case=condition.case_sensitive,
            regex=False,
            na=False,
        )

    working: pd.Series[Any] = series
    value: Any = condition.value
    values: list[Any] = list(condition.values)
    valid = series.notna()
    if is_datetime:
        working = pd.to_datetime(series, errors="coerce", format="mixed")
        valid = working.notna()
        value = pd.to_datetime(value, errors="coerce") if value is not None else None
        values = [pd.to_datetime(item, errors="coerce") for item in values]
    elif not condition.case_sensitive and (
        isinstance(value, str) or (values and all(isinstance(item, str) for item in values))
    ):
        working = series.astype("string").str.casefold()
        value = value.casefold() if isinstance(value, str) else value
        values = [item.casefold() if isinstance(item, str) else item for item in values]

    try:
        if operator == "eq":
            mask = working.eq(value)
        elif operator == "ne":
            mask = working.ne(value)
        elif operator == "gt":
            mask = working.gt(value)
        elif operator == "gte":
            mask = working.ge(value)
        elif operator == "lt":
            mask = working.lt(value)
        elif operator == "lte":
            mask = working.le(value)
        elif operator == "in":
            mask = working.isin(values)
        elif operator == "not_in":
            mask = ~working.isin(values)
        elif operator == "between":
            mask = working.between(values[0], values[1], inclusive="both")
        else:
            raise AssertionError(f"Unhandled filter operator: {operator}")
    except (TypeError, ValueError):
        return pd.Series(False, index=series.index, dtype=bool)
    return (valid & mask.fillna(False)).astype(bool)


def _describe(frame: pd.DataFrame, step: DescribeStep) -> _OperationResult:
    columns = step.params.target_columns or [str(column) for column in frame.columns]
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
            numeric = _finite_numeric(series)
            record.update(
                mean=_json_value(numeric.mean()),
                median=_json_value(numeric.median()),
                min=_json_value(numeric.min()),
                max=_json_value(numeric.max()),
                std=_json_value(numeric.std()),
                q1=_json_value(numeric.quantile(0.25)),
                q3=_json_value(numeric.quantile(0.75)),
            )
        records.append(record)
    return _OperationResult(
        summary=f"Described {len(records)} columns.",
        records=records,
        metrics={"column_count": len(records)},
        used_rows=len(frame),
        warnings=[],
    )


def _groupby_aggregate(frame: pd.DataFrame, step: GroupByAggregateStep) -> _OperationResult:
    params = step.params
    if params.aggregation != "count":
        _require_numeric(frame, params.target_columns, step.step_id)
    grouped = frame.groupby(params.group_by, dropna=False, sort=False)[params.target_columns].agg(
        params.aggregation
    )
    result = grouped.reset_index().sort_values(
        params.target_columns, ascending=params.sort_order == "asc", kind="mergesort"
    )
    records, truncated = _bounded_frame_records(result, params.limit)
    usable = frame[params.target_columns].notna().any(axis=1)
    return _OperationResult(
        summary=f"Computed {params.aggregation} by {', '.join(params.group_by)}.",
        records=records,
        metrics={"result_rows": len(result), "aggregation": params.aggregation},
        used_rows=int(usable.sum()),
        warnings=[],
        truncated=truncated,
    )


def _multi_aggregate(frame: pd.DataFrame, step: MultiAggregateStep) -> _OperationResult:
    params = step.params
    for metric in params.metrics:
        if metric.aggregation != "count":
            _require_numeric(frame, [metric.column], step.step_id)
    named = {
        metric.alias: pd.NamedAgg(column=metric.column, aggfunc=metric.aggregation)
        for metric in params.metrics
    }
    result = frame.groupby(params.group_by, dropna=False, sort=False).agg(**named).reset_index()
    if params.sort_by is not None:
        result = result.sort_values(
            params.sort_by, ascending=params.sort_order == "asc", kind="mergesort"
        )
    records, truncated = _bounded_frame_records(result, params.limit)
    metric_columns = list(dict.fromkeys(metric.column for metric in params.metrics))
    usable = frame[metric_columns].notna().any(axis=1)
    return _OperationResult(
        summary=f"Computed {len(params.metrics)} metrics by {', '.join(params.group_by)}.",
        records=records,
        metrics={
            "result_rows": len(result),
            "metric_definitions": [
                {
                    "column": metric.column,
                    "aggregation": metric.aggregation,
                    "alias": metric.alias,
                }
                for metric in params.metrics
            ],
        },
        used_rows=int(usable.sum()),
        warnings=[],
        truncated=truncated,
    )


def _top_k(frame: pd.DataFrame, step: TopKStep) -> _OperationResult:
    params = step.params
    sort_column = params.target_columns[0]
    result = frame.sort_values(
        sort_column, ascending=params.sort_order == "asc", kind="mergesort", na_position="last"
    )
    selected = list(dict.fromkeys([*params.group_by, *params.target_columns]))
    records, truncated = _bounded_frame_records(result[selected], params.limit)
    return _OperationResult(
        summary=f"Selected records ordered by {sort_column}.",
        records=records,
        metrics={"available_rows": len(result), "sort_column": sort_column},
        used_rows=len(frame),
        warnings=[],
        truncated=truncated,
    )


def _value_counts(frame: pd.DataFrame, step: ValueCountsStep) -> _OperationResult:
    params = step.params
    working = frame if params.include_null else frame.loc[frame[params.column].notna()]
    keys = [*params.group_by, params.column]
    result = working.groupby(keys, dropna=False, sort=False).size().rename("count").reset_index()
    if params.normalize:
        if params.group_by:
            denominators = result.groupby(params.group_by, dropna=False)["count"].transform("sum")
        else:
            denominators = pd.Series(len(working), index=result.index)
        result["share"] = result["count"] / denominators
    result = result.sort_values("count", ascending=params.sort_order == "asc", kind="mergesort")
    records, truncated = _bounded_frame_records(result, params.limit)
    denominator = "within each group" if params.group_by else "across all included rows"
    return _OperationResult(
        summary=f"Computed counts for {params.column}; shares use a denominator {denominator}.",
        records=records,
        metrics={"result_rows": len(result), "denominator": denominator},
        used_rows=len(working),
        warnings=[],
        truncated=truncated,
    )


def _correlation(frame: pd.DataFrame, step: CorrelationStep) -> _OperationResult:
    columns = step.params.target_columns
    _require_numeric(frame, columns, step.step_id)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, left in enumerate(columns):
        for right in columns[index + 1 :]:
            pair = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
            value: Any = None
            if len(pair) < 3:
                warnings.append(f"Correlation for {left} and {right} has fewer than 3 samples.")
            elif pair[left].nunique() <= 1 or pair[right].nunique() <= 1:
                warnings.append(f"Correlation for {left} and {right} has a zero-variance column.")
            else:
                value = _json_value(pair[left].corr(pair[right]))
            records.append(
                {
                    "column_a": left,
                    "column_b": right,
                    "sample_count": len(pair),
                    "correlation": value,
                }
            )
    bounded = records[: step.params.limit]
    complete = frame[columns].replace([np.inf, -np.inf], np.nan).dropna()
    return _OperationResult(
        summary="Computed pairwise Pearson correlations.",
        records=bounded,
        metrics={"pair_count": len(records)},
        used_rows=len(complete),
        warnings=warnings,
        truncated=len(records) > len(bounded),
    )


def _time_trend(frame: pd.DataFrame, step: TimeTrendStep) -> _OperationResult:
    params = step.params
    if params.aggregation != "count":
        _require_numeric(frame, params.target_columns, step.step_id)
    dates = pd.to_datetime(frame[params.time_column], errors="coerce", format="mixed")
    if not dates.notna().any():
        _fail(
            step.step_id,
            f"Column {params.time_column} contains no valid dates.",
            "Choose a date-like time_column and retry.",
        )
    working = frame.loc[dates.notna(), params.target_columns].copy()
    period_values = _period_labels(dates.loc[dates.notna()], params.grain)
    working.insert(0, params.time_column, period_values)
    result = (
        working.groupby(params.time_column, dropna=False, sort=False)[params.target_columns]
        .agg(params.aggregation)
        .reset_index()
        .sort_values(params.time_column, ascending=params.sort_order == "asc", kind="mergesort")
    )
    records, truncated = _bounded_frame_records(result, params.limit)
    invalid_dates = int(dates.isna().sum())
    warnings = [f"Excluded {invalid_dates} rows with invalid dates."] if invalid_dates else []
    return _OperationResult(
        summary=f"Computed {params.grain} time trend.",
        records=records,
        metrics={"result_rows": len(result), "grain": params.grain},
        used_rows=int(dates.notna().sum()),
        warnings=warnings,
        truncated=truncated,
    )


def _period_compare(frame: pd.DataFrame, step: PeriodCompareStep) -> _OperationResult:
    params = step.params
    if params.aggregation != "count":
        _require_numeric(frame, params.target_columns, step.step_id)
    dates = pd.to_datetime(frame[params.time_column], errors="coerce", format="mixed")
    valid_dates = dates.dropna()
    if valid_dates.empty:
        _fail(
            step.step_id,
            f"Column {params.time_column} contains no valid dates.",
            "Choose a date-like time_column and retry.",
        )
    warnings: list[str] = []
    a_start, a_end, b_start, b_end = _comparison_ranges(step, valid_dates.max())
    if params.comparison != "explicit" and valid_dates.max().normalize() < b_end.normalize():
        warnings.append("The current comparison period is incomplete.")
    mask_a = dates.between(a_start, a_end, inclusive="both")
    mask_b = dates.between(b_start, b_end, inclusive="both")
    if not mask_a.any() or not mask_b.any():
        _fail(
            step.step_id,
            "One or both comparison periods contain no data.",
            "Choose two populated periods or an earlier comparison anchor.",
        )

    values_a = _aggregate_period(
        frame.loc[mask_a], params.group_by, params.target_columns, params.aggregation
    )
    values_b = _aggregate_period(
        frame.loc[mask_b], params.group_by, params.target_columns, params.aggregation
    )
    group_keys = sorted(set(values_a) | set(values_b), key=repr)
    records: list[dict[str, Any]] = []
    zero_bases = 0
    for key in group_keys:
        left = values_a.get(key)
        right = values_b.get(key)
        absolute_change = None if left is None or right is None else right - left
        if left is None or right is None:
            change_rate = None
        elif left == 0:
            change_rate = None
            zero_bases += 1
        else:
            change_rate = (right - left) / left
        group_values, target = key[:-1], key[-1]
        record = {
            column: value for column, value in zip(params.group_by, group_values, strict=True)
        }
        record.update(
            target_column=target,
            period_a_value=_json_value(left),
            period_b_value=_json_value(right),
            absolute_change=_json_value(absolute_change),
            change_rate=_json_value(change_rate),
        )
        records.append(record)
    if zero_bases:
        warnings.append(
            f"Change rate is null for {zero_bases} result(s) because the base period is zero."
        )
    invalid_dates = int(dates.isna().sum())
    if invalid_dates:
        warnings.append(f"Excluded {invalid_dates} rows with invalid dates.")
    used_mask = mask_a | mask_b
    return _OperationResult(
        summary=(
            f"Compared {params.grain} periods {a_start.date()}..{a_end.date()} and "
            f"{b_start.date()}..{b_end.date()}."
        ),
        records=records,
        metrics={
            "period_a": {"start": str(a_start.date()), "end": str(a_end.date())},
            "period_b": {"start": str(b_start.date()), "end": str(b_end.date())},
            "comparison": params.comparison,
            "grain": params.grain,
        },
        used_rows=int(used_mask.sum()),
        warnings=warnings,
    )


def _comparison_ranges(
    step: PeriodCompareStep, anchor: pd.Timestamp
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    params = step.params
    if params.comparison == "explicit":
        assert params.period_a is not None and params.period_b is not None
        return (
            pd.Timestamp(params.period_a.start),
            pd.Timestamp(params.period_a.end) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1),
            pd.Timestamp(params.period_b.start),
            pd.Timestamp(params.period_b.end) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1),
        )
    frequency = _PERIOD_FREQUENCIES[params.grain]
    current = anchor.to_period(frequency)
    if params.comparison == "previous_period":
        previous = current - 1
    else:
        offsets = {"month": 12, "quarter": 4, "year": 1}
        previous = current - offsets[params.grain]
    return previous.start_time, previous.end_time, current.start_time, current.end_time


def _aggregate_period(
    frame: pd.DataFrame,
    group_by: list[str],
    target_columns: list[str],
    aggregation: str,
) -> dict[tuple[Any, ...], float | int | None]:
    result: dict[tuple[Any, ...], float | int | None] = {}
    if group_by:
        grouped = frame.groupby(group_by, dropna=False, sort=False)
        for raw_key, group in grouped:
            group_key = raw_key if isinstance(raw_key, tuple) else (raw_key,)
            safe_key = tuple(_json_value(value) for value in group_key)
            for target in target_columns:
                result[(*safe_key, target)] = _aggregate_series(group[target], aggregation)
    else:
        for target in target_columns:
            result[(target,)] = _aggregate_series(frame[target], aggregation)
    return result


def _aggregate_series(series: pd.Series[Any], aggregation: str) -> float | int | None:
    if aggregation == "count":
        return int(series.count())
    numeric = _finite_numeric(series)
    if numeric.empty:
        return None
    value = getattr(numeric, aggregation)()
    safe = _json_value(value)
    return safe if isinstance(safe, (int, float)) else None


def _missing_values(frame: pd.DataFrame, step: MissingValuesStep) -> _OperationResult:
    columns = step.params.target_columns or [str(column) for column in frame.columns]
    records = []
    for column in columns:
        count = int(frame[column].isna().sum())
        rate = float(frame[column].isna().mean())
        records.append(
            {
                "column": column,
                "missing_count": count,
                "missing_rate": _json_value(rate),
                "severity": "warning" if count else "info",
            }
        )
    records.sort(
        key=lambda item: int(item["missing_count"]),
        reverse=step.params.sort_order == "desc",
    )
    bounded = records[: step.params.limit]
    return _OperationResult(
        summary="Computed missing-value counts and rates.",
        records=bounded,
        metrics={"columns_with_missing": sum(int(item["missing_count"]) > 0 for item in records)},
        used_rows=len(frame),
        warnings=[],
        truncated=len(records) > len(bounded),
    )


def _outlier_iqr(frame: pd.DataFrame, step: OutlierIQRStep) -> _OperationResult:
    columns = step.params.target_columns
    _require_numeric(frame, columns, step.step_id)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    usable = pd.Series(False, index=frame.index)
    for column in columns:
        numeric = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        usable |= numeric.notna()
        finite = numeric.dropna()
        q1, q3 = finite.quantile(0.25), finite.quantile(0.75)
        iqr = q3 - q1
        if not finite.empty and iqr == 0:
            warnings.append(f"Column {column} has IQR=0; no values are flagged by strict bounds.")
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = finite[(finite < lower) | (finite > upper)]
        row_numbers = [_source_row_number(index) for index in outliers.index[: step.params.limit]]
        records.append(
            {
                "column": column,
                "q1": _json_value(q1),
                "q3": _json_value(q3),
                "lower_bound": _json_value(lower),
                "upper_bound": _json_value(upper),
                "outlier_count": len(outliers),
                "source_row_numbers": row_numbers,
            }
        )
    return _OperationResult(
        summary="Detected outliers using the 1.5xIQR rule.",
        records=records,
        metrics={"columns_analyzed": len(columns)},
        used_rows=int(usable.sum()),
        warnings=warnings,
    )


def _period_labels(dates: pd.Series[Any], grain: str) -> pd.Series[Any]:
    if grain == "day":
        return cast("pd.Series[Any]", dates.dt.strftime("%Y-%m-%d"))
    if grain == "week":
        return cast("pd.Series[Any]", dates.dt.to_period("W").astype(str))
    return cast("pd.Series[Any]", dates.dt.to_period(_PERIOD_FREQUENCIES[grain]).astype(str))


def _require_numeric(frame: pd.DataFrame, columns: list[str], step_id: str) -> None:
    invalid = [column for column in columns if not ptypes.is_numeric_dtype(frame[column].dtype)]
    if invalid:
        _fail(
            step_id,
            f"Numeric analysis requires numeric columns: {', '.join(invalid)}.",
            "Choose numeric columns or defer explicit conversion to the quality-policy phase.",
        )


def _finite_numeric(series: pd.Series[Any]) -> pd.Series[Any]:
    result = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return result


def _bounded_frame_records(frame: pd.DataFrame, limit: int) -> tuple[list[dict[str, Any]], bool]:
    records = [
        _json_mapping({str(key): value for key, value in record.items()})
        for record in frame.head(limit).to_dict(orient="records")
    ]
    return records, len(frame) > limit


def _json_mapping(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_nested(value) for key, value in values.items()}


def _json_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_nested(item) for item in value]
    return _json_value(value)


def _source_row_number(index: Any) -> Any:
    if isinstance(index, (int, np.integer)):
        return int(index) + 1
    return _json_value(index)


def _referenced_columns(step: AnalysisStep, frame: pd.DataFrame) -> list[str]:
    if isinstance(step, (DescribeStep, MissingValuesStep)):
        return list(step.params.target_columns or [str(column) for column in frame.columns])
    if isinstance(step, GroupByAggregateStep):
        return list(dict.fromkeys([*step.params.group_by, *step.params.target_columns]))
    if isinstance(step, MultiAggregateStep):
        return list(
            dict.fromkeys(
                [*step.params.group_by, *(metric.column for metric in step.params.metrics)]
            )
        )
    if isinstance(step, TopKStep):
        return list(dict.fromkeys([*step.params.group_by, *step.params.target_columns]))
    if isinstance(step, ValueCountsStep):
        return list(dict.fromkeys([*step.params.group_by, step.params.column]))
    if isinstance(step, CorrelationStep):
        return list(step.params.target_columns)
    if isinstance(step, TimeTrendStep):
        return [step.params.time_column, *step.params.target_columns]
    if isinstance(step, PeriodCompareStep):
        return list(
            dict.fromkeys(
                [step.params.time_column, *step.params.group_by, *step.params.target_columns]
            )
        )
    if isinstance(step, OutlierIQRStep):
        return list(step.params.target_columns)
    if isinstance(step, FilterRowsStep):
        return list(dict.fromkeys(condition.column for condition in step.params.conditions))
    return []


def _fail(step_id: str, message: str, hint: str) -> NoReturn:
    raise WorkflowExecutionError(message, hint, step_id=step_id)
