"""Tests for immutable environment configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.config import TOKENHUB_BASE_URL, Settings, load_settings
from hy3_data_analyst_mcp.errors import ConfigurationError


def test_defaults_and_missing_api_key_allow_local_data(fixture_dir: Path) -> None:
    settings = load_settings({"HY3_DATA_DIR": str(fixture_dir)})

    assert settings.base_url == TOKENHUB_BASE_URL
    assert settings.model_name == "hy3"
    assert settings.api_key is None
    assert settings.data_dir.is_absolute()


def test_api_key_is_required_only_when_explicitly_requested(fixture_dir: Path) -> None:
    settings = load_settings({"HY3_DATA_DIR": str(fixture_dir)})

    with pytest.raises(ConfigurationError, match="HY3_API_KEY"):
        settings.require_api_key()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HY3_TIMEOUT_SECONDS", "0"),
        ("HY3_MAX_RETRIES", "-1"),
        ("HY3_MAX_FILE_SIZE_MB", "not-a-number"),
        ("HY3_MAX_ROWS", "0"),
        ("HY3_MAX_COLUMNS", "0"),
        ("HY3_MAX_WORKFLOW_STEPS", "7"),
        ("HY3_MAX_EVIDENCE_RECORDS_PER_STEP", "101"),
        ("HY3_MAX_EVIDENCE_RECORDS_TOTAL", "301"),
        ("HY3_MAX_CHARTS", "4"),
        ("HY3_MAX_CHART_FILE_SIZE_MB", "6"),
    ],
)
def test_invalid_numeric_values_become_project_errors(
    fixture_dir: Path,
    name: str,
    value: str,
) -> None:
    source = {"HY3_DATA_DIR": str(fixture_dir), name: value}

    with pytest.raises(ConfigurationError, match=name):
        load_settings(source)


def test_missing_data_directory_becomes_project_error(fixture_dir: Path) -> None:
    missing = fixture_dir / "missing"

    with pytest.raises(ConfigurationError, match="HY3_DATA_DIR"):
        load_settings({"HY3_DATA_DIR": str(missing)})


def test_relative_data_directory_is_resolved(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: Path
) -> None:
    monkeypatch.chdir(fixture_dir.parent)

    settings = load_settings({"HY3_DATA_DIR": "fixtures"})

    assert settings.data_dir == fixture_dir.resolve()


def test_settings_are_immutable(fixture_dir: Path) -> None:
    settings = Settings(data_dir=fixture_dir)

    with pytest.raises(ValidationError):
        settings.max_rows = 1


def test_phase_c_resource_settings_can_only_lower_hard_limits(fixture_dir: Path) -> None:
    settings = load_settings(
        {
            "HY3_DATA_DIR": str(fixture_dir),
            "HY3_MAX_WORKFLOW_STEPS": "4",
            "HY3_MAX_EVIDENCE_RECORDS_PER_STEP": "25",
            "HY3_MAX_EVIDENCE_RECORDS_TOTAL": "75",
        }
    )

    assert settings.max_workflow_steps == 4
    assert settings.max_evidence_records_per_step == 25
    assert settings.max_evidence_records_total == 75


def test_chart_settings_are_optional_until_rendering(fixture_dir: Path) -> None:
    settings = load_settings({"HY3_DATA_DIR": str(fixture_dir)})

    assert settings.output_dir is None
    assert settings.max_charts == 3
    assert settings.max_chart_file_size_mb == 5
    with pytest.raises(ConfigurationError, match="HY3_OUTPUT_DIR"):
        settings.require_output_dir()


def test_chart_output_directory_is_resolved(fixture_dir: Path) -> None:
    settings = load_settings(
        {
            "HY3_DATA_DIR": str(fixture_dir),
            "HY3_OUTPUT_DIR": str(fixture_dir),
            "HY3_MAX_CHARTS": "2",
            "HY3_MAX_CHART_FILE_SIZE_MB": "4",
        }
    )

    assert settings.require_output_dir() == fixture_dir.resolve()
    assert settings.max_charts == 2
    assert settings.max_chart_file_size_mb == 4


@pytest.mark.parametrize("output_dir", [r"\\server\share", "https://example.com/output"])
def test_chart_output_directory_rejects_remote_locations(
    fixture_dir: Path, output_dir: str
) -> None:
    with pytest.raises(ConfigurationError, match="HY3_OUTPUT_DIR"):
        load_settings(
            {
                "HY3_DATA_DIR": str(fixture_dir),
                "HY3_OUTPUT_DIR": output_dir,
            }
        )
