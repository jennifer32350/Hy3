"""Deterministic chart data execution, quality handling, and PNG rendering."""

from __future__ import annotations

import io
import math
import os
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from hy3_data_analyst_mcp.analysis.evidence import EvidenceItem
from hy3_data_analyst_mcp.analysis.quality import prepare_analysis_data
from hy3_data_analyst_mcp.analysis.visualization_models import ChartSpec
from hy3_data_analyst_mcp.analysis.workflow_executor import (
    PHASE_E_OPERATIONS,
    execute_workflow,
)
from hy3_data_analyst_mcp.analysis.workflow_validator import (
    DatasetSchema,
    validate_workflow,
)
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import (
    InvalidAnalysisWorkflowError,
    OutputAccessDeniedError,
    VisualizationRenderError,
)
from hy3_data_analyst_mcp.models import DatasetProfile

MIN_WIDTH = 480
MAX_WIDTH = 1920
MIN_HEIGHT = 320
MAX_HEIGHT = 1080
MAX_POINTS = 5000
MAX_CATEGORIES = 30
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RENDER_LOCK = threading.Lock()
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class ChartExecution:
    """One rendered image plus auditable deterministic metadata."""

    png: bytes
    output_path: Path
    evidence: dict[str, Any]
    quality: dict[str, Any]


def validate_chart_spec(
    spec: ChartSpec,
    profile: DatasetProfile,
    *,
    max_steps: int,
) -> None:
    """Validate workflow safety and output-field semantics without trusting Hy3."""
    unsupported = [
        step for step in spec.data_plan.steps if step.operation not in PHASE_E_OPERATIONS
    ]
    if unsupported:
        raise InvalidAnalysisWorkflowError(
            f"Operation {unsupported[0].operation} is not available for visualization data.",
            "Use a locally executable whitelisted operation.",
            step_id=unsupported[0].step_id,
        )
    validate_workflow(
        spec.data_plan,
        DatasetSchema.from_profile(profile),
        max_steps=max_steps,
    )


def execute_chart_data(
    frame: pd.DataFrame,
    profile: DatasetProfile,
    source_path: Path,
    spec: ChartSpec,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-execute a Chart Spec and return only locally computed, Evidence-bound data."""
    validate_chart_spec(spec, profile, max_steps=settings.max_workflow_steps)
    schema = DatasetSchema.from_profile(profile)
    prepared = prepare_analysis_data(frame, spec.data_plan, schema)
    execution = execute_workflow(
        prepared.frame,
        spec.data_plan,
        source_file_name=source_path.name,
        dataset_schema=prepared.dataset_schema,
        max_records_per_step=settings.max_evidence_records_per_step,
        max_records_total=settings.max_evidence_records_total,
        quality_actions=prepared.quality_actions,
    )
    item = next(
        (
            entry
            for entry in execution.evidence_ledger.items
            if entry.evidence_id == spec.evidence_id
        ),
        None,
    )
    if item is None:
        raise InvalidAnalysisWorkflowError(
            f"Chart evidence_id {spec.evidence_id} is not produced by data_plan.",
            "Bind the chart to an Evidence-producing step in its data_plan.",
        )
    records, processing = _prepare_records(spec, item)
    evidence = item.model_dump(mode="json")
    evidence["records"] = records
    if processing["modified"]:
        evidence["truncated"] = True
        evidence["warnings"] = [
            *evidence["warnings"],
            "Visualization policies transformed or bounded the returned chart records.",
        ][:20]
    quality = {
        "data_quality": prepared.summary.model_dump(mode="json"),
        "visualization": processing,
        "step_audits": [audit.model_dump(mode="json") for audit in execution.step_audits],
    }
    return evidence, quality


def render_chart(
    spec: ChartSpec,
    evidence: dict[str, Any],
    *,
    width: int,
    height: int,
) -> bytes:
    """Render one validated chart using the non-interactive Matplotlib backend."""
    if not MIN_WIDTH <= width <= MAX_WIDTH or not MIN_HEIGHT <= height <= MAX_HEIGHT:
        raise VisualizationRenderError(
            f"Chart dimensions must be {MIN_WIDTH}..{MAX_WIDTH} by {MIN_HEIGHT}..{MAX_HEIGHT}.",
            "Choose bounded width and height values and retry.",
        )
    records = evidence["records"]
    if not records:
        raise VisualizationRenderError(
            "No finite chart points remain after deterministic quality handling.",
            "Choose populated fields or adjust the quality policy.",
        )
    with _RENDER_LOCK:
        fig, axis = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        try:
            _plot(axis, spec, records)
            axis.set_title(spec.title)
            axis.grid(axis="y", alpha=0.2)
            fig.subplots_adjust(left=0.1, right=0.97, bottom=0.16, top=0.9)
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=100, metadata={"Software": "Hy3 Data Analyst"})
            payload = buffer.getvalue()
        except VisualizationRenderError:
            raise
        except Exception as exc:
            raise VisualizationRenderError(
                "The validated chart could not be rendered.",
                "Choose simpler compatible chart fields and retry.",
            ) from exc
        finally:
            plt.close(fig)
    if not payload.startswith(_PNG_SIGNATURE) or len(payload) <= len(_PNG_SIGNATURE):
        raise VisualizationRenderError(
            "The renderer did not produce a valid non-empty PNG.",
            "Retry with a smaller chart or inspect the Matplotlib installation.",
        )
    return payload


def write_chart_png(payload: bytes, settings: Settings) -> Path:
    """Exclusively write one UUID-named PNG inside the configured safe output root."""
    root = settings.require_output_dir()
    _reject_reparse(root)
    if len(payload) > settings.max_chart_file_size_mb * 1024 * 1024:
        raise VisualizationRenderError(
            f"Rendered PNG exceeds the {settings.max_chart_file_size_mb} MB output limit.",
            "Reduce chart dimensions or data density and retry.",
        )
    target = root / f"{uuid.uuid4()}.png"
    created = False
    try:
        with target.open("xb") as handle:
            created = True
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        resolved = target.resolve(strict=True)
        current_root = root.resolve(strict=True)
        if not resolved.is_relative_to(current_root):
            raise OutputAccessDeniedError(
                "The chart output escaped HY3_OUTPUT_DIR.",
                "Use a regular local output directory without links or redirections.",
            )
        _reject_reparse(resolved)
        if resolved.stat().st_size != len(payload):
            raise VisualizationRenderError(
                "The chart output size changed during the safe write.",
                "Check output storage integrity and retry.",
            )
        return resolved
    except FileExistsError as exc:
        raise OutputAccessDeniedError(
            "The generated chart filename already exists; refusing to overwrite it.",
            "Retry to generate a fresh UUID filename.",
        ) from exc
    except (OutputAccessDeniedError, VisualizationRenderError):
        if created:
            _cleanup_created_file(target)
        raise
    except OSError as exc:
        if created:
            _cleanup_created_file(target)
        raise OutputAccessDeniedError(
            "The chart output could not be written safely.",
            "Check HY3_OUTPUT_DIR permissions and ensure it is not a link or reparse point.",
        ) from exc


def cleanup_chart_file(path: Path, output_root: Path) -> None:
    """Remove only a file created by the current render call and still inside its root."""
    try:
        resolved_root = output_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(resolved_root) and resolved.suffix == ".png":
            resolved.unlink(missing_ok=True)
    except OSError:
        pass


def _prepare_records(
    spec: ChartSpec, item: EvidenceItem
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = [dict(record) for record in item.records]
    fields = _chart_fields(spec)
    available = {key for record in records for key in record}
    unknown = sorted(set(fields) - available)
    if unknown:
        raise InvalidAnalysisWorkflowError(
            f"Chart fields are absent from {spec.evidence_id}: {', '.join(unknown)}.",
            "Use source result fields or aliases produced by the bound Evidence step.",
        )
    source_count = len(records)
    valid = [record for record in records if all(_present(record.get(field)) for field in fields)]
    missing_removed = source_count - len(valid)
    non_numeric = _numeric_fields(spec)
    invalid_numeric = [
        field
        for field in non_numeric
        if not any(_finite_number(record.get(field)) for record in valid)
    ]
    if invalid_numeric:
        raise InvalidAnalysisWorkflowError(
            f"Chart requires numeric Evidence fields: {', '.join(invalid_numeric)}.",
            "Choose numeric result fields or numeric derived aliases.",
        )
    valid = [
        record
        for record in valid
        if all(_finite_number(record.get(field)) for field in non_numeric)
    ]
    numeric_removed = source_count - missing_removed - len(valid)

    sampled = 0
    if len(valid) > MAX_POINTS:
        pre_sample_count = len(valid)
        indexes = _evenly_spaced_indexes(len(valid), MAX_POINTS)
        valid = [valid[index] for index in indexes]
        sampled = pre_sample_count - len(valid)

    if spec.sort != "none":
        sort_field = _sort_field(spec)
        valid.sort(
            key=lambda record: _stable_sort_key(record.get(sort_field)),
            reverse=spec.sort == "desc",
        )
    limited = max(0, len(valid) - spec.limit)
    valid = valid[: spec.limit]
    valid, category_meta = _bound_categories(spec, valid)
    metadata = {
        "source_evidence_records": source_count,
        "plotted_records": len(valid),
        "missing_records_removed": missing_removed,
        "non_finite_records_removed": numeric_removed,
        "sampled_records_removed": sampled,
        "limit_records_removed": limited,
        **category_meta,
    }
    metadata["modified"] = any(
        metadata[key]
        for key in (
            "missing_records_removed",
            "non_finite_records_removed",
            "sampled_records_removed",
            "limit_records_removed",
            "categories_collapsed",
        )
    )
    return valid, metadata


def _bound_categories(
    spec: ChartSpec, records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    category_field = spec.x if spec.chart_type in {"bar", "box"} else None
    if category_field is None:
        return records, {"categories_kept": 0, "categories_collapsed": 0}
    ordered = list(dict.fromkeys(str(record[category_field]) for record in records))
    if len(ordered) <= MAX_CATEGORIES:
        return records, {
            "categories_kept": len(ordered),
            "categories_collapsed": 0,
        }
    kept = set(ordered[:MAX_CATEGORIES])
    collapsed = len(ordered) - len(kept)
    if spec.chart_type == "box":
        bounded = [
            {
                **record,
                category_field: (
                    record[category_field] if str(record[category_field]) in kept else "Other"
                ),
            }
            for record in records
        ]
        return bounded, {
            "categories_kept": MAX_CATEGORIES,
            "categories_collapsed": collapsed,
        }

    assert spec.y is not None
    bounded = [record for record in records if str(record[category_field]) in kept]
    other = [record for record in records if str(record[category_field]) not in kept]
    group_fields = [spec.color] if spec.color is not None else []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in other:
        key = tuple(record[field] for field in group_fields)
        groups.setdefault(key, []).append(record)
    for key, group in groups.items():
        entry: dict[str, Any] = {category_field: "Other", spec.y: sum(row[spec.y] for row in group)}
        entry.update(zip(group_fields, key, strict=True))
        bounded.append(entry)
    return bounded, {
        "categories_kept": MAX_CATEGORIES,
        "categories_collapsed": collapsed,
    }


def _plot(axis: Any, spec: ChartSpec, records: list[dict[str, Any]]) -> None:
    if spec.chart_type == "histogram":
        field = spec.y or spec.x
        assert field is not None
        values = [float(record[field]) for record in records]
        axis.hist(values, bins=min(30, max(5, math.ceil(math.sqrt(len(values))))))
        axis.set_xlabel(field)
        axis.set_ylabel("Frequency")
        return
    if spec.chart_type == "box":
        assert spec.y is not None
        if spec.x is None:
            axis.boxplot([[float(record[spec.y]) for record in records]], tick_labels=[spec.y])
        else:
            box_groups: dict[str, list[float]] = {}
            for record in records:
                box_groups.setdefault(str(record[spec.x]), []).append(float(record[spec.y]))
            axis.boxplot(list(box_groups.values()), tick_labels=list(box_groups))
            axis.set_xlabel(spec.x)
        axis.set_ylabel(spec.y)
        return
    assert spec.x is not None and spec.y is not None
    if spec.color is None:
        x_values = [record[spec.x] for record in records]
        y_values = [float(record[spec.y]) for record in records]
        if spec.chart_type == "bar":
            axis.bar([str(value) for value in x_values], y_values)
        elif spec.chart_type == "line":
            axis.plot(x_values, y_values, marker="o")
        else:
            axis.scatter([float(value) for value in x_values], y_values)
    else:
        color_groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            color_groups.setdefault(str(record[spec.color]), []).append(record)
        for label, group in color_groups.items():
            x_values = [record[spec.x] for record in group]
            y_values = [float(record[spec.y]) for record in group]
            if spec.chart_type == "bar":
                axis.bar([str(value) for value in x_values], y_values, label=label, alpha=0.75)
            elif spec.chart_type == "line":
                axis.plot(x_values, y_values, marker="o", label=label)
            else:
                axis.scatter([float(value) for value in x_values], y_values, label=label)
        axis.legend()
    axis.set_xlabel(spec.x)
    axis.set_ylabel(spec.y)
    if spec.chart_type in {"bar", "box"}:
        axis.tick_params(axis="x", rotation=35)


def _chart_fields(spec: ChartSpec) -> list[str]:
    return [field for field in (spec.x, spec.y, spec.color) if field is not None]


def _numeric_fields(spec: ChartSpec) -> list[str]:
    fields = [spec.y] if spec.y is not None else []
    if spec.chart_type == "scatter" and spec.x is not None:
        fields.append(spec.x)
    if spec.chart_type == "histogram":
        histogram_field = spec.y or spec.x
        fields = [histogram_field] if histogram_field is not None else []
    return [field for field in fields if field is not None]


def _sort_field(spec: ChartSpec) -> str:
    if spec.chart_type == "bar" and spec.y is not None:
        return spec.y
    return spec.x or spec.y or ""


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and not math.isfinite(value))


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _stable_sort_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, str(value)


def _evenly_spaced_indexes(length: int, count: int) -> list[int]:
    if count == 1:
        return [0]
    return [round(index * (length - 1) / (count - 1)) for index in range(count)]


def _reject_reparse(path: Path) -> None:
    try:
        stat = path.lstat()
    except OSError as exc:
        raise OutputAccessDeniedError(
            "The chart output path cannot be inspected safely.",
            "Use an existing regular local output directory.",
        ) from exc
    attributes = getattr(stat, "st_file_attributes", 0)
    if path.is_symlink() or attributes & _REPARSE_POINT:
        raise OutputAccessDeniedError(
            "Symbolic links and filesystem reparse points are not allowed for chart output.",
            "Use a regular local HY3_OUTPUT_DIR.",
        )


def _cleanup_created_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)
