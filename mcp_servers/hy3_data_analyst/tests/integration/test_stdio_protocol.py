"""Subprocess stdio handshake for the installed module entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio_initialize_and_list_exactly_four_tools(fixture_dir: Path) -> None:
    environment = {key: value for key, value in os.environ.items() if key != "HY3_API_KEY"}
    environment["HY3_DATA_DIR"] = str(fixture_dir)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hy3_data_analyst_mcp"],
        env=environment,
    )

    try:
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialized = await session.initialize()
            listed = await session.list_tools()
    except PermissionError:
        pytest.skip("Windows named pipes are unavailable in this sandbox")

    assert initialized.serverInfo.name == "Hy3 Data Analyst"
    assert {tool.name for tool in listed.tools} == {
        "analyze_dataset",
        "inspect_dataset",
        "render_visualization",
        "suggest_visualization",
    }
    assert all(tool.description for tool in listed.tools)
    assert all(tool.inputSchema for tool in listed.tools)
