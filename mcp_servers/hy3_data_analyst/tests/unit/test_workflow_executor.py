"""Deterministic execution tests for the v0.2-alpha workflow engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

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


def test_aggregate_ratio_uses_one_pairwise_complete_population(
    frame: pd.DataFrame,
    dataset_schema: DatasetSchema,
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "aggregate_ratio",
                {
                    "group_by": ["region"],
                    "numerator": {
                        "column": "profit",
                        "aggregation": "sum",
                        "alias": "profit_sum",
                    },
                    "denominator": {
                        "column": "revenue",
                        "aggregation": "sum",
                        "alias": "revenue_sum",
                    },
                    "ratio_alias": "margin_pct",
                    "scale": 100,
                    "sort_by": "margin_pct",
                    "sort_order": "desc",
                },
            )
        ]
    )

    result = execute_workflow(
        frame,
        workflow,
        source_file_name="sales.csv",
        dataset_schema=dataset_schema,
    )

    evidence = result.evidence_ledger.items[0]
    assert evidence.operation == "aggregate_ratio"
    assert evidence.used_rows == 5
    assert evidence.excluded_rows == 1
    assert evidence.records == [
        {"region": "West", "profit_sum": 60.0, "revenue_sum": 300.0, "margin_pct": 20.0},
        {"region": "east", "profit_sum": 30.0, "revenue_sum": 200.0, "margin_pct": 15.0},
        {"region": "East", "profit_sum": 25.0, "revenue_sum": 250.0, "margin_pct": 10.0},
    ]
    ratio_definition = cast(dict[str, Any], evidence.metrics["ratio_definition"])
    assert ratio_definition["aligned_rows"] is True


def test_example_sales_margin_regression_matches_client_acceptance_values() -> None:
    sales_path = Path(__file__).parents[2] / "examples" / "data" / "sales.csv"
    sales = pd.read_csv(sales_path)
    workflow = _workflow(
        [
            _step(
                "S01",
                "aggregate_ratio",
                {
                    "group_by": ["region"],
                    "numerator": {
                        "column": "profit",
                        "aggregation": "sum",
                        "alias": "profit_sum",
                    },
                    "denominator": {
                        "column": "revenue",
                        "aggregation": "sum",
                        "alias": "revenue_sum",
                    },
                    "ratio_alias": "margin_pct",
                    "scale": 100,
                    "sort_by": "margin_pct",
                },
            )
        ]
    )
    schema = DatasetSchema(
        columns=tuple(str(column) for column in sales.columns),
        numeric_columns=frozenset({"units", "unit_price", "revenue", "cost", "profit"}),
    )

    result = execute_workflow(
        sales,
        workflow,
        source_file_name="sales.csv",
        dataset_schema=schema,
    )

    by_region = {
        cast(str, record["region"]): record for record in result.evidence_ledger.items[0].records
    }
    assert by_region["West"]["revenue_sum"] == 4200.0
    assert by_region["West"]["profit_sum"] == 100.0
    assert by_region["West"]["margin_pct"] == pytest.approx(2.38095238095)
    assert by_region["East"]["margin_pct"] == pytest.approx(54.375)
    assert by_region["South"]["margin_pct"] == pytest.approx(37.2093023256)
    assert by_region["North"]["margin_pct"] == pytest.approx(51.1764705882)


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


def test_distribution_has_complete_statistics_and_deterministic_bins(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "distribution",
                {"target_columns": ["revenue"], "quantiles": [0.25, 0.5, 0.75], "bins": 5},
            )
        ]
    )

    record = _execute(frame, workflow, dataset_schema).evidence_ledger.items[0].records[0]

    assert record["count"] == 6
    assert record["missing"] == 0
    assert record["mean"] == pytest.approx(133.33333333333334)
    assert record["std"] == pytest.approx(108.01234497346434)
    assert record["min"] == 0.0
    assert record["max"] == 300.0
    assert record["quantiles"] == {"0.25": 62.5, "0.5": 125.0, "0.75": 187.5}
    bins = cast(list[dict[str, Any]], record["bins"])
    assert len(bins) == 5
    assert sum(item["count"] for item in bins) == 6


def test_distribution_constant_and_empty_numeric_columns_are_safe() -> None:
    frame = pd.DataFrame(
        {
            "constant": pd.Series([7.0, 7.0, None], dtype="float64"),
            "empty": pd.Series([None, None, None], dtype="float64"),
        }
    )
    schema = DatasetSchema(
        columns=("constant", "empty"),
        numeric_columns=frozenset({"constant", "empty"}),
        cardinalities={"constant": 1, "empty": 0},
    )
    workflow = _workflow(
        [
            _step(
                "S01",
                "distribution",
                {"target_columns": ["constant", "empty"], "bins": 5},
            )
        ]
    )

    item = _execute(frame, workflow, schema).evidence_ledger.items[0]

    assert item.records[0]["bins"] == [{"lower_bound": 7.0, "upper_bound": 7.0, "count": 2}]
    assert item.records[1]["count"] == 0
    assert item.records[1]["missing"] == 3
    assert item.records[1]["bins"] == []
    assert item.records[1]["mean"] is None
    assert any("constant" in warning for warning in item.warnings)
    assert any("no finite" in warning for warning in item.warnings)


def test_distribution_rejects_non_numeric_column(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow([_step("S01", "distribution", {"target_columns": ["note"]})])

    with pytest.raises(WorkflowExecutionError, match="requires numeric columns"):
        _execute(frame, workflow, dataset_schema)


def test_pivot_table_outputs_bounded_long_form_records_with_fill(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "pivot_table",
                {
                    "rows": ["region"],
                    "columns": ["category"],
                    "metrics": [
                        {"column": "revenue", "aggregation": "sum", "alias": "revenue_sum"},
                        {"column": "profit", "aggregation": "mean", "alias": "profit_mean"},
                    ],
                    "fill_value": 0.0,
                },
            )
        ]
    )

    item = _execute(frame, workflow, dataset_schema).evidence_ledger.items[0]

    assert item.metrics["actual_cells"] == 18
    assert item.metrics["actual_cells"] == len(item.records)
    assert all(
        set(record) == {"region", "category", "metric", "aggregation", "value"}
        for record in item.records
    )
    assert {record["metric"] for record in item.records} == {"revenue_sum", "profit_mean"}
    assert all(record["value"] is not None for record in item.records)
    missing_combinations = [
        record
        for record in item.records
        if record["region"] == "east" and record["category"] == "A"
    ]
    assert {record["value"] for record in missing_combinations} == {0.0}


def test_pivot_table_rejects_actual_cardinality_above_bound() -> None:
    frame = pd.DataFrame(
        {
            "row_dimension": list(range(501)),
            "column_dimension": ["only"] * 501,
            "value": list(range(501)),
        }
    )
    schema = DatasetSchema(
        columns=("row_dimension", "column_dimension", "value"),
        numeric_columns=frozenset({"row_dimension", "value"}),
        cardinalities={"row_dimension": 1, "column_dimension": 1, "value": 501},
    )
    workflow = _workflow(
        [
            _step(
                "S01",
                "pivot_table",
                {
                    "rows": ["row_dimension"],
                    "columns": ["column_dimension"],
                    "metrics": [
                        {"column": "value", "aggregation": "sum", "alias": "total"},
                        {"column": "value", "aggregation": "count", "alias": "observations"},
                    ],
                },
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="above the 1000-cell limit"):
        _execute(frame, workflow, schema)


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("add", [12.0, 24.0]),
        ("subtract", [8.0, 16.0]),
        ("multiply", [20.0, 80.0]),
        ("divide", [5.0, 5.0]),
    ],
)
def test_derived_metric_creates_a_chainable_isolated_view(
    operator: str, expected: list[float]
) -> None:
    frame = pd.DataFrame({"left": [10.0, 20.0], "right": [2.0, 4.0]})
    original = frame.copy(deep=True)
    schema = DatasetSchema(
        columns=("left", "right"),
        numeric_columns=frozenset({"left", "right"}),
        cardinalities={"left": 2, "right": 2},
    )
    workflow = _workflow(
        [
            _step(
                "S01",
                "derived_metric",
                {
                    "output_column": "derived",
                    "operator": operator,
                    "left": {"kind": "column", "column": "left"},
                    "right": {"kind": "column", "column": "right"},
                },
            ),
            _step("S02", "describe", {"target_columns": ["derived"]}, input_ref="S01"),
        ]
    )

    result = _execute(frame, workflow, schema)

    record = result.evidence_ledger.items[0].records[0]
    assert record["min"] == min(expected)
    assert record["max"] == max(expected)
    assert result.step_audits[0].operation == "derived_metric"
    assert result.step_audits[0].output_rows == len(frame)
    pd.testing.assert_frame_equal(frame, original)
    assert "derived" not in frame.columns


def test_derived_metric_division_by_zero_is_null_and_audited() -> None:
    frame = pd.DataFrame({"numerator": [10.0, 5.0], "denominator": [2.0, 0.0]})
    schema = DatasetSchema(
        columns=("numerator", "denominator"),
        numeric_columns=frozenset({"numerator", "denominator"}),
        cardinalities={"numerator": 2, "denominator": 2},
    )
    workflow = _workflow(
        [
            _step(
                "S01",
                "derived_metric",
                {
                    "output_column": "ratio",
                    "operator": "divide",
                    "left": {"kind": "column", "column": "numerator"},
                    "right": {"kind": "column", "column": "denominator"},
                },
            ),
            _step("S02", "describe", {"target_columns": ["ratio"]}, input_ref="S01"),
        ]
    )

    result = _execute(frame, workflow, schema)

    assert result.evidence_ledger.items[0].records[0]["count"] == 1
    assert result.evidence_ledger.items[0].records[0]["missing"] == 1
    assert result.step_audits[0].warnings == ["Set 1 division-by-zero result(s) to null."]


def test_derived_metric_rejects_non_numeric_column(
    frame: pd.DataFrame, dataset_schema: DatasetSchema
) -> None:
    workflow = _workflow(
        [
            _step(
                "S01",
                "derived_metric",
                {
                    "output_column": "invalid",
                    "operator": "multiply",
                    "left": {"kind": "column", "column": "note"},
                    "right": {"kind": "constant", "value": 2},
                },
            ),
            _step("S02", "describe", {"target_columns": ["invalid"]}, input_ref="S01"),
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="requires numeric columns"):
        _execute(frame, workflow, dataset_schema)
