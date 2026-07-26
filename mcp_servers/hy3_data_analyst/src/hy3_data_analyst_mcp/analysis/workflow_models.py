"""Strict v0.2 workflow and operation-parameter schemas."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

Aggregation: TypeAlias = Literal["sum", "mean", "count", "min", "max", "median"]
SortOrder: TypeAlias = Literal["asc", "desc"]
TimeGrain: TypeAlias = Literal["day", "week", "month", "quarter", "year"]
Operation: TypeAlias = Literal[
    "describe",
    "groupby_aggregate",
    "multi_aggregate",
    "top_k",
    "value_counts",
    "correlation",
    "time_trend",
    "period_compare",
    "missing_values",
    "distribution",
    "outlier_iqr",
    "pivot_table",
    "filter_rows",
    "derived_metric",
]
JsonScalar: TypeAlias = str | int | float | bool | None

ColumnName: TypeAlias = Annotated[str, Field(min_length=1, max_length=255)]
OutputAlias: TypeAlias = Annotated[
    str,
    Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"),
]

VIEW_OPERATIONS = frozenset({"filter_rows", "derived_metric"})
EVIDENCE_OPERATIONS = frozenset(
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
        "distribution",
        "outlier_iqr",
        "pivot_table",
    }
)


class StrictSchemaModel(BaseModel):
    """Base for model-facing schemas that reject undeclared fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicate columns")


class QualityPolicy(StrictSchemaModel):
    """Declared Phase D data-quality behavior executed on an isolated in-memory copy."""

    missing: Literal["keep", "drop_referenced", "error"] = "keep"
    duplicates: Literal["keep", "drop", "error"] = "keep"
    numeric_conversion: Literal["strict", "coerce"] = "strict"
    date_conversion: Literal["strict", "coerce"] = "coerce"


class DescribeParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_columns(self) -> DescribeParams:
        _require_unique(self.target_columns, "target_columns")
        return self


class GroupByAggregateParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(min_length=1, max_length=20)
    group_by: list[ColumnName] = Field(min_length=1, max_length=5)
    aggregation: Aggregation
    sort_order: SortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> GroupByAggregateParams:
        _require_unique(self.target_columns, "target_columns")
        _require_unique(self.group_by, "group_by")
        if set(self.target_columns) & set(self.group_by):
            raise ValueError("target_columns and group_by must not overlap")
        return self


class TopKParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(min_length=1, max_length=20)
    group_by: list[ColumnName] = Field(default_factory=list, max_length=5)
    sort_order: SortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> TopKParams:
        _require_unique(self.target_columns, "target_columns")
        _require_unique(self.group_by, "group_by")
        return self


class CorrelationParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(min_length=2, max_length=20)
    method: Literal["pearson"] = "pearson"
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> CorrelationParams:
        _require_unique(self.target_columns, "target_columns")
        return self


class TimeTrendParams(StrictSchemaModel):
    time_column: ColumnName
    target_columns: list[ColumnName] = Field(min_length=1, max_length=20)
    aggregation: Aggregation
    grain: TimeGrain = "month"
    sort_order: SortOrder = "asc"
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> TimeTrendParams:
        _require_unique(self.target_columns, "target_columns")
        if self.time_column in self.target_columns:
            raise ValueError("time_column must not also be a target column")
        return self


class MissingValuesParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(default_factory=list, max_length=20)
    sort_order: SortOrder = "desc"
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> MissingValuesParams:
        _require_unique(self.target_columns, "target_columns")
        return self


class OutlierIQRParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(min_length=1, max_length=20)
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> OutlierIQRParams:
        _require_unique(self.target_columns, "target_columns")
        return self


FilterOperator: TypeAlias = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "between",
    "is_null",
    "not_null",
]


class FilterCondition(StrictSchemaModel):
    column: ColumnName
    operator: FilterOperator
    value: JsonScalar = None
    values: list[JsonScalar] = Field(default_factory=list, max_length=100)
    case_sensitive: bool = False

    @model_validator(mode="after")
    def validate_operator_arguments(self) -> FilterCondition:
        scalar_operators = {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}
        collection_operators = {"in", "not_in", "between"}
        if self.operator in scalar_operators:
            if self.value is None or self.values:
                raise ValueError(f"{self.operator} requires value and forbids values")
            if self.operator == "contains" and not isinstance(self.value, str):
                raise ValueError("contains requires a string value")
        elif self.operator in collection_operators:
            if self.value is not None:
                raise ValueError(f"{self.operator} forbids value")
            expected_length = 2 if self.operator == "between" else None
            if not self.values or (
                expected_length is not None and len(self.values) != expected_length
            ):
                raise ValueError(
                    "between requires exactly two values"
                    if self.operator == "between"
                    else f"{self.operator} requires one or more values"
                )
            if any(value is None for value in self.values):
                raise ValueError(f"{self.operator} values must not contain null")
            if self.operator == "between" and not _same_scalar_type(*self.values):
                raise ValueError("between boundaries must have the same scalar type")
        elif self.value is not None or self.values:
            raise ValueError(f"{self.operator} forbids value and values")
        return self


def _same_scalar_type(left: JsonScalar, right: JsonScalar) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return True
    return type(left) is type(right)


class FilterRowsParams(StrictSchemaModel):
    combine: Literal["all", "any"] = "all"
    conditions: list[FilterCondition] = Field(min_length=1, max_length=10)


class AggregateMetric(StrictSchemaModel):
    column: ColumnName
    aggregation: Aggregation
    alias: OutputAlias


class MultiAggregateParams(StrictSchemaModel):
    group_by: list[ColumnName] = Field(min_length=1, max_length=5)
    metrics: list[AggregateMetric] = Field(min_length=1, max_length=20)
    sort_by: ColumnName | None = None
    sort_order: SortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_outputs(self) -> MultiAggregateParams:
        _require_unique(self.group_by, "group_by")
        aliases = [metric.alias for metric in self.metrics]
        _require_unique(aliases, "metric aliases")
        if set(aliases) & set(self.group_by):
            raise ValueError("metric aliases must not conflict with group_by columns")
        if self.sort_by is not None and self.sort_by not in {*self.group_by, *aliases}:
            raise ValueError("sort_by must name a group_by column or metric alias")
        return self


class ValueCountsParams(StrictSchemaModel):
    column: ColumnName
    group_by: list[ColumnName] = Field(default_factory=list, max_length=3)
    normalize: bool = False
    include_null: bool = False
    sort_order: SortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_columns(self) -> ValueCountsParams:
        _require_unique(self.group_by, "group_by")
        if self.column in self.group_by:
            raise ValueError("column must not also appear in group_by")
        return self


class DateRange(StrictSchemaModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> DateRange:
        if self.start > self.end:
            raise ValueError("date range start must not be after end")
        return self


class PeriodCompareParams(StrictSchemaModel):
    time_column: ColumnName
    target_columns: list[ColumnName] = Field(min_length=1, max_length=10)
    aggregation: Aggregation
    grain: Literal["month", "quarter", "year"]
    comparison: Literal["previous_period", "year_over_year", "explicit"]
    group_by: list[ColumnName] = Field(default_factory=list, max_length=3)
    period_a: DateRange | None = None
    period_b: DateRange | None = None

    @model_validator(mode="after")
    def validate_periods(self) -> PeriodCompareParams:
        _require_unique(self.target_columns, "target_columns")
        _require_unique(self.group_by, "group_by")
        if set(self.target_columns) & set(self.group_by):
            raise ValueError("target_columns and group_by must not overlap")
        if self.time_column in {*self.target_columns, *self.group_by}:
            raise ValueError("time_column must not overlap target_columns or group_by")
        has_explicit_ranges = self.period_a is not None and self.period_b is not None
        if self.comparison == "explicit" and not has_explicit_ranges:
            raise ValueError("explicit comparison requires period_a and period_b")
        if self.comparison != "explicit" and (
            self.period_a is not None or self.period_b is not None
        ):
            raise ValueError("non-explicit comparison forbids period_a and period_b")
        return self


Quantile: TypeAlias = Annotated[float, Field(ge=0, le=1)]


class DistributionParams(StrictSchemaModel):
    target_columns: list[ColumnName] = Field(min_length=1, max_length=10)
    quantiles: list[Quantile] = Field(
        default_factory=lambda: [0.25, 0.5, 0.75], min_length=1, max_length=9
    )
    bins: int = Field(default=10, ge=5, le=50)

    @model_validator(mode="after")
    def validate_distribution(self) -> DistributionParams:
        _require_unique(self.target_columns, "target_columns")
        if any(
            left >= right for left, right in zip(self.quantiles, self.quantiles[1:], strict=False)
        ):
            raise ValueError("quantiles must be strictly increasing")
        return self


class PivotTableParams(StrictSchemaModel):
    rows: list[ColumnName] = Field(min_length=1, max_length=3)
    columns: list[ColumnName] = Field(min_length=1, max_length=2)
    metrics: list[AggregateMetric] = Field(min_length=1, max_length=10)
    fill_value: float | None = None

    @model_validator(mode="after")
    def validate_outputs(self) -> PivotTableParams:
        _require_unique(self.rows, "rows")
        _require_unique(self.columns, "columns")
        if set(self.rows) & set(self.columns):
            raise ValueError("rows and columns must not overlap")
        aliases = [metric.alias for metric in self.metrics]
        _require_unique(aliases, "metric aliases")
        if set(aliases) & {*self.rows, *self.columns}:
            raise ValueError("metric aliases must not conflict with pivot dimensions")
        return self


class ColumnOperand(StrictSchemaModel):
    kind: Literal["column"]
    column: ColumnName


class ConstantOperand(StrictSchemaModel):
    kind: Literal["constant"]
    value: float


Operand: TypeAlias = Annotated[ColumnOperand | ConstantOperand, Field(discriminator="kind")]


class DerivedMetricParams(StrictSchemaModel):
    output_column: OutputAlias
    operator: Literal["add", "subtract", "multiply", "divide"]
    left: Operand
    right: Operand

    @model_validator(mode="after")
    def validate_operands(self) -> DerivedMetricParams:
        if isinstance(self.left, ConstantOperand) and isinstance(self.right, ConstantOperand):
            raise ValueError("derived metric operands must not both be constants")
        return self


class _BaseStep(StrictSchemaModel):
    step_id: str = Field(pattern=r"^S0[1-6]$")
    input_ref: str = Field(pattern=r"^(?:source|S0[1-6])$")
    purpose: str = Field(min_length=1, max_length=1000)


class DescribeStep(_BaseStep):
    operation: Literal["describe"]
    params: DescribeParams


class GroupByAggregateStep(_BaseStep):
    operation: Literal["groupby_aggregate"]
    params: GroupByAggregateParams


class MultiAggregateStep(_BaseStep):
    operation: Literal["multi_aggregate"]
    params: MultiAggregateParams


class TopKStep(_BaseStep):
    operation: Literal["top_k"]
    params: TopKParams


class ValueCountsStep(_BaseStep):
    operation: Literal["value_counts"]
    params: ValueCountsParams


class CorrelationStep(_BaseStep):
    operation: Literal["correlation"]
    params: CorrelationParams


class TimeTrendStep(_BaseStep):
    operation: Literal["time_trend"]
    params: TimeTrendParams


class PeriodCompareStep(_BaseStep):
    operation: Literal["period_compare"]
    params: PeriodCompareParams


class MissingValuesStep(_BaseStep):
    operation: Literal["missing_values"]
    params: MissingValuesParams


class DistributionStep(_BaseStep):
    operation: Literal["distribution"]
    params: DistributionParams


class OutlierIQRStep(_BaseStep):
    operation: Literal["outlier_iqr"]
    params: OutlierIQRParams


class PivotTableStep(_BaseStep):
    operation: Literal["pivot_table"]
    params: PivotTableParams


class FilterRowsStep(_BaseStep):
    operation: Literal["filter_rows"]
    params: FilterRowsParams


class DerivedMetricStep(_BaseStep):
    operation: Literal["derived_metric"]
    params: DerivedMetricParams


AnalysisStep: TypeAlias = Annotated[
    DescribeStep
    | GroupByAggregateStep
    | MultiAggregateStep
    | TopKStep
    | ValueCountsStep
    | CorrelationStep
    | TimeTrendStep
    | PeriodCompareStep
    | MissingValuesStep
    | DistributionStep
    | OutlierIQRStep
    | PivotTableStep
    | FilterRowsStep
    | DerivedMetricStep,
    Field(discriminator="operation"),
]


class AnalysisWorkflow(StrictSchemaModel):
    """A bounded, acyclic sequence of safe analysis steps."""

    version: Literal["2.0"]
    goal: str = Field(min_length=1, max_length=1000)
    primary_step_id: str = Field(pattern=r"^S0[1-6]$")
    quality_policy: QualityPolicy
    steps: list[AnalysisStep] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_graph(self) -> AnalysisWorkflow:
        expected_ids = [f"S{index:02d}" for index in range(1, len(self.steps) + 1)]
        actual_ids = [step.step_id for step in self.steps]
        if actual_ids != expected_ids:
            raise ValueError("steps must use continuous IDs S01..S06 in list order")

        step_by_id = {step.step_id: step for step in self.steps}
        evidence_ids = {
            step.step_id for step in self.steps if step.operation in EVIDENCE_OPERATIONS
        }
        if not evidence_ids:
            raise ValueError("workflow must contain at least one Evidence-producing step")
        if self.primary_step_id not in evidence_ids:
            raise ValueError("primary_step_id must reference an Evidence-producing step")

        for index, step in enumerate(self.steps):
            if index == 0 and step.input_ref != "source":
                raise ValueError("S01 must reference source")
            if step.input_ref == "source":
                continue
            referenced = step_by_id.get(step.input_ref)
            if referenced is None or actual_ids.index(step.input_ref) >= index:
                raise ValueError(f"{step.step_id} input_ref must reference an earlier step")
            if referenced.operation not in VIEW_OPERATIONS:
                raise ValueError(f"{step.step_id} input_ref must reference a View-producing step")
        return self
