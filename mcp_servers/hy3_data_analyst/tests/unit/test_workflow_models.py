"""Schema-only tests for every v0.2 workflow operation."""

from typing import Any

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow


def _workflow(
    steps: list[dict[str, Any]],
    *,
    primary_step_id: str | None = None,
) -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Validate a safe workflow.",
            "primary_step_id": primary_step_id or steps[-1]["step_id"],
            "quality_policy": {},
            "steps": steps,
            "rationale": "Use deterministic operations only.",
        }
    )


def _step(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": "S01",
        "operation": operation,
        "input_ref": "source",
        "params": params,
        "purpose": f"Validate {operation}.",
    }


VALID_OPERATION_PARAMS: list[tuple[str, dict[str, Any]]] = [
    ("describe", {"target_columns": ["revenue"]}),
    (
        "groupby_aggregate",
        {
            "target_columns": ["revenue"],
            "group_by": ["region"],
            "aggregation": "sum",
        },
    ),
    (
        "multi_aggregate",
        {
            "group_by": ["region"],
            "metrics": [{"column": "revenue", "aggregation": "sum", "alias": "revenue_sum"}],
            "sort_by": "revenue_sum",
        },
    ),
    ("top_k", {"target_columns": ["revenue"], "limit": 5}),
    ("value_counts", {"column": "region", "normalize": True}),
    ("correlation", {"target_columns": ["revenue", "profit"]}),
    (
        "time_trend",
        {
            "time_column": "date",
            "target_columns": ["revenue"],
            "aggregation": "sum",
            "grain": "quarter",
        },
    ),
    (
        "period_compare",
        {
            "time_column": "date",
            "target_columns": ["revenue"],
            "aggregation": "sum",
            "grain": "month",
            "comparison": "explicit",
            "period_a": {"start": "2025-01-01", "end": "2025-01-31"},
            "period_b": {"start": "2025-02-01", "end": "2025-02-28"},
        },
    ),
    ("missing_values", {"target_columns": []}),
    ("distribution", {"target_columns": ["revenue"], "bins": 10}),
    ("outlier_iqr", {"target_columns": ["profit"]}),
    (
        "pivot_table",
        {
            "rows": ["region"],
            "columns": ["category"],
            "metrics": [{"column": "revenue", "aggregation": "sum", "alias": "revenue_sum"}],
        },
    ),
    (
        "filter_rows",
        {
            "combine": "all",
            "conditions": [
                {
                    "column": "region",
                    "operator": "in",
                    "values": ["North", "South"],
                }
            ],
        },
    ),
    (
        "derived_metric",
        {
            "output_column": "margin",
            "operator": "divide",
            "left": {"kind": "column", "column": "profit"},
            "right": {"kind": "column", "column": "revenue"},
        },
    ),
]


@pytest.mark.parametrize(("operation", "params"), VALID_OPERATION_PARAMS)
def test_every_operation_has_a_valid_discriminated_schema(
    operation: str, params: dict[str, Any]
) -> None:
    first = _step(operation, params)
    if operation in {"filter_rows", "derived_metric"}:
        steps = [
            first,
            {
                "step_id": "S02",
                "operation": "describe",
                "input_ref": "S01",
                "params": {"target_columns": []},
                "purpose": "Produce Evidence from the View.",
            },
        ]
    else:
        steps = [first]

    workflow = _workflow(steps)

    assert workflow.steps[0].operation == operation
    assert workflow.version == "2.0"


def test_workflow_json_schema_uses_operation_discriminator() -> None:
    schema_text = str(AnalysisWorkflow.model_json_schema())
    assert "discriminator" in schema_text
    assert "filter_rows" in schema_text
    assert "derived_metric" in schema_text


@pytest.mark.parametrize(
    "payload",
    [
        {
            "column": "region",
            "operator": "contains",
            "value": "North",
            "values": ["forbidden"],
        },
        {"column": "region", "operator": "between", "values": [1, "2"]},
        {"column": "region", "operator": "in", "values": []},
        {"column": "region", "operator": "is_null", "value": "forbidden"},
        {"column": "region", "operator": "contains", "value": 3},
    ],
)
def test_filter_condition_rejects_invalid_argument_shapes(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _workflow(
            [
                _step("filter_rows", {"conditions": [payload]}),
                {
                    "step_id": "S02",
                    "operation": "describe",
                    "input_ref": "S01",
                    "params": {"target_columns": []},
                    "purpose": "Evidence.",
                },
            ]
        )


def test_period_compare_requires_two_ordered_explicit_ranges() -> None:
    params = {
        "time_column": "date",
        "target_columns": ["revenue"],
        "aggregation": "sum",
        "grain": "month",
        "comparison": "explicit",
        "period_a": {"start": "2025-02-01", "end": "2025-01-01"},
    }
    with pytest.raises(ValidationError):
        _workflow([_step("period_compare", params)])


def test_distribution_requires_strictly_increasing_quantiles() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        _workflow(
            [
                _step(
                    "distribution",
                    {"target_columns": ["revenue"], "quantiles": [0.5, 0.25]},
                )
            ]
        )


def test_derived_metric_rejects_two_constants() -> None:
    params = {
        "output_column": "unsafe",
        "operator": "add",
        "left": {"kind": "constant", "value": 1},
        "right": {"kind": "constant", "value": 2},
    }
    with pytest.raises(ValidationError, match="must not both be constants"):
        _workflow([_step("derived_metric", params)])


def test_derived_metric_rejects_formula_fields_and_illegal_operators() -> None:
    base = {
        "output_column": "unsafe",
        "operator": "add",
        "left": {"kind": "column", "column": "revenue"},
        "right": {"kind": "constant", "value": 2},
    }
    with pytest.raises(ValidationError):
        _workflow([_step("derived_metric", {**base, "formula": "eval('1+2')"})])
    with pytest.raises(ValidationError):
        _workflow([_step("derived_metric", {**base, "operator": "power"})])


@pytest.mark.parametrize(
    ("steps", "primary"),
    [
        (
            [
                {
                    **_step("describe", {"target_columns": []}),
                    "step_id": "S02",
                }
            ],
            "S02",
        ),
        (
            [
                _step("describe", {"target_columns": []}),
                {
                    "step_id": "S02",
                    "operation": "describe",
                    "input_ref": "S01",
                    "params": {"target_columns": []},
                    "purpose": "Invalid Evidence dependency.",
                },
            ],
            "S02",
        ),
        (
            [
                _step("filter_rows", {"conditions": [{"column": "x", "operator": "not_null"}]}),
                {
                    "step_id": "S02",
                    "operation": "describe",
                    "input_ref": "S03",
                    "params": {"target_columns": []},
                    "purpose": "Forward reference.",
                },
                {
                    "step_id": "S03",
                    "operation": "filter_rows",
                    "input_ref": "source",
                    "params": {"conditions": [{"column": "x", "operator": "not_null"}]},
                    "purpose": "Later View.",
                },
            ],
            "S02",
        ),
        (
            [_step("filter_rows", {"conditions": [{"column": "x", "operator": "not_null"}]})],
            "S01",
        ),
    ],
)
def test_workflow_rejects_invalid_ids_dependencies_and_primary_steps(
    steps: list[dict[str, Any]], primary: str
) -> None:
    with pytest.raises(ValidationError):
        _workflow(steps, primary_step_id=primary)


def test_workflow_and_params_reject_extra_fields_and_collection_overflow() -> None:
    payload = _step("describe", {"target_columns": [f"c{i}" for i in range(21)]})
    payload["code"] = "print('forbidden')"
    with pytest.raises(ValidationError):
        _workflow([payload])


def test_workflow_rejects_missing_policy_invalid_policy_and_more_than_six_steps() -> None:
    valid = _workflow([_step("describe", {"target_columns": []})]).model_dump(mode="json")
    del valid["quality_policy"]
    with pytest.raises(ValidationError):
        AnalysisWorkflow.model_validate(valid)

    valid["quality_policy"] = {"missing": "silently_delete"}
    with pytest.raises(ValidationError):
        AnalysisWorkflow.model_validate(valid)

    too_many = [_step("describe", {"target_columns": []}) for _ in range(7)]
    for index, item in enumerate(too_many, start=1):
        item["step_id"] = f"S{index:02d}"
    with pytest.raises(ValidationError):
        _workflow(too_many, primary_step_id="S01")
