"""Integration coverage for Phase E quality, validation, Views, and Evidence."""

from __future__ import annotations

import pandas as pd

from hy3_data_analyst_mcp.analysis.quality import prepare_analysis_data
from hy3_data_analyst_mcp.analysis.workflow_executor import execute_workflow
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema, validate_workflow


def test_derived_distribution_and_pivot_execute_as_one_validated_workflow() -> None:
    source = pd.DataFrame(
        {
            "region": ["East", "East", "West", "West"],
            "category": ["A", "B", "A", "B"],
            "revenue": [100.0, 150.0, 80.0, 120.0],
            "cost": [50.0, 100.0, 40.0, 0.0],
        }
    )
    original = source.copy(deep=True)
    schema = DatasetSchema(
        columns=("region", "category", "revenue", "cost"),
        numeric_columns=frozenset({"revenue", "cost"}),
        cardinalities={"region": 2, "category": 2, "revenue": 4, "cost": 4},
    )
    workflow = AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Analyze a derived revenue-to-cost ratio by segment.",
            "primary_step_id": "S03",
            "quality_policy": {},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "derived_metric",
                    "input_ref": "source",
                    "params": {
                        "output_column": "revenue_cost_ratio",
                        "operator": "divide",
                        "left": {"kind": "column", "column": "revenue"},
                        "right": {"kind": "column", "column": "cost"},
                    },
                    "purpose": "Create a safe ratio View.",
                },
                {
                    "step_id": "S02",
                    "operation": "distribution",
                    "input_ref": "S01",
                    "params": {"target_columns": ["revenue_cost_ratio"], "bins": 5},
                    "purpose": "Measure the ratio distribution.",
                },
                {
                    "step_id": "S03",
                    "operation": "pivot_table",
                    "input_ref": "S01",
                    "params": {
                        "rows": ["region"],
                        "columns": ["category"],
                        "metrics": [
                            {
                                "column": "revenue_cost_ratio",
                                "aggregation": "mean",
                                "alias": "mean_ratio",
                            }
                        ],
                        "fill_value": 0.0,
                    },
                    "purpose": "Compare mean ratios across segments.",
                },
            ],
            "rationale": "Exercise a View and two Evidence operations together.",
        }
    )

    validate_workflow(workflow, schema)
    prepared = prepare_analysis_data(source, workflow, schema)
    result = execute_workflow(
        prepared.frame,
        workflow,
        source_file_name="segments.csv",
        dataset_schema=prepared.dataset_schema,
        quality_actions=prepared.quality_actions,
    )

    assert [item.operation for item in result.evidence_ledger.items] == [
        "distribution",
        "pivot_table",
    ]
    assert result.evidence_ledger.items[0].records[0]["count"] == 3
    assert result.evidence_ledger.items[1].metrics["actual_cells"] == 4
    assert result.step_audits[0].warnings == ["Set 1 division-by-zero result(s) to null."]
    pd.testing.assert_frame_equal(source, original)
    assert "revenue_cost_ratio" not in source.columns
