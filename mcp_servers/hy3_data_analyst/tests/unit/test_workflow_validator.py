"""Dataset-aware static validator tests for v0.2 workflows."""

from typing import Any

import pytest

from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema, validate_workflow
from hy3_data_analyst_mcp.errors import InvalidAnalysisWorkflowError
from hy3_data_analyst_mcp.models import (
    ColumnProfile,
    DatasetProfile,
    DatasetQuality,
    FileInfo,
)


def _workflow(
    steps: list[dict[str, Any]],
    *,
    quality_policy: dict[str, Any] | None = None,
) -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Validate columns before execution.",
            "primary_step_id": steps[-1]["step_id"],
            "quality_policy": quality_policy or {},
            "steps": steps,
            "rationale": "Static validation only.",
        }
    )


def _step(
    step_id: str,
    operation: str,
    params: dict[str, Any],
    *,
    input_ref: str = "source",
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "operation": operation,
        "input_ref": input_ref,
        "params": params,
        "purpose": f"Validate {operation}.",
    }


@pytest.fixture
def dataset() -> DatasetSchema:
    return DatasetSchema(
        columns=("date", "region", "category", "revenue", "cost", "profit", "amount_text"),
        numeric_columns=frozenset({"revenue", "cost", "profit"}),
        datetime_columns=frozenset({"date"}),
        cardinalities={
            "date": 30,
            "region": 4,
            "category": 3,
            "revenue": 25,
            "cost": 20,
            "profit": 22,
            "amount_text": 20,
        },
    )


def test_valid_view_chain_tracks_derived_columns(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {"conditions": [{"column": "region", "operator": "eq", "value": "North"}]},
            ),
            _step(
                "S02",
                "derived_metric",
                {
                    "output_column": "margin",
                    "operator": "divide",
                    "left": {"kind": "column", "column": "profit"},
                    "right": {"kind": "column", "column": "revenue"},
                },
                input_ref="S01",
            ),
            _step(
                "S03",
                "multi_aggregate",
                {
                    "group_by": ["region"],
                    "metrics": [
                        {"column": "margin", "aggregation": "mean", "alias": "mean_margin"}
                    ],
                },
                input_ref="S02",
            ),
        ]
    )

    validate_workflow(workflow, dataset)


@pytest.mark.parametrize(
    ("operation", "params"),
    [
        (
            "groupby_aggregate",
            {
                "target_columns": ["revenue"],
                "group_by": ["region"],
                "aggregation": "sum",
            },
        ),
        ("top_k", {"target_columns": ["revenue"], "group_by": ["region"]}),
        ("value_counts", {"column": "region", "group_by": ["category"]}),
        ("correlation", {"target_columns": ["revenue", "profit"]}),
        (
            "time_trend",
            {
                "time_column": "date",
                "target_columns": ["revenue"],
                "aggregation": "sum",
            },
        ),
        (
            "period_compare",
            {
                "time_column": "date",
                "target_columns": ["revenue"],
                "aggregation": "sum",
                "grain": "month",
                "comparison": "previous_period",
            },
        ),
        ("outlier_iqr", {"target_columns": ["profit"]}),
    ],
)
def test_validator_accepts_each_existing_evidence_shape(
    operation: str, params: dict[str, Any], dataset: DatasetSchema
) -> None:
    validate_workflow(_workflow([_step("S01", operation, params)]), dataset)


def test_count_aggregation_does_not_require_numeric_input(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "groupby_aggregate",
                {
                    "target_columns": ["amount_text"],
                    "group_by": ["region"],
                    "aggregation": "count",
                },
            )
        ]
    )
    validate_workflow(workflow, dataset)


def test_unknown_column_is_rejected_with_stable_step_error(dataset: DatasetSchema) -> None:
    workflow = _workflow([_step("S01", "top_k", {"target_columns": ["invented"], "limit": 5})])
    with pytest.raises(InvalidAnalysisWorkflowError) as captured:
        validate_workflow(workflow, dataset)

    assert captured.value.as_dict()["step_id"] == "S01"
    assert "invented" in captured.value.message
    assert "D:\\" not in captured.value.message


def test_strict_numeric_type_rejects_text_but_coerce_policy_allows_it(
    dataset: DatasetSchema,
) -> None:
    step = _step("S01", "distribution", {"target_columns": ["amount_text"]})
    with pytest.raises(InvalidAnalysisWorkflowError, match="Numeric operation"):
        validate_workflow(_workflow([step]), dataset)

    validate_workflow(
        _workflow([step], quality_policy={"numeric_conversion": "coerce"}),
        dataset,
    )


def test_strict_date_type_rejects_non_date_column(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "time_trend",
                {
                    "time_column": "amount_text",
                    "target_columns": ["revenue"],
                    "aggregation": "sum",
                },
            )
        ],
        quality_policy={"date_conversion": "strict"},
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="datetime columns"):
        validate_workflow(workflow, dataset)


@pytest.mark.parametrize(
    "condition",
    [
        {"column": "revenue", "operator": "contains", "value": "10"},
        {"column": "revenue", "operator": "gt", "value": "10"},
        {"column": "revenue", "operator": "in", "values": [10, "20"]},
    ],
)
def test_numeric_filter_rejects_incompatible_operators_and_values(
    condition: dict[str, Any], dataset: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step("S01", "filter_rows", {"conditions": [condition]}),
            _step("S02", "describe", {"target_columns": []}, input_ref="S01"),
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError):
        validate_workflow(workflow, dataset)


@pytest.mark.parametrize(
    "condition",
    [
        {"column": "date", "operator": "contains", "value": "2025"},
        {"column": "date", "operator": "gte", "value": 20250101},
    ],
)
def test_datetime_filter_rejects_contains_and_non_string_values(
    condition: dict[str, Any], dataset: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step("S01", "filter_rows", {"conditions": [condition]}),
            _step("S02", "describe", {"target_columns": []}, input_ref="S01"),
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError):
        validate_workflow(workflow, dataset)


def test_null_filters_do_not_require_scalar_values(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {
                    "conditions": [
                        {"column": "revenue", "operator": "not_null"},
                        {"column": "date", "operator": "is_null"},
                    ]
                },
            ),
            _step("S02", "describe", {"target_columns": []}, input_ref="S01"),
        ]
    )
    validate_workflow(workflow, dataset)


def test_derived_output_must_not_overwrite_an_input_column(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "derived_metric",
                {
                    "output_column": "profit",
                    "operator": "subtract",
                    "left": {"kind": "column", "column": "revenue"},
                    "right": {"kind": "column", "column": "cost"},
                },
            ),
            _step("S02", "describe", {"target_columns": []}, input_ref="S01"),
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="already exists"):
        validate_workflow(workflow, dataset)


def test_aggregate_alias_must_not_conflict_with_input(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "multi_aggregate",
                {
                    "group_by": ["region"],
                    "metrics": [{"column": "profit", "aggregation": "sum", "alias": "revenue"}],
                },
            )
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="aliases conflict"):
        validate_workflow(workflow, dataset)


def test_pivot_prediction_rejects_more_than_1000_cells(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "pivot_table",
                {
                    "rows": ["date"],
                    "columns": ["amount_text"],
                    "metrics": [
                        {"column": "revenue", "aggregation": "sum", "alias": "sum_revenue"},
                        {"column": "profit", "aggregation": "sum", "alias": "sum_profit"},
                    ],
                },
            )
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="above the 1000-cell limit"):
        validate_workflow(workflow, dataset)


def test_small_pivot_is_accepted(dataset: DatasetSchema) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "pivot_table",
                {
                    "rows": ["region"],
                    "columns": ["category"],
                    "metrics": [
                        {"column": "revenue", "aggregation": "sum", "alias": "sum_revenue"}
                    ],
                },
            )
        ]
    )
    validate_workflow(workflow, dataset)


def test_pivot_requires_cardinalities_for_every_dimension(dataset: DatasetSchema) -> None:
    incomplete = DatasetSchema(
        columns=dataset.columns,
        numeric_columns=dataset.numeric_columns,
        datetime_columns=dataset.datetime_columns,
        cardinalities={"region": 4},
    )
    workflow = _workflow(
        [
            _step(
                "S01",
                "pivot_table",
                {
                    "rows": ["region"],
                    "columns": ["category"],
                    "metrics": [
                        {"column": "revenue", "aggregation": "sum", "alias": "sum_revenue"}
                    ],
                },
            )
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="cannot be predicted"):
        validate_workflow(workflow, incomplete)


def test_configured_step_budget_can_only_reduce_hard_limit(dataset: DatasetSchema) -> None:
    workflow = _workflow([_step("S01", "describe", {"target_columns": []})])
    with pytest.raises(InvalidAnalysisWorkflowError, match="between 1 and 6"):
        validate_workflow(workflow, dataset, max_steps=7)
    two_step_workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {"conditions": [{"column": "region", "operator": "not_null"}]},
            ),
            _step("S02", "describe", {"target_columns": []}, input_ref="S01"),
        ]
    )
    with pytest.raises(InvalidAnalysisWorkflowError, match="configured limit is 1"):
        validate_workflow(two_step_workflow, dataset, max_steps=1)


def test_implicit_all_column_target_respects_20_column_limit() -> None:
    columns = tuple(f"column_{index}" for index in range(21))
    dataset = DatasetSchema(columns=columns)
    workflow = _workflow([_step("S01", "describe", {"target_columns": []})])
    with pytest.raises(InvalidAnalysisWorkflowError, match="20-column limit"):
        validate_workflow(workflow, dataset)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"columns": ()},
        {"columns": ("a", "a")},
        {"columns": ("a",), "numeric_columns": frozenset({"missing"})},
        {"columns": ("a",), "cardinalities": {"missing": 1}},
        {"columns": ("a",), "cardinalities": {"a": -1}},
    ],
)
def test_dataset_schema_rejects_invalid_metadata(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        DatasetSchema(**kwargs)


def test_dataset_schema_can_be_built_from_bounded_profile() -> None:
    profile = DatasetProfile(
        file=FileInfo(name="safe.csv", format="csv", size_bytes=10),
        row_count=3,
        column_count=3,
        column_names=["amount", "date", "region"],
        duplicate_row_count=0,
        columns=[
            ColumnProfile(
                name="amount",
                pandas_dtype="float64",
                semantic_type="numeric",
                non_null_count=3,
                missing_rate=0,
                unique_count=3,
                statistics={},
            ),
            ColumnProfile(
                name="date",
                pandas_dtype="object",
                semantic_type="datetime",
                non_null_count=3,
                missing_rate=0,
                unique_count=3,
                statistics={},
            ),
            ColumnProfile(
                name="region",
                pandas_dtype="object",
                semantic_type="categorical",
                non_null_count=3,
                missing_rate=0,
                unique_count=2,
                statistics={},
            ),
        ],
        sample_rows=[],
        quality=DatasetQuality(score=100, severity="info", analyzed_rows=3),
    )

    schema = DatasetSchema.from_profile(profile)

    assert schema.numeric_columns == {"amount"}
    assert schema.datetime_columns == {"date"}
    assert schema.cardinalities["region"] == 2
