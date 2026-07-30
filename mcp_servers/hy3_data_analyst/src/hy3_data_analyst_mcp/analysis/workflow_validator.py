"""Dataset-aware static validation for v0.2 workflows."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from functools import reduce
from operator import mul

from hy3_data_analyst_mcp.analysis.workflow_models import (
    AggregateRatioStep,
    AnalysisStep,
    AnalysisWorkflow,
    ColumnOperand,
    CorrelationStep,
    DerivedMetricStep,
    DescribeStep,
    DistributionStep,
    FilterCondition,
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
from hy3_data_analyst_mcp.errors import InvalidAnalysisWorkflowError
from hy3_data_analyst_mcp.models import DatasetProfile

MAX_WORKFLOW_STEPS = 6
MAX_PIVOT_CELLS = 1000


@dataclass(frozen=True)
class DatasetSchema:
    """Only the bounded metadata needed for pre-execution validation."""

    columns: tuple[str, ...]
    numeric_columns: frozenset[str] = frozenset()
    datetime_columns: frozenset[str] = frozenset()
    cardinalities: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        known = set(self.columns)
        if not self.columns or len(known) != len(self.columns):
            raise ValueError("dataset columns must be non-empty and unique")
        if not self.numeric_columns <= known or not self.datetime_columns <= known:
            raise ValueError("typed columns must be present in dataset columns")
        if any(column not in known or count < 0 for column, count in self.cardinalities.items()):
            raise ValueError("cardinalities must be non-negative and reference known columns")

    @classmethod
    def from_profile(cls, profile: DatasetProfile) -> DatasetSchema:
        """Build validation metadata without retaining samples or source paths."""
        numeric = frozenset(
            column.name for column in profile.columns if column.semantic_type == "numeric"
        )
        datetimes = frozenset(
            column.name for column in profile.columns if column.semantic_type == "datetime"
        )
        cardinalities = {column.name: column.unique_count for column in profile.columns}
        return cls(tuple(profile.column_names), numeric, datetimes, cardinalities)


@dataclass(frozen=True)
class _ViewSchema:
    columns: frozenset[str]
    numeric_columns: frozenset[str]
    datetime_columns: frozenset[str]


def validate_workflow(
    workflow: AnalysisWorkflow,
    dataset: DatasetSchema,
    *,
    max_steps: int = MAX_WORKFLOW_STEPS,
) -> None:
    """Reject unknown columns, invalid types, oversized pivots, and budget violations."""
    if not 1 <= max_steps <= MAX_WORKFLOW_STEPS:
        raise InvalidAnalysisWorkflowError(
            "The configured workflow step limit must be between 1 and 6.",
            "Use a max_steps value within the hard safety limit.",
        )
    if len(workflow.steps) > max_steps:
        raise InvalidAnalysisWorkflowError(
            f"The workflow has {len(workflow.steps)} steps but the configured limit "
            f"is {max_steps}.",
            "Reduce the workflow steps and retry.",
        )

    source = _ViewSchema(
        columns=frozenset(dataset.columns),
        numeric_columns=dataset.numeric_columns,
        datetime_columns=dataset.datetime_columns,
    )
    views: dict[str, _ViewSchema] = {}
    for step in workflow.steps:
        input_schema = source if step.input_ref == "source" else views[step.input_ref]
        referenced = _referenced_columns(step, input_schema)
        unknown = sorted(referenced - input_schema.columns)
        if unknown:
            _fail(step.step_id, f"Unknown columns: {', '.join(unknown)}.")
        if (
            isinstance(step, (DescribeStep, MissingValuesStep))
            and not step.params.target_columns
            and len(referenced) > 20
        ):
            _fail(
                step.step_id,
                "An implicit all-column target would exceed the 20-column limit.",
            )

        _validate_parameter_types(step, input_schema, workflow)
        _validate_output_names(step, input_schema)
        if isinstance(step, PivotTableStep):
            _validate_pivot_size(step, dataset)

        if isinstance(step, FilterRowsStep):
            views[step.step_id] = input_schema
        elif isinstance(step, DerivedMetricStep):
            views[step.step_id] = _ViewSchema(
                columns=input_schema.columns | {step.params.output_column},
                numeric_columns=input_schema.numeric_columns | {step.params.output_column},
                datetime_columns=input_schema.datetime_columns,
            )


def _referenced_columns(step: AnalysisStep, schema: _ViewSchema) -> set[str]:
    if isinstance(step, (DescribeStep, MissingValuesStep)):
        return set(step.params.target_columns or schema.columns)
    if isinstance(step, GroupByAggregateStep):
        return {*step.params.target_columns, *step.params.group_by}
    if isinstance(step, MultiAggregateStep):
        return {
            *step.params.group_by,
            *(metric.column for metric in step.params.metrics),
        }
    if isinstance(step, AggregateRatioStep):
        return {
            *step.params.group_by,
            step.params.numerator.column,
            step.params.denominator.column,
        }
    if isinstance(step, TopKStep):
        return {*step.params.target_columns, *step.params.group_by}
    if isinstance(step, ValueCountsStep):
        return {step.params.column, *step.params.group_by}
    if isinstance(step, CorrelationStep):
        return set(step.params.target_columns)
    if isinstance(step, TimeTrendStep):
        return {step.params.time_column, *step.params.target_columns}
    if isinstance(step, PeriodCompareStep):
        return {
            step.params.time_column,
            *step.params.target_columns,
            *step.params.group_by,
        }
    if isinstance(step, (DistributionStep, OutlierIQRStep)):
        return set(step.params.target_columns)
    if isinstance(step, PivotTableStep):
        return {
            *step.params.rows,
            *step.params.columns,
            *(metric.column for metric in step.params.metrics),
        }
    if isinstance(step, FilterRowsStep):
        return {condition.column for condition in step.params.conditions}
    if isinstance(step, DerivedMetricStep):
        return {
            operand.column
            for operand in (step.params.left, step.params.right)
            if isinstance(operand, ColumnOperand)
        }
    raise AssertionError(f"Unhandled workflow step: {type(step).__name__}")


def _validate_parameter_types(
    step: AnalysisStep,
    schema: _ViewSchema,
    workflow: AnalysisWorkflow,
) -> None:
    numeric_required: set[str] = set()
    date_required: set[str] = set()

    if isinstance(step, GroupByAggregateStep) and step.params.aggregation != "count":
        numeric_required.update(step.params.target_columns)
    elif isinstance(step, MultiAggregateStep):
        numeric_required.update(
            metric.column for metric in step.params.metrics if metric.aggregation != "count"
        )
    elif isinstance(step, AggregateRatioStep):
        numeric_required.update(
            metric.column
            for metric in (step.params.numerator, step.params.denominator)
            if metric.aggregation != "count"
        )
    elif isinstance(step, CorrelationStep):
        numeric_required.update(step.params.target_columns)
    elif isinstance(step, (TimeTrendStep, PeriodCompareStep)):
        date_required.add(step.params.time_column)
        if step.params.aggregation != "count":
            numeric_required.update(step.params.target_columns)
    elif isinstance(step, (DistributionStep, OutlierIQRStep)):
        numeric_required.update(step.params.target_columns)
    elif isinstance(step, PivotTableStep):
        numeric_required.update(
            metric.column for metric in step.params.metrics if metric.aggregation != "count"
        )
    elif isinstance(step, DerivedMetricStep):
        numeric_required.update(
            operand.column
            for operand in (step.params.left, step.params.right)
            if isinstance(operand, ColumnOperand)
        )
    elif isinstance(step, FilterRowsStep):
        for condition in step.params.conditions:
            _validate_filter_type(condition, schema, step.step_id)

    if workflow.quality_policy.numeric_conversion == "strict":
        invalid_numeric = sorted(numeric_required - schema.numeric_columns)
        if invalid_numeric:
            _fail(
                step.step_id,
                f"Numeric operation requires numeric columns: {', '.join(invalid_numeric)}.",
            )
    if workflow.quality_policy.date_conversion == "strict":
        invalid_dates = sorted(date_required - schema.datetime_columns)
        if invalid_dates:
            _fail(
                step.step_id,
                f"Date operation requires datetime columns: {', '.join(invalid_dates)}.",
            )


def _validate_filter_type(condition: FilterCondition, schema: _ViewSchema, step_id: str) -> None:
    collection_operators = {"in", "not_in", "between"}
    comparison_operators = {"eq", "ne", "gt", "gte", "lt", "lte", *collection_operators}
    if condition.column in schema.numeric_columns:
        if condition.operator == "contains":
            _fail(step_id, f"contains is not valid for numeric column {condition.column}.")
        if condition.operator not in comparison_operators:
            return
        values = (
            condition.values if condition.operator in collection_operators else [condition.value]
        )
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            _fail(step_id, f"Numeric filter for {condition.column} requires numeric values.")
    elif condition.column in schema.datetime_columns:
        if condition.operator == "contains":
            _fail(step_id, f"contains is not valid for datetime column {condition.column}.")
        if condition.operator not in comparison_operators:
            return
        values = (
            condition.values if condition.operator in collection_operators else [condition.value]
        )
        if any(not isinstance(value, str) for value in values):
            _fail(step_id, f"Datetime filter for {condition.column} requires ISO date strings.")


def _validate_output_names(step: AnalysisStep, schema: _ViewSchema) -> None:
    aliases: Collection[str] = ()
    if isinstance(step, (MultiAggregateStep, PivotTableStep)):
        aliases = [metric.alias for metric in step.params.metrics]
    elif isinstance(step, AggregateRatioStep):
        aliases = [
            step.params.numerator.alias,
            step.params.denominator.alias,
            step.params.ratio_alias,
        ]
    conflicts = sorted(set(aliases) & schema.columns)
    if conflicts:
        _fail(step.step_id, f"Output aliases conflict with input columns: {', '.join(conflicts)}.")
    if isinstance(step, DerivedMetricStep) and step.params.output_column in schema.columns:
        _fail(step.step_id, f"Derived output column already exists: {step.params.output_column}.")


def _validate_pivot_size(step: PivotTableStep, dataset: DatasetSchema) -> None:
    dimensions = [*step.params.rows, *step.params.columns]
    missing = sorted(column for column in dimensions if column not in dataset.cardinalities)
    if missing:
        _fail(
            step.step_id,
            f"Pivot size cannot be predicted without cardinalities for: {', '.join(missing)}.",
        )
    dimension_sizes = [max(1, dataset.cardinalities[column]) for column in dimensions]
    predicted_cells = reduce(mul, dimension_sizes, len(step.params.metrics))
    if predicted_cells > MAX_PIVOT_CELLS:
        _fail(
            step.step_id,
            f"Pivot would create about {predicted_cells} cells, above the 1000-cell limit.",
        )


def _fail(step_id: str, message: str) -> None:
    raise InvalidAnalysisWorkflowError(
        message,
        "Use exact compatible columns and keep the workflow within static safety limits.",
        step_id=step_id,
    )
