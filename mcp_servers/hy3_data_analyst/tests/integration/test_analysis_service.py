"""Integration tests for planning, repair, evidence, and interpretation."""

from pathlib import Path
from typing import Any

import pytest

from hy3_data_analyst_mcp.analysis.models import AnalysisPlan, EvidenceInterpretation
from hy3_data_analyst_mcp.analysis.planner import AnalysisPlanner
from hy3_data_analyst_mcp.analysis.service import AnalysisService
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_planner import WorkflowPlanner
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    InvalidAnalysisPlanError,
    InvalidAnalysisWorkflowError,
)


class StubClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def complete_structured(self, **kwargs: Any) -> Any:
        self.prompts.append(kwargs["user_prompt"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _profile(settings: Settings, fixture_dir: Path):  # type: ignore[no-untyped-def]
    path = fixture_dir / "sales.csv"
    return profile_dataset(load_dataset(path, settings=settings), source_path=path)


def _workflow(*, invented: bool = False) -> AnalysisWorkflow:
    revenue = "invented" if invented else "revenue"
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Filter and compare regional revenue.",
            "primary_step_id": "S02",
            "quality_policy": {},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "filter_rows",
                    "input_ref": "source",
                    "params": {
                        "conditions": [{"column": "revenue", "operator": "gte", "value": 100}]
                    },
                    "purpose": "Keep qualifying rows.",
                },
                {
                    "step_id": "S02",
                    "operation": "multi_aggregate",
                    "input_ref": "S01",
                    "params": {
                        "group_by": ["region"],
                        "metrics": [
                            {
                                "column": revenue,
                                "aggregation": "sum",
                                "alias": "revenue_sum",
                            }
                        ],
                        "sort_by": "revenue_sum",
                    },
                    "purpose": "Compare regional revenue.",
                },
                {
                    "step_id": "S03",
                    "operation": "value_counts",
                    "input_ref": "S01",
                    "params": {"column": "region", "normalize": True},
                    "purpose": "Measure region shares.",
                },
            ],
            "rationale": "Use three deterministic steps.",
        }
    )


def _business_workflow() -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Compare regional performance, periods, and profit outliers.",
            "primary_step_id": "S01",
            "quality_policy": {},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "multi_aggregate",
                    "input_ref": "source",
                    "params": {
                        "group_by": ["region"],
                        "metrics": [
                            {
                                "column": "revenue",
                                "aggregation": "sum",
                                "alias": "revenue_sum",
                            },
                            {
                                "column": "profit",
                                "aggregation": "sum",
                                "alias": "profit_sum",
                            },
                        ],
                        "sort_by": "revenue_sum",
                    },
                    "purpose": "Rank regional revenue and profit.",
                },
                {
                    "step_id": "S02",
                    "operation": "outlier_iqr",
                    "input_ref": "source",
                    "params": {"target_columns": ["profit"]},
                    "purpose": "Locate profit outliers.",
                },
                {
                    "step_id": "S03",
                    "operation": "period_compare",
                    "input_ref": "source",
                    "params": {
                        "time_column": "date",
                        "target_columns": ["revenue", "profit"],
                        "aggregation": "sum",
                        "grain": "year",
                        "comparison": "explicit",
                        "period_a": {"start": "2025-01-01", "end": "2025-06-30"},
                        "period_b": {"start": "2025-07-01", "end": "2025-09-30"},
                    },
                    "purpose": "Compare first- and second-half-to-date performance.",
                },
            ],
            "rationale": "Use three independent deterministic calculations.",
        }
    )


async def test_planner_repairs_invented_column(settings: Settings, fixture_dir: Path) -> None:
    client = StubClient(
        [
            AnalysisPlan(operation="top_k", target_columns=["invented"], rationale="bad"),
            AnalysisPlan(operation="top_k", target_columns=["revenue"], rationale="fixed"),
        ]
    )
    plan = await AnalysisPlanner(client).create_plan(  # type: ignore[arg-type]
        "top revenue", _profile(settings, fixture_dir), reasoning_effort="high"
    )
    assert plan.target_columns == ["revenue"]
    assert len(client.prompts) == 2


async def test_planner_fails_after_one_repair(settings: Settings, fixture_dir: Path) -> None:
    error = Hy3ResponseError("invalid", "retry")
    client = StubClient([error, error])
    with pytest.raises(InvalidAnalysisPlanError):
        await AnalysisPlanner(client).create_plan(  # type: ignore[arg-type]
            "question", _profile(settings, fixture_dir), reasoning_effort="low"
        )


async def test_workflow_planner_repairs_invalid_columns_once(
    settings: Settings, fixture_dir: Path
) -> None:
    client = StubClient([_workflow(invented=True), _workflow()])

    workflow = await WorkflowPlanner(client).create_workflow(  # type: ignore[arg-type]
        "Compare regions",
        _profile(settings, fixture_dir),
        reasoning_effort="high",
        max_steps=3,
    )

    assert workflow.steps[1].operation == "multi_aggregate"
    assert len(client.prompts) == 2
    assert str(fixture_dir) not in client.prompts[-1]


async def test_workflow_planner_fails_after_exactly_one_repair(
    settings: Settings, fixture_dir: Path
) -> None:
    client = StubClient([_workflow(invented=True), _workflow(invented=True)])

    with pytest.raises(InvalidAnalysisWorkflowError):
        await WorkflowPlanner(client).create_workflow(  # type: ignore[arg-type]
            "Compare regions",
            _profile(settings, fixture_dir),
            reasoning_effort="low",
            max_steps=3,
        )

    assert len(client.prompts) == 2


async def test_analysis_service_passes_evidence_to_interpreter(
    settings: Settings, fixture_dir: Path
) -> None:
    client = StubClient(
        [
            _workflow(),
            EvidenceInterpretation(
                conclusion="North has 100 revenue and South has 120.",
                evidence_references=["E01", "E02"],
                limitations=[],
            ),
        ]
    )
    result = await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
        "sales.csv", "Compare regional revenue.", reasoning_effort="high", max_steps=3
    )
    assert result["status"] == "ok"
    assert result["plan"]["operation"] == "multi_aggregate"
    assert result["evidence"]["operation"] == "multi_aggregate"
    assert result["workflow"]["primary_step_id"] == "S02"
    assert [item["evidence_id"] for item in result["evidence_ledger"]["items"]] == [
        "E01",
        "E02",
    ]
    assert result["evidence"]["records"] == [
        {"region": "South", "revenue_sum": 120},
        {"region": "North", "revenue_sum": 100},
    ]
    assert set(result["step_timings_ms"]) == {"S01", "S02", "S03"}
    assert '"evidence_ledger"' in client.prompts[-1]
    assert str(fixture_dir) not in client.prompts[-1]


async def test_analysis_service_rejects_interpreter_unknown_evidence_id(
    settings: Settings,
) -> None:
    client = StubClient(
        [
            _workflow(),
            EvidenceInterpretation(
                conclusion="Unsupported claim.",
                evidence_references=["E99"],
                limitations=[],
            ),
        ]
    )

    with pytest.raises(Hy3ResponseError, match="invalid Evidence references"):
        await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
            "sales.csv", "Compare regional revenue.", reasoning_effort="high", max_steps=3
        )


async def test_comprehensive_business_analysis_executes_three_exact_steps(
    fixture_dir: Path,
) -> None:
    eval_data_dir = fixture_dir.parent.parent / "evals" / "data"
    settings = Settings(data_dir=eval_data_dir)
    client = StubClient(
        [
            _business_workflow(),
            EvidenceInterpretation(
                conclusion="Regional totals, the profit outlier, and period changes were computed.",
                evidence_references=["E01", "E02", "E03"],
                limitations=[],
            ),
        ]
    )

    result = await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
        "sales.csv", "Run a comprehensive business analysis.", reasoning_effort="high"
    )

    assert len(result["workflow"]["steps"]) == 3
    regional = {
        record["region"]: record for record in result["evidence_ledger"]["items"][0]["records"]
    }
    assert regional["North"] == {
        "region": "North",
        "revenue_sum": 8600.0,
        "profit_sum": 4200.0,
    }
    assert regional["West"] == {
        "region": "West",
        "revenue_sum": 4400.0,
        "profit_sum": 1270.0,
    }
    outlier = result["evidence_ledger"]["items"][1]["records"][0]
    assert outlier["outlier_count"] == 4
    assert 11 in outlier["source_row_numbers"]
    periods = {
        record["target_column"]: record
        for record in result["evidence_ledger"]["items"][2]["records"]
    }
    assert periods["revenue"]["period_a_value"] == 15300.0
    assert periods["revenue"]["period_b_value"] == 6950.0
