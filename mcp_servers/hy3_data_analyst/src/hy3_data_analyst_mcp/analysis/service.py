"""End-to-end orchestration for Hy3-planned deterministic workflows."""

import json
import time
from pathlib import Path
from typing import Any

from hy3_data_analyst_mcp.analysis.models import EvidenceInterpretation
from hy3_data_analyst_mcp.analysis.prompts import INTERPRETER_SYSTEM_PROMPT
from hy3_data_analyst_mcp.analysis.workflow_executor import execute_workflow
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisStep
from hy3_data_analyst_mcp.analysis.workflow_planner import WorkflowPlanner
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import Hy3ResponseError
from hy3_data_analyst_mcp.hy3_client import Hy3Client


class AnalysisService:
    """Load, profile, plan, execute, and explain one bounded dataset workflow."""

    def __init__(self, settings: Settings, *, client: Hy3Client | None = None) -> None:
        self._settings = settings
        self._client = client or Hy3Client(settings)

    async def analyze(
        self,
        file_path: str | Path,
        question: str,
        *,
        reasoning_effort: str,
        max_steps: int = 6,
    ) -> dict[str, Any]:
        started = time.monotonic()
        source_path = resolve_data_file(
            file_path,
            allowed_directory=self._settings.data_dir,
            max_file_size_mb=self._settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=self._settings)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=3)
        effective_max_steps = min(max_steps, self._settings.max_workflow_steps)
        workflow = await WorkflowPlanner(self._client).create_workflow(
            question,
            profile,
            reasoning_effort=reasoning_effort,
            max_steps=effective_max_steps,
        )
        execution = execute_workflow(
            frame,
            workflow,
            source_file_name=source_path.name,
            dataset_schema=DatasetSchema.from_profile(profile),
            max_records_per_step=self._settings.max_evidence_records_per_step,
            max_records_total=self._settings.max_evidence_records_total,
        )
        ledger = execution.evidence_ledger
        interpretation = await self._client.complete_structured(
            system_prompt=INTERPRETER_SYSTEM_PROMPT,
            user_prompt=json.dumps(
                {
                    "question": question,
                    "workflow": workflow.model_dump(mode="json"),
                    "evidence_ledger": ledger.model_dump(mode="json"),
                },
                ensure_ascii=False,
                default=str,
            ),
            response_model=EvidenceInterpretation,
            reasoning_effort=reasoning_effort,
        )
        known_evidence_ids = {item.evidence_id for item in ledger.items}
        if (
            not interpretation.evidence_references
            or not set(interpretation.evidence_references) <= known_evidence_ids
        ):
            raise Hy3ResponseError(
                "Hy3 returned an explanation with invalid Evidence references.",
                "Retry the analysis so the explanation cites only this workflow's Evidence IDs.",
            )
        primary_step = next(
            step for step in workflow.steps if step.step_id == workflow.primary_step_id
        )
        primary_evidence = next(
            item for item in ledger.items if item.step_id == workflow.primary_step_id
        )
        return {
            "status": "ok",
            "plan": _compatibility_plan(primary_step),
            "evidence": _compatibility_evidence(primary_evidence.model_dump(mode="json")),
            "conclusion": interpretation.conclusion,
            "evidence_references": interpretation.evidence_references,
            "limitations": interpretation.limitations,
            "warnings": [warning for item in ledger.items for warning in item.warnings],
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "workflow": workflow.model_dump(mode="json"),
            "evidence_ledger": ledger.model_dump(mode="json"),
            "step_audits": [audit.model_dump(mode="json") for audit in execution.step_audits],
            "step_timings_ms": execution.step_timings_ms,
        }


def _compatibility_plan(step: AnalysisStep) -> dict[str, Any]:
    params = step.params
    payload = params.model_dump(mode="json")
    target_columns = payload.get("target_columns", [])
    if not target_columns and "metrics" in payload:
        target_columns = list(dict.fromkeys(metric["column"] for metric in payload["metrics"]))
    if not target_columns and "column" in payload:
        target_columns = [payload["column"]]
    return {
        "operation": step.operation,
        "target_columns": target_columns,
        "group_by": payload.get("group_by", []),
        "aggregation": payload.get("aggregation"),
        "sort_order": payload.get("sort_order", "desc"),
        "limit": payload.get("limit", 100),
        "time_column": payload.get("time_column"),
        "rationale": step.purpose,
    }


def _compatibility_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": item["operation"],
        "summary": item["summary"],
        "records": item["records"],
        "metrics": item["metrics"],
        "warnings": item["warnings"],
    }
