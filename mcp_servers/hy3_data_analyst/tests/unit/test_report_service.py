"""Phase D report grounding, confidence, causality, and repair tests."""

from __future__ import annotations

from typing import Any

import pytest

from hy3_data_analyst_mcp.analysis.evidence import EvidenceLedger
from hy3_data_analyst_mcp.analysis.quality import QualitySummary
from hy3_data_analyst_mcp.analysis.report_models import AnalysisReport
from hy3_data_analyst_mcp.analysis.report_service import (
    ReportService,
    validate_report_grounding,
)
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.errors import InvalidAnalysisReportError


class StubClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def complete_structured(self, **kwargs: Any) -> Any:
        self.prompts.append(kwargs["user_prompt"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _quality(**overrides: Any) -> QualitySummary:
    payload: dict[str, Any] = {
        "source_rows": 10,
        "analysis_base_rows": 10,
        "duplicate_rows_found": 0,
        "duplicate_rows_removed": 0,
        "referenced_rows_with_missing": 0,
        "rows_removed_for_missing": 0,
        "numeric_values_coerced_to_null": 0,
        "date_values_coerced_to_null": 0,
        "policies_applied": [
            "duplicates=keep (found=0, removed=0)",
            "numeric_conversion=strict (coerced_to_null=0)",
            "date_conversion=coerce (coerced_to_null=0)",
            "missing=keep (removed=0)",
        ],
        "source_modified": False,
    }
    payload.update(overrides)
    return QualitySummary.model_validate(payload)


def _ledger(
    *,
    operation: str = "multi_aggregate",
    truncated: bool = False,
    warnings: list[str] | None = None,
) -> EvidenceLedger:
    return EvidenceLedger.model_validate(
        {
            "items": [
                {
                    "evidence_id": "E01",
                    "step_id": "S01",
                    "operation": operation,
                    "summary": "Deterministic result.",
                    "metrics": {"result_rows": 1},
                    "records": [
                        {
                            "region": "North",
                            "revenue_sum": 1200.0,
                            "share": 0.5,
                            "correlation": 0.8,
                        }
                    ],
                    "source_rows": 10,
                    "used_rows": 10,
                    "excluded_rows": 0,
                    "truncated": truncated,
                    "warnings": warnings or [],
                    "lineage": {
                        "source_file_name": "sales.csv",
                        "input_ref": "source",
                        "referenced_columns": ["region", "revenue"],
                        "quality_actions": [],
                    },
                }
            ]
        }
    )


def _workflow() -> AnalysisWorkflow:
    return AnalysisWorkflow.model_validate(
        {
            "version": "2.0",
            "goal": "Compare regional revenue.",
            "primary_step_id": "S01",
            "quality_policy": {},
            "steps": [
                {
                    "step_id": "S01",
                    "operation": "multi_aggregate",
                    "input_ref": "source",
                    "params": {
                        "group_by": ["region"],
                        "metrics": [
                            {
                                "column": "revenue",
                                "aggregation": "sum",
                                "alias": "revenue_sum",
                            }
                        ],
                    },
                    "purpose": "Aggregate revenue.",
                }
            ],
            "rationale": "Use deterministic aggregation.",
        }
    )


def _report(
    *,
    statement: str = "North revenue is 1,200 and its share is 50%.",
    executive_summary: str = "North revenue is 1,200 with a 50% share.",
    evidence_ids: list[str] | None = None,
    confidence: str = "high",
) -> AnalysisReport:
    return AnalysisReport.model_validate(
        {
            "executive_summary": executive_summary,
            "findings": [
                {
                    "finding_id": "F01",
                    "kind": "fact",
                    "title": "North revenue",
                    "statement": statement,
                    "evidence_ids": evidence_ids or ["E01"],
                    "confidence": confidence,
                }
            ],
            "anomalies": [],
            "recommendations": [
                {
                    "recommendation_id": "R01",
                    "statement": "Review the North result before taking action.",
                    "basis_evidence_ids": ["E01"],
                    "priority": "medium",
                }
            ],
            "data_scope": {
                "source_file_name": "sales.csv",
                "source_rows": 10,
                "used_rows": 10,
                "excluded_rows": 0,
                "referenced_columns": ["region", "revenue"],
                "filters_applied": [],
                "time_grain": None,
                "notes": [],
            },
            "limitations": [],
            "warnings": [],
            "suggested_follow_ups": ["Compare another region."],
        }
    )


def test_grounding_accepts_commas_percentages_and_exact_values() -> None:
    validate_report_grounding(_report(), _ledger(), _quality())


def test_grounding_rejects_unknown_evidence_and_unsupported_number() -> None:
    with pytest.raises(ValueError, match="unknown Evidence IDs"):
        validate_report_grounding(
            _report(evidence_ids=["E02"]),
            _ledger(),
            _quality(),
        )
    with pytest.raises(ValueError, match="999"):
        validate_report_grounding(
            _report(statement="North revenue is 999."),
            _ledger(),
            _quality(),
        )


def test_correlation_cannot_be_described_as_causal() -> None:
    with pytest.raises(ValueError, match="causal language"):
        validate_report_grounding(
            _report(
                statement="A correlation of 0.8 causes higher revenue.",
                executive_summary="The observed correlation is 0.8.",
            ),
            _ledger(operation="correlation"),
            _quality(),
        )


@pytest.mark.parametrize(
    ("ledger", "quality"),
    [
        (_ledger(truncated=True), _quality()),
        (_ledger(warnings=["Small sample."]), _quality()),
        (_ledger(), _quality(referenced_rows_with_missing=2)),
        (_ledger(), _quality(duplicate_rows_found=1)),
    ],
)
def test_high_confidence_is_rejected_for_bounded_or_quality_risk(
    ledger: EvidenceLedger,
    quality: QualitySummary,
) -> None:
    with pytest.raises(ValueError, match="confidence cannot be high"):
        validate_report_grounding(_report(), ledger, quality)


async def test_report_service_repairs_once_and_replaces_data_scope() -> None:
    invalid = _report(statement="North revenue is 999.")
    valid = _report(confidence="medium")
    client = StubClient([invalid, valid])

    report = await ReportService(client).create_report(  # type: ignore[arg-type]
        "Compare revenue.",
        _workflow(),
        _ledger(),
        _quality(),
        (),
        reasoning_effort="high",
    )

    assert len(client.prompts) == 2
    assert '"invalid_report"' in client.prompts[1]
    assert report.findings[0].statement == valid.findings[0].statement
    assert report.data_scope.notes == _quality().policies_applied


async def test_report_service_fails_after_one_repair_and_preserves_evidence() -> None:
    client = StubClient(
        [
            _report(statement="North revenue is 999."),
            _report(statement="North revenue is 998."),
        ]
    )

    with pytest.raises(InvalidAnalysisReportError) as captured:
        await ReportService(client).create_report(  # type: ignore[arg-type]
            "Compare revenue.",
            _workflow(),
            _ledger(),
            _quality(),
            (),
            reasoning_effort="low",
        )

    assert len(client.prompts) == 2
    assert captured.value.as_dict()["evidence_ledger"]["items"][0]["evidence_id"] == "E01"
