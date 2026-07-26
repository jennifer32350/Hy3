"""End-to-end orchestration for Hy3-planned deterministic workflows."""

import time
from pathlib import Path
from typing import Any, Literal

from hy3_data_analyst_mcp.analysis.evidence import EvidenceLedger
from hy3_data_analyst_mcp.analysis.quality import prepare_analysis_data
from hy3_data_analyst_mcp.analysis.report_models import AnalysisReport
from hy3_data_analyst_mcp.analysis.report_service import ReportService
from hy3_data_analyst_mcp.analysis.workflow_executor import execute_workflow
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisStep, QualityPolicy
from hy3_data_analyst_mcp.analysis.workflow_planner import WorkflowPlanner
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
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
        output_mode: Literal["concise", "detailed"] = "detailed",
        quality_policy: QualityPolicy | None = None,
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
        requested_quality_policy = quality_policy or QualityPolicy()
        workflow = await WorkflowPlanner(self._client).create_workflow(
            question,
            profile,
            reasoning_effort=reasoning_effort,
            max_steps=effective_max_steps,
            quality_policy=requested_quality_policy,
        )
        source_schema = DatasetSchema.from_profile(profile)
        prepared = prepare_analysis_data(frame, workflow, source_schema)
        execution = execute_workflow(
            prepared.frame,
            workflow,
            source_file_name=source_path.name,
            dataset_schema=prepared.dataset_schema,
            max_records_per_step=self._settings.max_evidence_records_per_step,
            max_records_total=self._settings.max_evidence_records_total,
            quality_actions=prepared.quality_actions,
        )
        ledger = execution.evidence_ledger
        report = await ReportService(self._client).create_report(
            question,
            workflow,
            ledger,
            prepared.summary,
            execution.step_audits,
            reasoning_effort=reasoning_effort,
        )
        serialized_ledger = _serialize_ledger(ledger, output_mode=output_mode)
        primary_step = next(
            step for step in workflow.steps if step.step_id == workflow.primary_step_id
        )
        primary_evidence = next(
            item
            for item in serialized_ledger["items"]
            if item["step_id"] == workflow.primary_step_id
        )
        evidence_references = _report_evidence_references(report)
        return {
            "status": "ok",
            "plan": _compatibility_plan(primary_step),
            "evidence": _compatibility_evidence(primary_evidence),
            "conclusion": report.executive_summary,
            "evidence_references": evidence_references,
            "limitations": report.limitations,
            "warnings": report.warnings,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "workflow": workflow.model_dump(mode="json"),
            "evidence_ledger": serialized_ledger,
            "report": report.model_dump(mode="json"),
            "quality_summary": prepared.summary.model_dump(mode="json"),
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


def _serialize_ledger(
    ledger: EvidenceLedger,
    *,
    output_mode: Literal["concise", "detailed"],
) -> dict[str, Any]:
    payload = ledger.model_dump(mode="json")
    if output_mode == "detailed":
        return payload
    for item in payload["items"]:
        if len(item["records"]) > 5:
            item["records"] = item["records"][:5]
            item["truncated"] = True
            item["warnings"] = list(
                dict.fromkeys(
                    [
                        *item["warnings"],
                        "Concise output limited this Evidence item to 5 records.",
                    ]
                )
            )[:20]
    return payload


def _report_evidence_references(report: AnalysisReport) -> list[str]:
    ordered: dict[str, None] = {}
    for finding in [*report.findings, *report.anomalies]:
        for evidence_id in finding.evidence_ids:
            ordered.setdefault(evidence_id, None)
    for recommendation in report.recommendations:
        for evidence_id in recommendation.basis_evidence_ids:
            ordered.setdefault(evidence_id, None)
    return list(ordered)
