"""MCP content protocol tests for rendered charts."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from mcp.types import ImageContent, TextContent

from hy3_data_analyst_mcp.analysis.visualization import VisualizationRenderService
from hy3_data_analyst_mcp.analysis.visualization_executor import ChartExecution
from hy3_data_analyst_mcp.tools import render_visualization as render_module


async def test_render_tool_returns_metadata_then_png_content(
    monkeypatch: pytest.MonkeyPatch,
    fixture_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tmp_path = fixture_dir
    png = b"\x89PNG\r\n\x1a\ncontent"

    async def fake_render(*args: object, **kwargs: object) -> list[ChartExecution]:
        del args, kwargs
        return [
            ChartExecution(
                png=png,
                output_path=tmp_path / "chart.png",
                evidence={"evidence_id": "E01", "records": [{"x": 1, "y": 2}]},
                quality={"visualization": {"plotted_records": 1}},
            )
        ]

    monkeypatch.setenv("HY3_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HY3_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(VisualizationRenderService, "render", fake_render)

    result = await render_module.render_visualization("data.csv", "Show data")

    assert len(result) == 2
    assert isinstance(result[0], TextContent)
    assert isinstance(result[1], ImageContent)
    metadata = json.loads(result[0].text)
    assert metadata["mime_type"] == "image/png"
    assert metadata["evidence"]["records"] == [{"x": 1, "y": 2}]
    assert result[1].mimeType == "image/png"
    assert base64.b64decode(result[1].data) == png
    assert capsys.readouterr().out == ""


async def test_render_tool_reports_missing_output_configuration(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: Path
) -> None:
    tmp_path = fixture_dir
    monkeypatch.setenv("HY3_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HY3_OUTPUT_DIR", raising=False)

    result = await render_module.render_visualization("data.csv", "Show data")

    assert isinstance(result[0], TextContent)
    assert json.loads(result[0].text)["error"] == "ConfigurationError"
