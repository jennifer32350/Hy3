"""Tests for structured and repaired visualization suggestions."""

from pathlib import Path
from typing import Any

import pytest

from hy3_data_analyst_mcp.analysis.models import ChartSuggestion, VisualizationSuggestions
from hy3_data_analyst_mcp.analysis.visualization import VisualizationService
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import InvalidAnalysisPlanError


class StubClient:
    def __init__(self, responses: list[VisualizationSuggestions]) -> None:
        self.responses = responses
        self.calls = 0

    async def complete_structured(self, **kwargs: Any) -> VisualizationSuggestions:
        del kwargs
        self.calls += 1
        return self.responses.pop(0)


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
    assert client.calls == 1


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


async def test_visualization_context_does_not_include_file_path(
    settings: Settings, fixture_dir: Path
) -> None:
    assert fixture_dir == settings.data_dir
