"""Deterministic execution tests for the v0.2-alpha workflow engine."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from hy3_data_analyst_mcp.analysis.workflow_executor import (
    WorkflowExecutionResult,
    execute_workflow,
)
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.errors import WorkflowExecutionError


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2025-01-05",
                "2025-01-20",
                "2025-02-05",
                "2025-02-20",
                "2025-03-10",
                "bad-date",
            ],
            "region": ["East", "east", "East", "West", "West", "West"],
            "category": ["A", "B", "A", "A", "B", None],
            "revenue": [100.0, 200.0, 150.0, 300.0, 0.0, 50.0],
            "profit": [10.0, 30.0, 15.0, 60.0, 0.0, None],
            "note": ["a.b", "AB", "a.b", "plain", None, "aXb"],
        }
    )


@pytest.fixture
def dataset_schema() -> DatasetSchema:
    return DatasetSchema(
        columns=("date", "region", "category", "revenue", "profit", "note"),
        numeric_columns=frozenset({"revenue", "profit"}),
        datetime_columns=frozenset({"date"}),
        cardinalities={
            "date": 6,
            "region": 3,
            "category": 2,
            "revenue": 6,
            "profit": 5,
            "note": 5,
        },
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
        "purpose": f"Execute {operation} deterministically.",
    }


def _workflow(
    steps: list[dict[str, Any]], *, primary_step_id: str | None = None
) -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Exercise the Phase C executor.",
            "primary_step_id": primary_step_id or steps[-1]["step_id"],
            "quality_policy": {},
            "steps": steps,
            "rationale": "Use only local deterministic operations.",
        }
    )


def _execute(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    dataset_schema: DatasetSchema,
    **kwargs: Any,
) -> WorkflowExecutionResult:
    return execute_workflow(
        frame,
        workflow,
        source_file_name="sales.csv",
        dataset_schema=dataset_schema,
        **kwargs,
    )


def test_three_step_filter_multi_aggregate_and_value_counts(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    original = frame.copy(deep=True)
    workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {
                    "combine": "all",
                    "conditions": [
                        {"column": "region", "operator": "eq", "value": "EAST"},
                        {"column": "date", "operator": "gte", "value": "2025-01-01"},
                    ],
                },
            ),
            _step(
                "S02",
                "multi_aggregate",
                {
                    "group_by": ["category"],
                    "metrics": [
                        {"column": "revenue", "aggregation": "sum", "alias": "revenue_sum"},
                        {"column": "profit", "aggregation": "mean", "alias": "profit_mean"},
                    ],
                    "sort_by": "revenue_sum",
                    "sort_order": "desc",
                },
                input_ref="S01",
            ),
            _step(
                "S03",
                "value_counts",
                {"column": "category", "normalize": True},
                input_ref="S01",
            ),
        ],
        primary_step_id="S02",
    )

    result = _execute(frame, workflow, dataset_schema)

    assert [item.evidence_id for item in result.evidence_ledger.items] == ["E01", "E02"]
    assert result.step_audits[0].input_rows == 6
    assert result.step_audits[0].output_rows == 3
    aggregate_records = result.evidence_ledger.items[0].records
    assert aggregate_records == [
        {"category": "A", "revenue_sum": 250.0, "profit_mean": 12.5},
        {"category": "B", "revenue_sum": 200.0, "profit_mean": 30.0},
    ]
    shares = {
        record["category"]: record["share"] for record in result.evidence_ledger.items[1].records
    }
    assert shares == pytest.approx({"A": 2 / 3, "B": 1 / 3})
    pd.testing.assert_frame_equal(frame, original)


def test_filter_contains_is_literal_and_null_filters_compose(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {
                    "combine": "any",
                    "conditions": [
                        {"column": "note", "operator": "contains", "value": "a.b"},
                        {"column": "note", "operator": "is_null"},
                    ],
                },
            ),
            _step(
                "S02",
                "describe",
                {"target_columns": ["revenue"]},
                input_ref="S01",
            ),
        ]
    )

    result = _execute(frame, workflow, dataset_schema)

    assert result.step_audits[0].output_rows == 3
    record = result.evidence_ledger.items[0].records[0]
    assert record["count"] == 3
    assert record["q1"] == pytest.approx(50.0)
    assert record["q3"] == pytest.approx(125.0)


def test_grouped_value_counts_uses_group_denominators(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "value_counts",
                {
                    "column": "category",
                    "group_by": ["region"],
                    "normalize": True,
                    "include_null": False,
                    "limit": 100,
                },
            )
        ]
    )

    item = _execute(frame, workflow, dataset_schema).evidence_ledger.items[0]

    assert item.used_rows == 5
    assert all(isinstance(record["count"], int) for record in item.records)
    west_shares = [record["share"] for record in item.records if record["region"] == "West"]
    assert west_shares == pytest.approx([0.5, 0.5])


def test_explicit_period_compare_reports_change_and_zero_base(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "period_compare",
                {
                    "time_column": "date",
                    "target_columns": ["revenue"],
                    "aggregation": "sum",
                    "grain": "month",
                    "comparison": "explicit",
                    "group_by": ["region"],
                    "period_a": {"start": "2025-01-01", "end": "2025-01-31"},
                    "period_b": {"start": "2025-02-01", "end": "2025-02-28"},
                },
            )
        ]
    )

    item = _execute(frame, workflow, dataset_schema).evidence_ledger.items[0]
    records = {record["region"]: record for record in item.records}

    assert records["East"]["period_a_value"] == 100.0
    assert records["East"]["period_b_value"] == 150.0
    assert records["East"]["change_rate"] == 0.5
    assert records["east"]["period_b_value"] is None
    assert records["West"]["period_a_value"] is None
    assert item.used_rows == 4


def test_previous_period_warns_when_current_period_is_incomplete(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "period_compare",
                {
                    "time_column": "date",
                    "target_columns": ["revenue"],
                    "aggregation": "sum",
                    "grain": "month",
                    "comparison": "previous_period",
                },
            )
        ]
    )

    item = _execute(frame, workflow, dataset_schema).evidence_ledger.items[0]

    assert item.records[0]["period_a_value"] == 450.0
    assert item.records[0]["period_b_value"] == 0.0
    assert "incomplete" in item.warnings[0]
    assert any("invalid dates" in warning for warning in item.warnings)


def test_period_compare_zero_base_returns_null_rate_and_warning() -> None:
    small_frame = pd.DataFrame({"date": ["2025-01-10", "2025-02-10"], "revenue": [0.0, 10.0]})
    schema = DatasetSchema(
        columns=("date", "revenue"),
        numeric_columns=frozenset({"revenue"}),
        datetime_columns=frozenset({"date"}),
    )
    workflow = _workflow(
        [
            _step(
                "S01",
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
            )
        ]
    )

    item = _execute(small_frame, workflow, schema).evidence_ledger.items[0]

    assert item.records[0]["absolute_change"] == 10.0
    assert item.records[0]["change_rate"] is None
    assert any("base period is zero" in warning for warning in item.warnings)


def test_empty_view_fails_at_dependent_step_with_completed_audit(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "filter_rows",
                {"conditions": [{"column": "region", "operator": "eq", "value": "missing"}]},
            ),
            _step(
                "S02",
                "describe",
                {"target_columns": ["revenue"]},
                input_ref="S01",
            ),
        ]
    )

    with pytest.raises(WorkflowExecutionError) as captured:
        _execute(frame, workflow, dataset_schema)

    payload = captured.value.as_dict()
    assert payload["step_id"] == "S02"
    assert payload["completed_step_audits"][0]["output_rows"] == 0


def test_failure_preserves_completed_evidence(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step("S01", "describe", {"target_columns": ["revenue"]}),
            _step(
                "S02",
                "period_compare",
                {
                    "time_column": "date",
                    "target_columns": ["revenue"],
                    "aggregation": "sum",
                    "grain": "month",
                    "comparison": "explicit",
                    "period_a": {"start": "2024-01-01", "end": "2024-01-31"},
                    "period_b": {"start": "2024-02-01", "end": "2024-02-29"},
                },
            ),
        ]
    )

    with pytest.raises(WorkflowExecutionError) as captured:
        _execute(frame, workflow, dataset_schema)

    payload = captured.value.as_dict()
    assert payload["step_id"] == "S02"
    assert payload["completed_evidence"][0]["evidence_id"] == "E01"


def test_per_step_and_ledger_record_budgets_are_independent_of_calculation(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    steps = [
        _step(f"S{index:02d}", "top_k", {"target_columns": ["revenue"], "limit": 6})
        for index in range(1, 4)
    ]
    result = _execute(
        frame,
        _workflow(steps),
        dataset_schema,
        max_records_per_step=2,
        max_records_total=3,
    )

    assert [len(item.records) for item in result.evidence_ledger.items] == [2, 1, 0]
    assert sum(len(item.records) for item in result.evidence_ledger.items) == 3
    assert all(item.truncated for item in result.evidence_ledger.items)


@pytest.mark.parametrize(
    ("operation", "params", "expected_key"),
    [
        (
            "groupby_aggregate",
            {
                "target_columns": ["revenue"],
                "group_by": ["region"],
                "aggregation": "sum",
            },
            "region",
        ),
        ("top_k", {"target_columns": ["revenue"], "limit": 2}, "revenue"),
        ("correlation", {"target_columns": ["revenue", "profit"]}, "correlation"),
        (
            "time_trend",
            {
                "time_column": "date",
                "target_columns": ["revenue"],
                "aggregation": "sum",
                "grain": "quarter",
            },
            "date",
        ),
        ("missing_values", {"target_columns": ["profit"]}, "missing_count"),
        ("outlier_iqr", {"target_columns": ["revenue"]}, "source_row_numbers"),
    ],
)
def test_existing_operations_run_inside_workflows(
    operation: str,
    params: dict[str, Any],
    expected_key: str,
    frame: pd.DataFrame,
    dataset_schema: DatasetSchema,
) -> None:
    item = _execute(
        frame, _workflow([_step("S01", operation, params)]), dataset_schema
    ).evidence_ledger.items[0]
    assert expected_key in item.records[0]


def test_phase_e_operation_is_rejected_during_phase_d(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow([_step("S01", "distribution", {"target_columns": ["revenue"]})])
    with pytest.raises(WorkflowExecutionError, match="not available"):
        _execute(frame, workflow, dataset_schema)
