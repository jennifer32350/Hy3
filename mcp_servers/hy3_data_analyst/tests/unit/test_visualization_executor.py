"""Deterministic rendering and safe-output tests for Phase F."""

from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from hy3_data_analyst_mcp.analysis.visualization_executor import (
    execute_chart_data,
    render_chart,
    write_chart_png,
)
from hy3_data_analyst_mcp.analysis.visualization_models import ChartSpec, ChartType
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow, QualityPolicy
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.errors import (
    ConfigurationError,
    OutputAccessDeniedError,
    VisualizationRenderError,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category": ["A", "B", "A", "C"],
            "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "x_value": [1.0, 2.0, 3.0, 4.0],
            "y_value": [4.0, 3.0, 2.0, 1.0],
        }
    )


def _spec(chart_type: ChartType) -> ChartSpec:
    if chart_type == "bar":
        x, y = "category", "y_value"
    elif chart_type == "line":
        x, y = "date", "y_value"
    elif chart_type == "scatter":
        x, y = "x_value", "y_value"
    elif chart_type == "histogram":
        x, y = None, "y_value"
    else:
        x, y = "category", "y_value"
    selected = list(dict.fromkeys(field for field in (y, x) if field is not None))
    workflow = AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Prepare deterministic chart data.",
            "primary_step_id": "S01",
            "quality_policy": QualityPolicy().model_dump(mode="json"),
            "steps": [
                {
                    "step_id": "S01",
                    "input_ref": "source",
                    "purpose": "Select bounded chart fields.",
                    "operation": "top_k",
                    "params": {
                        "target_columns": selected,
                        "group_by": [],
                        "sort_order": "desc",
                        "limit": 100,
                    },
                }
            ],
            "rationale": "Use a safe local operation.",
        }
    )
    return ChartSpec(
        chart_type=chart_type,
        title=f"{chart_type} test",
        x=x,
        y=y,
        rationale="Test all supported renderers.",
        data_plan=workflow,
    )


@pytest.mark.parametrize("chart_type", ["bar", "line", "scatter", "histogram", "box"])
def test_all_chart_types_render_exact_png_dimensions(
    chart_type: ChartType, fixture_dir: Path
) -> None:
    tmp_path = fixture_dir
    frame = _frame()
    source = tmp_path / "sales.csv"
    profile = profile_dataset(frame, source_path=source, sample_rows=0)
    settings = Settings(data_dir=tmp_path, output_dir=tmp_path)
    spec = _spec(chart_type)

    evidence, quality = execute_chart_data(frame, profile, source, spec, settings)
    png = render_chart(spec, evidence, width=640, height=480)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 100
    assert int.from_bytes(png[16:20], "big") == 640
    assert int.from_bytes(png[20:24], "big") == 480
    assert quality["visualization"]["plotted_records"] == len(evidence["records"])


def test_sampling_metadata_does_not_double_count_invalid_records(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: Path
) -> None:
    monkeypatch.setattr(
        "hy3_data_analyst_mcp.analysis.visualization_executor.MAX_POINTS",
        2,
    )
    frame = _frame()
    frame.loc[1, "y_value"] = None
    source = fixture_dir / "sales.csv"
    profile = profile_dataset(frame, source_path=source, sample_rows=0)
    settings = Settings(data_dir=fixture_dir, output_dir=fixture_dir)

    evidence, quality = execute_chart_data(frame, profile, source, _spec("line"), settings)

    assert len(evidence["records"]) == 2
    assert quality["visualization"]["missing_records_removed"] == 1
    assert quality["visualization"]["sampled_records_removed"] == 1


def test_category_policy_collapses_to_thirty_plus_other(
    fixture_dir: Path,
) -> None:
    tmp_path = fixture_dir
    frame = pd.DataFrame({"category": [f"C{i:02d}" for i in range(40)], "y_value": list(range(40))})
    source = tmp_path / "sales.csv"
    profile = profile_dataset(frame, source_path=source, sample_rows=0)
    settings = Settings(data_dir=tmp_path, output_dir=tmp_path)

    evidence, quality = execute_chart_data(frame, profile, source, _spec("bar"), settings)

    assert len({row["category"] for row in evidence["records"]}) == 31
    assert any(row["category"] == "Other" for row in evidence["records"])
    assert quality["visualization"]["categories_collapsed"] == 10


def test_output_requires_configuration(fixture_dir: Path) -> None:
    tmp_path = fixture_dir
    with pytest.raises(ConfigurationError):
        write_chart_png(b"\x89PNG\r\n\x1a\nbody", Settings(data_dir=tmp_path))


def test_output_is_exclusively_written_inside_configured_root(fixture_dir: Path) -> None:
    payload = b"\x89PNG\r\n\x1a\nbody"
    output = write_chart_png(
        payload,
        Settings(data_dir=fixture_dir, output_dir=fixture_dir),
    )
    try:
        assert output.parent == fixture_dir.resolve()
        assert output.suffix == ".png"
        assert output.read_bytes() == payload
        uuid.UUID(output.stem)
    finally:
        output.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("width", "height"),
    [(479, 720), (1921, 720), (1200, 319), (1200, 1081)],
)
def test_renderer_rejects_dimensions_outside_specification(width: int, height: int) -> None:
    with pytest.raises(VisualizationRenderError, match="dimensions"):
        render_chart(
            _spec("bar"),
            {"records": [{"category": "A", "y_value": 1.0}]},
            width=width,
            height=height,
        )


def test_output_uses_uuid_and_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: Path
) -> None:
    tmp_path = fixture_dir
    identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
    target = tmp_path / f"{identifier}.png"
    target.write_bytes(b"original")
    monkeypatch.setattr(
        "hy3_data_analyst_mcp.analysis.visualization_executor.uuid.uuid4",
        lambda: identifier,
    )

    with pytest.raises(OutputAccessDeniedError):
        write_chart_png(b"\x89PNG\r\n\x1a\nbody", Settings(data_dir=tmp_path, output_dir=tmp_path))
    assert target.read_bytes() == b"original"
    target.unlink()


def test_output_size_is_checked_before_write(fixture_dir: Path) -> None:
    tmp_path = fixture_dir
    settings = Settings(
        data_dir=tmp_path,
        output_dir=tmp_path,
        max_chart_file_size_mb=1,
    )
    with pytest.raises(VisualizationRenderError):
        write_chart_png(b"x" * (1024 * 1024 + 1), settings)
    assert not list(tmp_path.glob("*.png"))


def test_output_directory_symlink_is_rejected(fixture_dir: Path) -> None:
    tmp_path = fixture_dir
    suffix = uuid.uuid4().hex
    real = tmp_path / f"real-{suffix}"
    real.mkdir()
    link = tmp_path / f"link-{suffix}"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        real.rmdir()
        pytest.skip("directory symlinks are unavailable on this platform")
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, output_dir=link)
    link.unlink()
    real.rmdir()
