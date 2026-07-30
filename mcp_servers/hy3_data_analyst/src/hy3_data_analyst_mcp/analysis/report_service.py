"""Grounded Phase D report generation, semantic validation, and one repair."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

from hy3_data_analyst_mcp.analysis.evidence import EvidenceItem, EvidenceLedger
from hy3_data_analyst_mcp.analysis.prompts import (
    REPORT_REPAIR_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
)
from hy3_data_analyst_mcp.analysis.quality import QualitySummary
from hy3_data_analyst_mcp.analysis.report_models import (
    AnalysisReport,
    DataScope,
    Finding,
    Recommendation,
    validate_report_evidence_references,
)
from hy3_data_analyst_mcp.analysis.workflow_executor import StepAudit
from hy3_data_analyst_mcp.analysis.workflow_models import (
    AnalysisWorkflow,
    FilterRowsStep,
    PeriodCompareStep,
    TimeTrendStep,
)
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    Hy3StructuredOutputError,
    InvalidAnalysisReportError,
)
from hy3_data_analyst_mcp.hy3_client import Hy3Client

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![A-Za-z0-9_])"
)
_CAUSAL_TERMS = (
    "导致",
    "造成",
    "驱动",
    "引起",
    "cause",
    "causes",
    "caused",
    "drive",
    "drives",
    "driven",
    "lead to",
    "leads to",
    "result in",
    "results in",
)


class ReportService:
    """Ask Hy3 for a report and reject every ungrounded semantic result."""

    def __init__(self, client: Hy3Client) -> None:
        self._client = client

    async def create_report(
        self,
        question: str,
        workflow: AnalysisWorkflow,
        ledger: EvidenceLedger,
        quality_summary: QualitySummary,
        step_audits: tuple[StepAudit, ...],
        *,
        reasoning_effort: str,
    ) -> AnalysisReport:
        data_scope = build_data_scope(workflow, ledger, quality_summary, step_audits)
        context = _report_context(question, workflow, ledger, quality_summary, data_scope)
        report: AnalysisReport | None = None
        try:
            report = await self._client.complete_structured(
                system_prompt=REPORT_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=AnalysisReport,
                reasoning_effort=reasoning_effort,
            )
            return _finalize_and_validate_report(report, ledger, quality_summary, data_scope)
        except (Hy3ResponseError, ValueError) as first_error:
            try:
                repaired = await self._client.complete_structured(
                    system_prompt=REPORT_REPAIR_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "report_context": json.loads(context),
                            "invalid_report": (
                                report.model_dump(mode="json") if report is not None else None
                            ),
                            "validation_error": _safe_report_error(first_error),
                        },
                        ensure_ascii=False,
                    ),
                    response_model=AnalysisReport,
                    reasoning_effort=reasoning_effort,
                )
                return _finalize_and_validate_report(repaired, ledger, quality_summary, data_scope)
            except (Hy3ResponseError, ValueError) as exc:
                raise InvalidAnalysisReportError(
                    "Hy3 could not produce a valid grounded report after one repair attempt.",
                    "Review the returned deterministic Evidence or ask a narrower question.",
                    evidence_ledger=ledger.model_dump(mode="json"),
                ) from exc


def build_data_scope(
    workflow: AnalysisWorkflow,
    ledger: EvidenceLedger,
    quality_summary: QualitySummary,
    step_audits: tuple[StepAudit, ...],
) -> DataScope:
    """Build report scope from local facts rather than model-authored values."""
    source_file_name = ledger.items[0].lineage.source_file_name
    referenced: dict[str, None] = {}
    for item in ledger.items:
        for column in item.lineage.referenced_columns:
            referenced.setdefault(column, None)
    filters = [
        f"{step.step_id}: {step.params.combine} filter on "
        f"{', '.join(dict.fromkeys(condition.column for condition in step.params.conditions))}"
        for step in workflow.steps
        if isinstance(step, FilterRowsStep)
    ]
    grains = {
        step.params.grain
        for step in workflow.steps
        if isinstance(step, (TimeTrendStep, PeriodCompareStep))
    }
    time_grain = next(iter(grains)) if len(grains) == 1 else None
    notes = list(quality_summary.policies_applied)
    if len(grains) > 1:
        notes.append("The workflow used multiple time grains; data_scope.time_grain is null.")
    if step_audits:
        notes.append(f"{len(step_audits)} View step(s) were audited without modifying the source.")
    return DataScope(
        source_file_name=source_file_name,
        source_rows=quality_summary.source_rows,
        used_rows=quality_summary.analysis_base_rows,
        excluded_rows=quality_summary.source_rows - quality_summary.analysis_base_rows,
        referenced_columns=list(referenced)[:25],
        filters_applied=filters,
        time_grain=time_grain,
        notes=notes[:20],
    )


def validate_report_grounding(
    report: AnalysisReport,
    ledger: EvidenceLedger,
    quality_summary: QualitySummary,
) -> None:
    """Validate references, confidence, causality, and every report numeric claim."""
    evidence_by_id = {item.evidence_id: item for item in ledger.items}
    validate_report_evidence_references(report, evidence_by_id)
    serious_quality = _has_serious_quality_actions(quality_summary)

    for finding in [*report.findings, *report.anomalies]:
        referenced_items = [evidence_by_id[item] for item in finding.evidence_ids]
        if finding.confidence == "high" and (
            serious_quality or any(item.truncated or item.warnings for item in referenced_items)
        ):
            raise ValueError(
                f"{finding.finding_id} confidence cannot be high with bounded or warned Evidence"
            )
        if any(item.operation == "correlation" for item in referenced_items):
            _reject_causal_language(finding)
        _validate_text_numbers(
            finding.statement,
            referenced_items,
            label=finding.finding_id,
        )

    for recommendation in report.recommendations:
        referenced_items = [evidence_by_id[item] for item in recommendation.basis_evidence_ids]
        _validate_recommendation_numbers(recommendation, referenced_items)

    _validate_text_numbers(
        report.executive_summary,
        ledger.items,
        label="executive_summary",
        extra_values=_quality_numeric_values(quality_summary),
    )


def _finalize_and_validate_report(
    report: AnalysisReport,
    ledger: EvidenceLedger,
    quality_summary: QualitySummary,
    data_scope: DataScope,
) -> AnalysisReport:
    deterministic_warnings = [warning for item in ledger.items for warning in item.warnings]
    deterministic_warnings.extend(_quality_warnings(quality_summary))
    warnings = list(dict.fromkeys([*report.warnings, *deterministic_warnings]))[:20]
    finalized = report.model_copy(update={"data_scope": data_scope, "warnings": warnings})
    validate_report_grounding(finalized, ledger, quality_summary)
    return finalized


def _validate_recommendation_numbers(
    recommendation: Recommendation,
    evidence: list[EvidenceItem],
) -> None:
    _validate_text_numbers(
        recommendation.statement,
        evidence,
        label=recommendation.recommendation_id,
    )


def _reject_causal_language(finding: Finding) -> None:
    normalized = finding.statement.casefold()
    if any(term in normalized for term in _CAUSAL_TERMS):
        raise ValueError(f"{finding.finding_id} uses causal language for correlation Evidence")


def _validate_text_numbers(
    text: str,
    evidence: Iterable[EvidenceItem],
    *,
    label: str,
    extra_values: Iterable[float] = (),
) -> None:
    claims = list(_number_claims(text))
    if not claims:
        return
    supported = [*extra_values]
    for item in evidence:
        supported.extend(_numeric_values(item.metrics))
        supported.extend(_numeric_values(item.records))
    unsupported = [
        token
        for token, value, tolerance in claims
        if not any(
            math.isclose(value, known, rel_tol=1e-9, abs_tol=tolerance) for known in supported
        )
    ]
    if unsupported:
        raise ValueError(
            f"{label} contains numeric claims not grounded in cited Evidence: "
            f"{', '.join(unsupported)}"
        )


def _number_claims(text: str) -> Iterable[tuple[str, float, float]]:
    for match in _NUMBER_PATTERN.finditer(text):
        token = match.group(0)
        normalized = token.replace(",", "")
        is_percent = normalized.endswith("%")
        numeric_text = normalized.removesuffix("%")
        value = float(numeric_text)
        decimals = len(numeric_text.partition(".")[2])
        scale = 100 if is_percent else 1
        yield token, value / scale, 0.5 * (10 ** (-decimals)) / scale


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)] if math.isfinite(float(value)) else []
    if isinstance(value, str):
        return [claim[1] for claim in _number_claims(value)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in _numeric_values(item)]
    if isinstance(value, list):
        return [number for item in value for number in _numeric_values(item)]
    return []


def _quality_numeric_values(summary: QualitySummary) -> list[float]:
    return [
        float(summary.source_rows),
        float(summary.analysis_base_rows),
        float(summary.duplicate_rows_found),
        float(summary.duplicate_rows_removed),
        float(summary.referenced_rows_with_missing),
        float(summary.rows_removed_for_missing),
        float(summary.numeric_values_coerced_to_null),
        float(summary.date_values_coerced_to_null),
    ]


def _has_serious_quality_actions(summary: QualitySummary) -> bool:
    return any(
        (
            summary.duplicate_rows_removed,
            summary.duplicate_rows_found,
            summary.referenced_rows_with_missing,
            summary.rows_removed_for_missing,
            summary.numeric_values_coerced_to_null,
            summary.date_values_coerced_to_null,
        )
    )


def _quality_warnings(summary: QualitySummary) -> list[str]:
    warnings: list[str] = []
    if summary.duplicate_rows_found:
        warnings.append(
            f"The source contains {summary.duplicate_rows_found} duplicate row(s); "
            f"{summary.duplicate_rows_removed} were removed in memory."
        )
    if summary.referenced_rows_with_missing:
        warnings.append(
            f"{summary.referenced_rows_with_missing} row(s) had missing values in referenced "
            f"columns; {summary.rows_removed_for_missing} were removed in memory."
        )
    if summary.numeric_values_coerced_to_null:
        warnings.append(
            f"{summary.numeric_values_coerced_to_null} numeric value(s) were coerced to null."
        )
    if summary.date_values_coerced_to_null:
        warnings.append(
            f"{summary.date_values_coerced_to_null} date value(s) were coerced to null."
        )
    return warnings


def _report_context(
    question: str,
    workflow: AnalysisWorkflow,
    ledger: EvidenceLedger,
    quality_summary: QualitySummary,
    data_scope: DataScope,
) -> str:
    return json.dumps(
        {
            "question": question,
            "workflow": workflow.model_dump(mode="json"),
            "evidence_ledger": ledger.model_dump(mode="json"),
            "quality_summary": quality_summary.model_dump(mode="json"),
            "deterministic_data_scope": data_scope.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


def _safe_report_error(error: Exception) -> str:
    if isinstance(error, Hy3StructuredOutputError):
        return json.dumps(
            {
                "message": error.message,
                "validation_details": error.validation_details,
                "invalid_payload": error.invalid_payload,
            },
            ensure_ascii=False,
            default=str,
        )[:8_000]
    if isinstance(error, Hy3ResponseError):
        return error.message
    return str(error)[:1000]
