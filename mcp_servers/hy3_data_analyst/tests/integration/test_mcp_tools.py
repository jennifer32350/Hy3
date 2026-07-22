"""Protocol-level tests for the phase A MCP surface."""

from pathlib import Path

import pytest

from hy3_data_analyst_mcp.server import mcp
from hy3_data_analyst_mcp.tools.inspect_dataset import inspect_dataset


async def test_tools_list_exposes_exactly_the_three_public_tools() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == {
        "analyze_dataset",
        "inspect_dataset",
        "suggest_visualization",
    }
    assert all(tool.description for tool in tools)
    assert all(tool.inputSchema for tool in tools)


async def test_inspect_dataset_works_without_api_key(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: Path
) -> None:
    monkeypatch.setenv("HY3_DATA_DIR", str(fixture_dir))
    monkeypatch.delenv("HY3_API_KEY", raising=False)

    result = await inspect_dataset("sales.csv", sample_rows=1)

    assert result["row_count"] == 2
    assert result["column_names"] == ["date", "region", "revenue"]
    assert len(result["sample_rows"]) == 1


async def test_inspect_dataset_returns_readable_argument_error() -> None:
    result = await inspect_dataset("sales.csv", sample_rows=21)

    assert result["error"] == "InvalidToolArgument"
    assert "between 0 and 20" in result["message"]
