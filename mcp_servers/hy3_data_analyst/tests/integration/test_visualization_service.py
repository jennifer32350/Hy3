"""Tests for structured and repaired visualization suggestions."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.models import ChartSuggestion, VisualizationSuggestions
from hy3_data_analyst_mcp.analysis.visualization import (
    VisualizationRenderService,
    VisualizationService,
)
from hy3_data_analyst_mcp.analysis.visualization_models import ChartSpec
from hy3_data_analyst_mcp.analysis.workflow_models import QualityPolicy
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import InvalidAnalysisPlanError


class StubClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls = 0
        self.prompts: list[str] = []
        self.response_models: list[type[Any]] = []

    async def complete_structured(self, **kwargs: Any) -> VisualizationSuggestions:
        self.calls += 1
        self.prompts.append(kwargs["user_prompt"])
        self.response_models.append(kwargs["response_model"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, VisualizationSuggestions)
        return response


def _suggestion(x: str, y: str = "revenue") -> VisualizationSuggestions:
    return VisualizationSuggestions(
        suggestions=[
            ChartSuggestion(
                chart_type="bar",
                title="Revenue by region",
                x=x,
                y=y,
                aggregation="sum",
                rationale="Compare regions.",
            )
        ]
    )


async def test_visualization_service_returns_validated_fields(settings: Settings) -> None:
    client = StubClient([_suggestion("region")])
    result = await VisualizationService(settings, client=client).suggest(  # type: ignore[arg-type]
        "sales.csv", "Compare revenue", max_suggestions=1
    )
    assert result["suggestions"][0]["x"] == "region"
    assert result["chart_evidence"][0]["evidence_id"] == "E01"
    assert result["chart_evidence"][0]["evidence"]["records"]
    assert client.calls == 1
    assert client.response_models == [VisualizationSuggestions]


async def test_visualization_service_repairs_invented_field(settings: Settings) -> None:
    client = StubClient([_suggestion("invented"), _suggestion("region")])
    result = await VisualizationService(settings, client=client).suggest(  # type: ignore[arg-type]
        "sales.csv", "Compare revenue", max_suggestions=1
    )
    assert result["suggestions"][0]["x"] == "region"
    assert client.calls == 2


async def test_visualization_service_fails_after_repair(settings: Settings) -> None:
    client = StubClient([_suggestion("bad"), _suggestion("still_bad")])
    with pytest.raises(InvalidAnalysisPlanError):
        await VisualizationService(settings, client=client).suggest(  # type: ignore[arg-type]
            "sales.csv", "Compare revenue", max_suggestions=1
        )


async def test_visualization_repair_receives_safe_schema_validation_detail(
    settings: Settings,
) -> None:
    try:
        ChartSuggestion.model_validate(
            {
                "chart_type": "pie",
                "title": "Invalid chart",
                "x": "region",
                "y": "revenue",
                "aggregation": "sum",
                "rationale": "Invalid chart type.",
            }
        )
    except ValidationError as validation_error:
        from hy3_data_analyst_mcp.errors import Hy3ResponseError

        schema_error = Hy3ResponseError("invalid structured output", "retry")
        schema_error.__cause__ = validation_error
    else:  # pragma: no cover - protects the test fixture itself
        raise AssertionError("invalid chart fixture unexpectedly passed validation")
    client = StubClient([schema_error, _suggestion("region")])

    result = await VisualizationService(settings, client=client).suggest(  # type: ignore[arg-type]
        "sales.csv", "Compare revenue", max_suggestions=1
    )

    assert result["suggestions"][0]["x"] == "region"
    assert "Input should be 'bar', 'line', 'scatter', 'histogram' or 'box'" in client.prompts[1]
    assert "input_value" not in client.prompts[1]


async def test_visualization_context_does_not_include_file_path(
    settings: Settings, fixture_dir: Path
) -> None:
    assert fixture_dir == settings.data_dir


async def test_render_reuses_returned_chart_spec_without_calling_hy3(
    settings: Settings,
) -> None:
    policy = QualityPolicy(missing="drop_referenced")
    planning_client = StubClient([_suggestion("region")])
    planned = await VisualizationService(
        settings,
        client=planning_client,  # type: ignore[arg-type]
    ).suggest(
        "sales.csv",
        "Compare revenue",
        max_suggestions=1,
        quality_policy=policy,
    )
    chart = ChartSpec.model_validate(planned["charts"][0])
    assert chart.data_plan.quality_policy == policy
    render_client = StubClient([])
    output_dir = Path(__file__).parents[2] / "local-output"
    output_dir.mkdir(exist_ok=True)
    render_settings = settings.model_copy(update={"output_dir": output_dir})

    rendered = await VisualizationRenderService(
        render_settings,
        client=render_client,  # type: ignore[arg-type]
    ).render(
        "sales.csv",
        "Reuse the validated chart",
        max_charts=1,
        width=800,
        height=480,
        chart_specs=[chart],
    )

    assert len(rendered) == 1
    assert rendered[0].output_path.exists()
    assert render_client.calls == 0
    rendered[0].output_path.unlink()
