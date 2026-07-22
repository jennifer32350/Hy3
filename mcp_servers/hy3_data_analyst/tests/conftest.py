"""Shared fixtures for Hy3 Data Analyst MCP tests."""

from pathlib import Path

import pytest

from hy3_data_analyst_mcp.config import Settings


@pytest.fixture
def fixture_dir() -> Path:
    """Return the committed safe dataset fixture directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(fixture_dir: Path) -> Settings:
    """Return settings that permit access only to committed fixtures."""
    return Settings(data_dir=fixture_dir)
