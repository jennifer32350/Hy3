"""Deterministic Phase D data-quality policy execution and audit summaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from hy3_data_analyst_mcp.analysis.workflow_models import (
    AggregateRatioStep,
    AnalysisStep,
    AnalysisWorkflow,
    ColumnOperand,
    CorrelationStep,
    DerivedMetricStep,
    DescribeStep,
    DistributionStep,
    FilterRowsStep,
    GroupByAggregateStep,
    MissingValuesStep,
    MultiAggregateStep,
    OutlierIQRStep,
    PeriodCompareStep,
    PivotTableStep,
    TimeTrendStep,
    TopKStep,
    ValueCountsStep,
)
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.errors import DataQualityPolicyError


class QualitySummary(BaseModel):
    """Stable, local-only accounting for all Phase D quality actions."""

    model_config = ConfigDict(extra="forbid")

    source_rows: int = Field(ge=0)
    analysis_base_rows: int = Field(ge=0)
    duplicate_rows_found: int = Field(ge=0)
    duplicate_rows_removed: int = Field(ge=0)
    referenced_rows_with_missing: int = Field(ge=0)
    rows_removed_for_missing: int = Field(ge=0)
    numeric_values_coerced_to_null: int = Field(ge=0)
    date_values_coerced_to_null: int = Field(ge=0)
    policies_applied: list[str] = Field(min_length=4, max_length=10)
    source_modified: Literal[False] = False


@dataclass(frozen=True)
class PreparedAnalysisData:
    """An isolated analysis base plus schema and deterministic quality audit."""

    frame: pd.DataFrame
    dataset_schema: DatasetSchema
    summary: QualitySummary
    quality_actions: tuple[str, ...]


def prepare_analysis_data(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    dataset_schema: DatasetSchema,
) -> PreparedAnalysisData:
    """Apply the declared policy to a deep copy and never mutate source data."""
    working = frame.copy(deep=True)
    policy = workflow.quality_policy
    referenced = _workflow_referenced_columns(workflow, dataset_schema.columns)
    numeric_columns, date_columns = _conversion_columns(workflow, dataset_schema)

    duplicate_rows_found = int(working.duplicated().sum())
    duplicate_rows_removed = 0
    if policy.duplicates == "error" and duplicate_rows_found:
        raise DataQualityPolicyError(
            f"The dataset contains {duplicate_rows_found} duplicate rows and duplicates=error.",
            "Choose duplicates=keep or duplicates=drop, or clean the source data explicitly.",
        )
    if policy.duplicates == "drop" and duplicate_rows_found:
        working = working.drop_duplicates(keep="first").copy(deep=True)
        duplicate_rows_removed = duplicate_rows_found

    numeric_coerced = _convert_numeric_columns(
        working,
        numeric_columns,
        strict=policy.numeric_conversion == "strict",
    )
    date_coerced = _convert_date_columns(
        working,
        date_columns,
        strict=policy.date_conversion == "strict",
    )

    rows_removed_for_missing = 0
    rows_with_referenced_missing = (
        working[list(referenced)].isna().any(axis=1)
        if referenced
        else pd.Series(False, index=working.index)
    )
    missing_rows = int(rows_with_referenced_missing.sum())
    if policy.missing == "error" and missing_rows:
        raise DataQualityPolicyError(
            f"The analysis references {missing_rows} rows with missing values and missing=error.",
            "Choose missing=keep or missing=drop_referenced, or clean the source data.",
        )
    if policy.missing == "drop_referenced" and missing_rows:
        working = working.loc[~rows_with_referenced_missing].copy(deep=True)
        rows_removed_for_missing = missing_rows
    if working.empty:
        raise DataQualityPolicyError(
            "The declared quality policy removed all analysis rows.",
            "Relax the missing or duplicate policy and retry.",
        )

    actions = (
        f"duplicates={policy.duplicates} (found={duplicate_rows_found}, "
        f"removed={duplicate_rows_removed})",
        f"numeric_conversion={policy.numeric_conversion} (coerced_to_null={numeric_coerced})",
        f"date_conversion={policy.date_conversion} (coerced_to_null={date_coerced})",
        f"missing={policy.missing} (removed={rows_removed_for_missing})",
    )
    updated_schema = DatasetSchema(
        columns=dataset_schema.columns,
        numeric_columns=dataset_schema.numeric_columns | numeric_columns,
        datetime_columns=dataset_schema.datetime_columns | date_columns,
        cardinalities=dataset_schema.cardinalities,
    )
    summary = QualitySummary(
        source_rows=len(frame),
        analysis_base_rows=len(working),
        duplicate_rows_found=duplicate_rows_found,
        duplicate_rows_removed=duplicate_rows_removed,
        referenced_rows_with_missing=missing_rows,
        rows_removed_for_missing=rows_removed_for_missing,
        numeric_values_coerced_to_null=numeric_coerced,
        date_values_coerced_to_null=date_coerced,
        policies_applied=list(actions),
    )
    return PreparedAnalysisData(working, updated_schema, summary, actions)


def _convert_numeric_columns(
    frame: pd.DataFrame,
    columns: frozenset[str],
    *,
    strict: bool,
) -> int:
    coerced_count = 0
    for column in sorted(columns):
        original = frame[column]
        converted = pd.to_numeric(original, errors="coerce").replace([np.inf, -np.inf], np.nan)
        invalid = original.notna() & converted.isna()
        invalid_count = int(invalid.sum())
        if strict and invalid_count:
            raise DataQualityPolicyError(
                f"Numeric conversion failed for {invalid_count} values in column {column}.",
                "Use numeric_conversion=coerce or correct the invalid source values.",
            )
        frame[column] = converted
        coerced_count += invalid_count
    return coerced_count


def _convert_date_columns(
    frame: pd.DataFrame,
    columns: frozenset[str],
    *,
    strict: bool,
) -> int:
    coerced_count = 0
    for column in sorted(columns):
        original = frame[column]
        converted = pd.to_datetime(original, errors="coerce", format="mixed")
        invalid = original.notna() & converted.isna()
        invalid_count = int(invalid.sum())
        if strict and invalid_count:
            raise DataQualityPolicyError(
                f"Date conversion failed for {invalid_count} values in column {column}.",
                "Use date_conversion=coerce or correct the invalid source values.",
            )
        frame[column] = converted
        coerced_count += invalid_count
    return coerced_count


def _conversion_columns(
    workflow: AnalysisWorkflow,
    dataset_schema: DatasetSchema,
) -> tuple[frozenset[str], frozenset[str]]:
    numeric: set[str] = set()
    dates: set[str] = set()
    for step in workflow.steps:
        if isinstance(step, GroupByAggregateStep) and step.params.aggregation != "count":
            numeric.update(step.params.target_columns)
        elif isinstance(step, MultiAggregateStep):
            numeric.update(
                metric.column for metric in step.params.metrics if metric.aggregation != "count"
            )
        elif isinstance(step, AggregateRatioStep):
            numeric.update(
                metric.column
                for metric in (step.params.numerator, step.params.denominator)
                if metric.aggregation != "count"
            )
        elif isinstance(step, CorrelationStep):
            numeric.update(step.params.target_columns)
        elif isinstance(step, (TimeTrendStep, PeriodCompareStep)):
            dates.add(step.params.time_column)
            if step.params.aggregation != "count":
                numeric.update(step.params.target_columns)
        elif isinstance(step, (DistributionStep, OutlierIQRStep)):
            numeric.update(step.params.target_columns)
        elif isinstance(step, PivotTableStep):
            numeric.update(
                metric.column for metric in step.params.metrics if metric.aggregation != "count"
            )
        elif isinstance(step, DerivedMetricStep):
            numeric.update(
                operand.column
                for operand in (step.params.left, step.params.right)
                if isinstance(operand, ColumnOperand)
            )
        elif isinstance(step, FilterRowsStep):
            for condition in step.params.conditions:
                values = condition.values or [condition.value]
                if condition.column in dataset_schema.datetime_columns or (
                    condition.operator
                    in {"eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "not_in"}
                    and _all_iso_date_literals(values)
                ):
                    dates.add(condition.column)
                elif condition.operator in {
                    "eq",
                    "ne",
                    "gt",
                    "gte",
                    "lt",
                    "lte",
                    "between",
                    "in",
                    "not_in",
                } and any(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in values
                    if value is not None
                ):
                    numeric.add(condition.column)
    source_columns = set(dataset_schema.columns)
    return frozenset(numeric & source_columns), frozenset(dates & source_columns)


def _all_iso_date_literals(values: Iterable[object]) -> bool:
    candidates = [value for value in values if value is not None]
    if not candidates or not all(isinstance(value, str) for value in candidates):
        return False
    try:
        for value in candidates:
            assert isinstance(value, str)
            date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _workflow_referenced_columns(
    workflow: AnalysisWorkflow,
    all_columns: tuple[str, ...],
) -> tuple[str, ...]:
    ordered: dict[str, None] = {}
    for step in workflow.steps:
        for column in _step_referenced_columns(step, all_columns):
            if column in all_columns:
                ordered.setdefault(column, None)
    return tuple(ordered)


def _step_referenced_columns(step: AnalysisStep, all_columns: tuple[str, ...]) -> list[str]:
    if isinstance(step, (DescribeStep, MissingValuesStep)):
        return list(step.params.target_columns or all_columns)
    if isinstance(step, GroupByAggregateStep):
        return [*step.params.group_by, *step.params.target_columns]
    if isinstance(step, MultiAggregateStep):
        return [*step.params.group_by, *(metric.column for metric in step.params.metrics)]
    if isinstance(step, AggregateRatioStep):
        return [
            *step.params.group_by,
            step.params.numerator.column,
            step.params.denominator.column,
        ]
    if isinstance(step, TopKStep):
        return [*step.params.group_by, *step.params.target_columns]
    if isinstance(step, ValueCountsStep):
        return [*step.params.group_by, step.params.column]
    if isinstance(step, CorrelationStep):
        return list(step.params.target_columns)
    if isinstance(step, TimeTrendStep):
        return [step.params.time_column, *step.params.target_columns]
    if isinstance(step, PeriodCompareStep):
        return [step.params.time_column, *step.params.group_by, *step.params.target_columns]
    if isinstance(step, (DistributionStep, OutlierIQRStep)):
        return list(step.params.target_columns)
    if isinstance(step, PivotTableStep):
        return [
            *step.params.rows,
            *step.params.columns,
            *(metric.column for metric in step.params.metrics),
        ]
    if isinstance(step, FilterRowsStep):
        return [condition.column for condition in step.params.conditions]
    if isinstance(step, DerivedMetricStep):
        return [
            operand.column
            for operand in (step.params.left, step.params.right)
            if isinstance(operand, ColumnOperand)
        ]
    return []
