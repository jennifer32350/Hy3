"""Integration tests for planning, repair, evidence, and interpretation."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.models import AnalysisPlan
from hy3_data_analyst_mcp.analysis.planner import AnalysisPlanner
from hy3_data_analyst_mcp.analysis.report_models import AnalysisReport
from hy3_data_analyst_mcp.analysis.service import AnalysisService
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow, QualityPolicy
from hy3_data_analyst_mcp.analysis.workflow_planner import WorkflowPlanner
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    InvalidAnalysisPlanError,
    InvalidAnalysisReportError,
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


def _workflow(
    *,
    invented: bool = False,
    policy: dict[str, Any] | None = None,
) -> AnalysisWorkflow:
    revenue = "invented" if invented else "revenue"
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Filter and compare regional revenue.",
            "primary_step_id": "S02",
            "quality_policy": policy or {},
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


def _business_workflow(*, policy: dict[str, Any] | None = None) -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Compare regional performance, periods, and profit outliers.",
            "primary_step_id": "S01",
            "quality_policy": policy or {},
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


def _report(*, evidence_ids: list[str] | None = None) -> AnalysisReport:
    ids = evidence_ids or ["E01"]
    return AnalysisReport.model_validate(
        {
            "executive_summary": "South revenue is 120 and North revenue is 100.",
            "findings": [
                {
                    "finding_id": "F01",
                    "kind": "fact",
                    "title": "Regional revenue",
                    "statement": "South revenue is 120 and North revenue is 100.",
                    "evidence_ids": ids,
                    "confidence": "high",
                }
            ],
            "anomalies": [],
            "recommendations": [],
            "data_scope": {
                "source_file_name": "sales.csv",
                "source_rows": 2,
                "used_rows": 2,
                "excluded_rows": 0,
                "referenced_columns": ["region", "revenue"],
                "filters_applied": [],
                "time_grain": None,
                "notes": [],
            },
            "limitations": [],
            "warnings": [],
            "suggested_follow_ups": ["Compare shares."],
        }
    )


def _business_report() -> AnalysisReport:
    return AnalysisReport.model_validate(
        {
            "executive_summary": "Regional totals, profit outliers, and periods were compared.",
            "findings": [
                {
                    "finding_id": "F01",
                    "kind": "fact",
                    "title": "North totals",
                    "statement": "North revenue is 8,600 and profit is 4,200.",
                    "evidence_ids": ["E01"],
                    "confidence": "medium",
                },
                {
                    "finding_id": "F02",
                    "kind": "fact",
                    "title": "Period totals",
                    "statement": "Revenue changed from 15,300 to 6,950.",
                    "evidence_ids": ["E03"],
                    "confidence": "medium",
                },
            ],
            "anomalies": [
                {
                    "finding_id": "F03",
                    "kind": "risk",
                    "title": "Profit outliers",
                    "statement": "There are 4 profit outliers, including source row 11.",
                    "evidence_ids": ["E02"],
                    "confidence": "medium",
                }
            ],
            "recommendations": [],
            "data_scope": {
                "source_file_name": "sales.csv",
                "source_rows": 18,
                "used_rows": 18,
                "excluded_rows": 0,
                "referenced_columns": ["date", "region", "revenue", "profit"],
                "filters_applied": [],
                "time_grain": "year",
                "notes": [],
            },
            "limitations": [],
            "warnings": [],
            "suggested_follow_ups": ["Review the duplicate row."],
        }
    )


def _top_workflow() -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Rank revenue records.",
            "primary_step_id": "S01",
            "quality_policy": {},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "top_k",
                    "input_ref": "source",
                    "params": {"target_columns": ["revenue"], "limit": 100},
                    "purpose": "Rank all bounded revenue records.",
                }
            ],
            "rationale": "Use stable deterministic sorting.",
        }
    )


def _top_report() -> AnalysisReport:
    payload = _report().model_dump(mode="json")
    payload["executive_summary"] = "Revenue records were ranked deterministically."
    payload["findings"][0].update(
        title="Revenue ranking",
        statement="Revenue records were ranked deterministically.",
        confidence="medium",
    )
    return AnalysisReport.model_validate(payload)


def _quality_report() -> AnalysisReport:
    payload = _business_report().model_dump(mode="json")
    payload["executive_summary"] = "Quality-adjusted regional analysis completed."
    payload["findings"] = [
        {
            "finding_id": "F01",
            "kind": "fact",
            "title": "Regional aggregation",
            "statement": "Regional revenue and profit were aggregated deterministically.",
            "evidence_ids": ["E01"],
            "confidence": "medium",
        }
    ]
    payload["anomalies"] = []
    return AnalysisReport.model_validate(payload)


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
        quality_policy=QualityPolicy(),
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
            quality_policy=QualityPolicy(),
        )

    assert len(client.prompts) == 2


async def test_workflow_repair_receives_safe_schema_validation_detail(
    settings: Settings, fixture_dir: Path
) -> None:
    invalid_payload = _workflow().model_dump(mode="json")
    invalid_payload["primary_step_id"] = "S01"
    try:
        AnalysisWorkflow.model_validate(invalid_payload)
    except ValidationError as validation_error:
        schema_error = Hy3ResponseError("invalid structured output", "retry")
        schema_error.__cause__ = validation_error
    else:  # pragma: no cover - protects the test fixture itself
        raise AssertionError("invalid workflow fixture unexpectedly passed validation")
    client = StubClient([schema_error, _workflow()])

    workflow = await WorkflowPlanner(client).create_workflow(  # type: ignore[arg-type]
        "Compare regions",
        _profile(settings, fixture_dir),
        reasoning_effort="low",
        max_steps=3,
        quality_policy=QualityPolicy(),
    )

    assert workflow.primary_step_id == "S02"
    assert "primary_step_id must reference an Evidence-producing step" in client.prompts[1]
    assert "input_value" not in client.prompts[1]


async def test_workflow_planner_repairs_mismatched_requested_quality_policy(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    requested = QualityPolicy(duplicates="drop")
    client = StubClient([_workflow(), _workflow(policy={"duplicates": "drop"})])

    workflow = await WorkflowPlanner(client).create_workflow(  # type: ignore[arg-type]
        "Compare regions",
        _profile(settings, fixture_dir),
        reasoning_effort="high",
        max_steps=3,
        quality_policy=requested,
    )

    assert workflow.quality_policy == requested
    assert len(client.prompts) == 2


async def test_analysis_service_passes_evidence_to_reporter(
    settings: Settings, fixture_dir: Path
) -> None:
    client = StubClient(
        [
            _workflow(),
            _report(),
        ]
    )
    result = await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
        "sales.csv", "Compare regional revenue.", reasoning_effort="high", max_steps=3
    )
    assert result["status"] == "ok"
    assert result["plan"]["operation"] == "multi_aggregate"
    assert result["evidence"]["operation"] == "multi_aggregate"
    assert result["workflow"]["primary_step_id"] == "S02"
    assert result["report"]["executive_summary"] == result["conclusion"]
    assert result["evidence_references"] == ["E01"]
    assert result["quality_summary"]["source_modified"] is False
    assert len(result["evidence_ledger"]["items"][0]["lineage"]["quality_actions"]) == 4
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


async def test_analysis_service_repairs_then_rejects_unknown_evidence_id(
    settings: Settings,
) -> None:
    client = StubClient(
        [
            _workflow(),
            _report(evidence_ids=["E09"]),
            _report(evidence_ids=["E09"]),
        ]
    )

    with pytest.raises(InvalidAnalysisReportError, match="grounded report"):
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
            _business_report(),
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
    assert result["quality_summary"]["duplicate_rows_found"] == 1
    assert result["quality_summary"]["referenced_rows_with_missing"] == 1
    assert any("duplicate" in warning for warning in result["report"]["warnings"])


async def test_analysis_service_applies_requested_policy_without_modifying_source(
    fixture_dir: Path,
) -> None:
    eval_data_dir = fixture_dir.parent.parent / "evals" / "data"
    source_path = eval_data_dir / "sales.csv"
    original_bytes = source_path.read_bytes()
    settings = Settings(data_dir=eval_data_dir)
    policy = QualityPolicy(duplicates="drop")
    client = StubClient(
        [
            _business_workflow(policy={"duplicates": "drop"}),
            _quality_report(),
        ]
    )

    result = await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
        "sales.csv",
        "Run a quality-adjusted analysis.",
        reasoning_effort="high",
        quality_policy=policy,
    )

    summary = result["quality_summary"]
    assert summary["source_rows"] == 18
    assert summary["analysis_base_rows"] == 17
    assert summary["duplicate_rows_removed"] == 1
    assert summary["source_modified"] is False
    assert result["evidence_ledger"]["items"][0]["source_rows"] == 17
    assert source_path.read_bytes() == original_bytes


async def test_concise_mode_limits_presentation_without_changing_calculation(
    fixture_dir: Path,
) -> None:
    eval_data_dir = fixture_dir.parent.parent / "evals" / "data"
    settings = Settings(data_dir=eval_data_dir)
    detailed = await AnalysisService(
        settings,
        client=StubClient([_top_workflow(), _top_report()]),  # type: ignore[arg-type]
    ).analyze(
        "sales.csv",
        "Rank revenue records.",
        reasoning_effort="high",
        output_mode="detailed",
    )
    concise = await AnalysisService(
        settings,
        client=StubClient([_top_workflow(), _top_report()]),  # type: ignore[arg-type]
    ).analyze(
        "sales.csv",
        "Rank revenue records.",
        reasoning_effort="high",
        output_mode="concise",
    )

    detailed_item = detailed["evidence_ledger"]["items"][0]
    concise_item = concise["evidence_ledger"]["items"][0]
    assert len(detailed_item["records"]) == 18
    assert len(concise_item["records"]) == 5
    assert concise_item["truncated"] is True
    assert concise_item["metrics"] == detailed_item["metrics"]
    assert concise["report"] == detailed["report"]
