"""Phase D deterministic quality-policy execution tests."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from hy3_data_analyst_mcp.analysis.quality import prepare_analysis_data
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.errors import DataQualityPolicyError


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-01", "bad-date", "2025-02-01"],
            "region": ["North", "North", "South", "South"],
            "amount": ["10", "10", "bad-number", None],
        }
    )


def _schema() -> DatasetSchema:
    return DatasetSchema(
        columns=("date", "region", "amount"),
        datetime_columns=frozenset({"date"}),
        cardinalities={"date": 3, "region": 2, "amount": 2},
    )


def _workflow(policy: dict[str, Any]) -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Apply explicit quality handling before a trend.",
            "primary_step_id": "S01",
            "quality_policy": policy,
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "time_trend",
                    "input_ref": "source",
                    "params": {
                        "time_column": "date",
                        "target_columns": ["amount"],
                        "aggregation": "sum",
                    },
                    "purpose": "Summarize converted values over time.",
                }
            ],
            "rationale": "Exercise quality policies deterministically.",
        }
    )


def test_drop_and_coerce_policies_have_exact_audits_without_source_mutation() -> None:
    source = _frame()
    original = source.copy(deep=True)
    workflow = _workflow(
        {
            "duplicates": "drop",
            "missing": "drop_referenced",
            "numeric_conversion": "coerce",
            "date_conversion": "coerce",
        }
    )

    prepared = prepare_analysis_data(source, workflow, _schema())

    assert len(prepared.frame) == 1
    assert prepared.frame.iloc[0]["amount"] == 10
    assert pd.api.types.is_datetime64_any_dtype(prepared.frame["date"])
    assert prepared.dataset_schema.numeric_columns == {"amount"}
    assert prepared.summary.model_dump(mode="json") == {
        "source_rows": 4,
        "analysis_base_rows": 1,
        "duplicate_rows_found": 1,
        "duplicate_rows_removed": 1,
        "referenced_rows_with_missing": 2,
        "rows_removed_for_missing": 2,
        "numeric_values_coerced_to_null": 1,
        "date_values_coerced_to_null": 1,
        "policies_applied": list(prepared.quality_actions),
        "source_modified": False,
    }
    pd.testing.assert_frame_equal(source, original)


def test_keep_policy_preserves_rows_while_recording_conversion_risk() -> None:
    workflow = _workflow(
        {
            "duplicates": "keep",
            "missing": "keep",
            "numeric_conversion": "coerce",
            "date_conversion": "coerce",
        }
    )

    prepared = prepare_analysis_data(_frame(), workflow, _schema())

    assert len(prepared.frame) == 4
    assert prepared.summary.duplicate_rows_found == 1
    assert prepared.summary.duplicate_rows_removed == 0
    assert prepared.summary.referenced_rows_with_missing == 2
    assert prepared.summary.rows_removed_for_missing == 0


def test_duplicate_error_policy_fails_before_analysis() -> None:
    with pytest.raises(DataQualityPolicyError, match="duplicates=error"):
        prepare_analysis_data(
            _frame(),
            _workflow(
                {
                    "duplicates": "error",
                    "numeric_conversion": "coerce",
                    "date_conversion": "coerce",
                }
            ),
            _schema(),
        )


def test_missing_error_policy_counts_post_conversion_nulls() -> None:
    with pytest.raises(DataQualityPolicyError, match="missing=error"):
        prepare_analysis_data(
            _frame(),
            _workflow(
                {
                    "missing": "error",
                    "numeric_conversion": "coerce",
                    "date_conversion": "coerce",
                }
            ),
            _schema(),
        )


def test_strict_numeric_conversion_rejects_invalid_related_values() -> None:
    with pytest.raises(DataQualityPolicyError, match="Numeric conversion failed"):
        prepare_analysis_data(
            _frame(),
            _workflow({"numeric_conversion": "strict", "date_conversion": "coerce"}),
            _schema(),
        )


def test_strict_date_conversion_rejects_invalid_related_values() -> None:
    with pytest.raises(DataQualityPolicyError, match="Date conversion failed"):
        prepare_analysis_data(
            _frame(),
            _workflow({"numeric_conversion": "coerce", "date_conversion": "strict"}),
            _schema(),
        )


def test_infinity_is_never_silently_preserved() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-02-01"],
            "region": ["North", "South"],
            "amount": [1.0, float("inf")],
        }
    )
    prepared = prepare_analysis_data(
        frame,
        _workflow({"numeric_conversion": "coerce", "date_conversion": "coerce"}),
        _schema(),
    )

    assert pd.isna(prepared.frame.iloc[1]["amount"])
    assert prepared.summary.numeric_values_coerced_to_null == 1
    assert prepared.summary.referenced_rows_with_missing == 1


def test_iso_filter_requests_date_coercion_even_when_profile_is_text() -> None:
    workflow = AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Filter an imperfect date column.",
            "primary_step_id": "S02",
            "quality_policy": {"date_conversion": "coerce"},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "filter_rows",
                    "input_ref": "source",
                    "params": {
                        "conditions": [
                            {
                                "column": "date",
                                "operator": "between",
                                "values": ["2025-01-01", "2025-12-31"],
                            }
                        ]
                    },
                    "purpose": "Use an explicit ISO date interval.",
                },
                {
                    "step_id": "S02",
                    "operation": "describe",
                    "input_ref": "S01",
                    "params": {"target_columns": ["amount"]},
                    "purpose": "Produce Evidence.",
                },
            ],
            "rationale": "Coerce only the referenced date column.",
        }
    )
    schema = DatasetSchema(
        columns=("date", "region", "amount"),
        cardinalities={"date": 3, "region": 2, "amount": 2},
    )

    prepared = prepare_analysis_data(_frame(), workflow, schema)

    assert prepared.summary.date_values_coerced_to_null == 1
    assert prepared.dataset_schema.datetime_columns == {"date"}


def test_policy_that_removes_every_row_fails_closed() -> None:
    frame = pd.DataFrame({"date": [None], "region": ["North"], "amount": [None]})
    with pytest.raises(DataQualityPolicyError, match="removed all analysis rows"):
        prepare_analysis_data(
            frame,
            _workflow(
                {
                    "missing": "drop_referenced",
                    "numeric_conversion": "coerce",
                    "date_conversion": "coerce",
                }
            ),
            _schema(),
        )


def test_phase_e_operations_participate_in_numeric_conversion_and_missing_policy() -> None:
    frame = pd.DataFrame(
        {
            "region": ["North", "South", "South"],
            "category": ["A", "A", "B"],
            "amount": ["10", "bad", None],
        }
    )
    schema = DatasetSchema(
        columns=("region", "category", "amount"),
        cardinalities={"region": 2, "category": 2, "amount": 2},
    )
    workflow = AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Build and analyze a safely converted metric.",
            "primary_step_id": "S02",
            "quality_policy": {
                "numeric_conversion": "coerce",
                "missing": "drop_referenced",
            },
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "derived_metric",
                    "input_ref": "source",
                    "params": {
                        "output_column": "amount_twice",
                        "operator": "multiply",
                        "left": {"kind": "column", "column": "amount"},
                        "right": {"kind": "constant", "value": 2},
                    },
                    "purpose": "Create an isolated numeric View.",
                },
                {
                    "step_id": "S02",
                    "operation": "distribution",
                    "input_ref": "S01",
                    "params": {"target_columns": ["amount_twice"], "bins": 5},
                    "purpose": "Summarize the derived metric.",
                },
            ],
            "rationale": "Verify Phase E quality-column tracking.",
        }
    )

    prepared = prepare_analysis_data(frame, workflow, schema)

    assert prepared.frame["amount"].tolist() == [10.0]
    assert "amount_twice" not in prepared.frame.columns
    assert prepared.summary.numeric_values_coerced_to_null == 1
    assert prepared.summary.referenced_rows_with_missing == 2


def test_pivot_non_count_metrics_are_numeric_quality_columns() -> None:
    frame = pd.DataFrame(
        {"region": ["North", "South"], "category": ["A", "B"], "amount": ["1", "bad"]}
    )
    schema = DatasetSchema(
        columns=("region", "category", "amount"),
        cardinalities={"region": 2, "category": 2, "amount": 2},
    )
    workflow = AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Pivot a text-backed numeric measure.",
            "primary_step_id": "S01",
            "quality_policy": {"numeric_conversion": "coerce"},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "pivot_table",
                    "input_ref": "source",
                    "params": {
                        "rows": ["region"],
                        "columns": ["category"],
                        "metrics": [{"column": "amount", "aggregation": "sum", "alias": "total"}],
                    },
                    "purpose": "Aggregate the converted values.",
                }
            ],
            "rationale": "Verify Pivot quality-column tracking.",
        }
    )

    prepared = prepare_analysis_data(frame, workflow, schema)

    assert prepared.frame["amount"].tolist()[0] == 1.0
    assert pd.isna(prepared.frame["amount"].tolist()[1])
    assert prepared.summary.numeric_values_coerced_to_null == 1
