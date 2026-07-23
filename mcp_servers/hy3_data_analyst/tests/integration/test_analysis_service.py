"""Integration tests for planning, repair, evidence, and interpretation."""

from pathlib import Path
from typing import Any

import pytest

from hy3_data_analyst_mcp.analysis.models import AnalysisPlan, EvidenceInterpretation
from hy3_data_analyst_mcp.analysis.planner import AnalysisPlanner
from hy3_data_analyst_mcp.analysis.service import AnalysisService
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.errors import Hy3ResponseError, InvalidAnalysisPlanError


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


async def test_analysis_service_passes_evidence_to_interpreter(
    settings: Settings, fixture_dir: Path
) -> None:
    client = StubClient(
        [
            AnalysisPlan(operation="missing_values", rationale="quality"),
            EvidenceInterpretation(
                conclusion="No values are missing.",
                evidence_references=["missing_count"],
                limitations=[],
            ),
        ]
    )
    result = await AnalysisService(settings, client=client).analyze(  # type: ignore[arg-type]
        "sales.csv", "Which fields are missing?", reasoning_effort="high"
    )
    assert result["status"] == "ok"
    assert result["evidence"]["operation"] == "missing_values"
    assert '"evidence"' in client.prompts[-1]
    assert str(fixture_dir) not in client.prompts[-1]
