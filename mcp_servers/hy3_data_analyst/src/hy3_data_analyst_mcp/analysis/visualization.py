"""Hy3-selected Chart Specs backed by deterministic local Evidence execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.models import VisualizationSuggestions
from hy3_data_analyst_mcp.analysis.prompts import (
    VISUALIZATION_REPAIR_PROMPT,
    VISUALIZATION_SYSTEM_PROMPT,
)
from hy3_data_analyst_mcp.analysis.visualization_executor import (
    ChartExecution,
    cleanup_chart_file,
    execute_chart_data,
    render_chart,
    write_chart_png,
)
from hy3_data_analyst_mcp.analysis.visualization_models import ChartSpec, ChartSpecSet
from hy3_data_analyst_mcp.analysis.workflow_executor import PHASE_E_OPERATIONS
from hy3_data_analyst_mcp.analysis.workflow_models import (
    AnalysisWorkflow,
    QualityPolicy,
)
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    InvalidAnalysisPlanError,
    InvalidAnalysisWorkflowError,
    WorkflowExecutionError,
)
from hy3_data_analyst_mcp.hy3_client import Hy3Client
from hy3_data_analyst_mcp.models import DatasetProfile


class VisualizationService:
    """Create bounded Chart Specs and prove that each data plan executes locally."""

    def __init__(self, settings: Settings, *, client: Hy3Client | None = None) -> None:
        self._settings = settings
        self._client = client or Hy3Client(settings)

    async def suggest(
        self,
        file_path: str | Path,
        goal: str,
        *,
        max_suggestions: int,
        quality_policy: QualityPolicy | None = None,
    ) -> dict[str, Any]:
        source_path = resolve_data_file(
            file_path,
            allowed_directory=self._settings.data_dir,
            max_file_size_mb=self._settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=self._settings)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=0)
        policy = quality_policy or QualityPolicy()
        context = _visualization_context(goal, profile, max_suggestions, policy)
        specs, executions = await self._generate_with_repair(
            context,
            frame=frame,
            profile=profile,
            source_path=source_path,
            quality_policy=policy,
        )
        bounded_specs = specs.charts[:max_suggestions]
        suggestions = [spec.model_dump(mode="json") for spec in bounded_specs]
        chart_evidence = [
            {
                "chart_index": index,
                "evidence_id": spec.evidence_id,
                "evidence": evidence,
                "quality": quality,
            }
            for index, (spec, (evidence, quality)) in enumerate(
                zip(bounded_specs, executions[:max_suggestions], strict=True), start=1
            )
        ]
        return {
            "status": "ok",
            "quality_policy": policy.model_dump(mode="json"),
            "suggestions": suggestions,
            "charts": suggestions,
            "chart_evidence": chart_evidence,
        }

    async def _generate_with_repair(
        self,
        context: str,
        *,
        frame: Any,
        profile: DatasetProfile,
        source_path: Path,
        quality_policy: QualityPolicy,
    ) -> tuple[ChartSpecSet, list[tuple[dict[str, Any], dict[str, Any]]]]:
        try:
            raw = await self._client.complete_structured(
                system_prompt=VISUALIZATION_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=VisualizationSuggestions,
            )
            result = _normalize_response(raw, profile, quality_policy)
            executions = self._validate_and_execute(
                result, frame, profile, source_path, quality_policy
            )
            return result, executions
        except (
            Hy3ResponseError,
            InvalidAnalysisWorkflowError,
            WorkflowExecutionError,
            ValueError,
        ) as first_error:
            try:
                raw = await self._client.complete_structured(
                    system_prompt=VISUALIZATION_REPAIR_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "planning_context": json.loads(context),
                            "validation_error": _safe_validation_message(first_error),
                        },
                        ensure_ascii=False,
                    ),
                    response_model=VisualizationSuggestions,
                )
                repaired = _normalize_response(raw, profile, quality_policy)
                executions = self._validate_and_execute(
                    repaired, frame, profile, source_path, quality_policy
                )
                return repaired, executions
            except (
                Hy3ResponseError,
                InvalidAnalysisWorkflowError,
                WorkflowExecutionError,
                ValueError,
            ) as exc:
                raise InvalidAnalysisPlanError(
                    "Hy3 could not produce valid executable Chart Specs after one repair attempt.",
                    "Rephrase the goal using exact dataset columns and compatible chart fields.",
                ) from exc

    def _validate_and_execute(
        self,
        result: ChartSpecSet,
        frame: Any,
        profile: DatasetProfile,
        source_path: Path,
        quality_policy: QualityPolicy,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if result.quality_policy != quality_policy:
            raise ValueError("visualization quality_policy must match the requested policy")
        executions: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for spec in result.charts:
            executions.append(execute_chart_data(frame, profile, source_path, spec, self._settings))
        return executions


class VisualizationRenderService:
    """Select, re-execute, render, and safely persist a bounded set of charts."""

    def __init__(self, settings: Settings, *, client: Hy3Client | None = None) -> None:
        self._settings = settings
        self._suggestions = VisualizationService(settings, client=client)

    async def render(
        self,
        file_path: str | Path,
        goal: str,
        *,
        max_charts: int,
        width: int,
        height: int,
        quality_policy: QualityPolicy | None = None,
    ) -> list[ChartExecution]:
        output_root = self._settings.require_output_dir()
        suggested = await self._suggestions.suggest(
            file_path,
            goal,
            max_suggestions=max_charts,
            quality_policy=quality_policy,
        )
        specs = [ChartSpec.model_validate(payload) for payload in suggested["charts"]]
        source_path = resolve_data_file(
            file_path,
            allowed_directory=self._settings.data_dir,
            max_file_size_mb=self._settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=self._settings)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=0)
        results: list[ChartExecution] = []
        try:
            for spec in specs[:max_charts]:
                evidence, quality = execute_chart_data(
                    frame, profile, source_path, spec, self._settings
                )
                png = render_chart(spec, evidence, width=width, height=height)
                output_path = write_chart_png(png, self._settings)
                results.append(
                    ChartExecution(
                        png=png,
                        output_path=output_path,
                        evidence=evidence,
                        quality={
                            **quality,
                            "chart_spec": spec.model_dump(mode="json"),
                        },
                    )
                )
        except Exception:
            for result in results:
                cleanup_chart_file(result.output_path, output_root)
            raise
        return results


def _normalize_response(
    raw: Any,
    profile: DatasetProfile,
    quality_policy: QualityPolicy,
) -> ChartSpecSet:
    if isinstance(raw, ChartSpecSet):
        return raw
    if isinstance(raw, VisualizationSuggestions):
        charts = [
            ChartSpec(
                **suggestion.model_dump(mode="python"),
                data_plan=_legacy_data_plan(
                    suggestion.model_dump(mode="python"), profile, quality_policy
                ),
                evidence_id="E01",
                sort="none",
                limit=100,
                notes=["Compatibility plan derived locally from the legacy suggestion fields."],
            )
            for suggestion in raw.suggestions[:5]
        ]
        return ChartSpecSet(quality_policy=quality_policy, charts=charts)
    return ChartSpecSet.model_validate(raw)


def _legacy_data_plan(
    suggestion: dict[str, Any],
    profile: DatasetProfile,
    quality_policy: QualityPolicy,
) -> AnalysisWorkflow:
    chart_type = suggestion["chart_type"]
    x = suggestion.get("x")
    y = suggestion.get("y")
    color = suggestion.get("color")
    aggregation = suggestion.get("aggregation") or "sum"
    semantic = {column.name: column.semantic_type for column in profile.columns}
    if chart_type == "line" and x is not None and semantic.get(x) == "datetime" and y:
        operation = "time_trend"
        params = {
            "time_column": x,
            "target_columns": [y],
            "aggregation": aggregation,
            "grain": "month",
            "sort_order": "asc",
            "limit": 100,
        }
    elif chart_type in {"bar", "line"} and x is not None and y is not None:
        operation = "groupby_aggregate"
        params = {
            "target_columns": [y],
            "group_by": list(dict.fromkeys([x, *([color] if color else [])])),
            "aggregation": aggregation,
            "sort_order": "desc",
            "limit": 100,
        }
    else:
        operation = "top_k"
        selected = list(dict.fromkeys(field for field in (y, x, color) if field is not None))
        params = {
            "target_columns": selected,
            "group_by": [],
            "sort_order": "desc",
            "limit": 100,
        }
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": suggestion["rationale"],
            "primary_step_id": "S01",
            "quality_policy": quality_policy.model_dump(mode="json"),
            "steps": [
                {
                    "step_id": "S01",
                    "input_ref": "source",
                    "purpose": suggestion["rationale"],
                    "operation": operation,
                    "params": params,
                }
            ],
            "rationale": "Compatibility workflow for a legacy visualization suggestion.",
        }
    )


def _visualization_context(
    goal: str,
    profile: DatasetProfile,
    max_charts: int,
    quality_policy: QualityPolicy,
) -> str:
    return json.dumps(
        {
            "goal": goal,
            "max_charts": max_charts,
            "max_workflow_steps": 6,
            "max_evidence_records": 100,
            "allowed_operations": sorted(PHASE_E_OPERATIONS),
            "requested_quality_policy": quality_policy.model_dump(mode="json"),
            "row_count": profile.row_count,
            "columns": [
                {
                    "name": item.name,
                    "semantic_type": item.semantic_type,
                    "unique_count": item.unique_count,
                    "missing_rate": item.missing_rate,
                }
                for item in profile.columns
            ],
        },
        ensure_ascii=False,
    )


def _safe_validation_message(error: Exception) -> str:
    if isinstance(error, InvalidAnalysisWorkflowError):
        return error.message
    if isinstance(error, Hy3ResponseError):
        if isinstance(error.__cause__, ValidationError):
            details: list[str] = []
            for issue in error.__cause__.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:3]:
                location = ".".join(str(part) for part in issue["loc"]) or "chart_spec"
                details.append(f"{location}: {issue['msg']}")
            if details:
                return "Chart Spec schema validation failed: " + "; ".join(details)
        return "The model response did not satisfy the Chart Spec schema."
    message = str(error).strip()
    return message[:1000] or "The Chart Spec failed local validation."
