"""Tests for bounded v0.2 Evidence and Report schemas."""

from typing import Any

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.evidence import EvidenceItem, EvidenceLedger
from hy3_data_analyst_mcp.analysis.report_models import (
    AnalysisReport,
    Finding,
    validate_report_evidence_references,
)


def _evidence(
    evidence_id: str = "E01",
    step_id: str = "S01",
    *,
    records: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_id": evidence_id,
        "step_id": step_id,
        "operation": "describe",
        "summary": "Deterministic summary.",
        "metrics": {"mean": 10.0},
        "records": records or [],
        "source_rows": 10,
        "used_rows": 9,
        "excluded_rows": 1,
        "truncated": False,
        "warnings": [],
        "lineage": {
            "source_file_name": "sales.csv",
            "input_ref": "source",
            "referenced_columns": ["revenue"],
            "quality_actions": ["missing=keep"],
        },
    }
    payload.update(overrides)
    return payload


def _report() -> AnalysisReport:
    return AnalysisReport.model_validate(
        {
            "executive_summary": "Revenue was summarized deterministically.",
            "findings": [
                {
                    "finding_id": "F01",
                    "kind": "fact",
                    "title": "Mean revenue",
                    "statement": "The mean is 10.",
                    "evidence_ids": ["E01"],
                    "confidence": "high",
                }
            ],
            "anomalies": [],
            "recommendations": [
                {
                    "recommendation_id": "R01",
                    "statement": "Review the bounded evidence.",
                    "basis_evidence_ids": ["E01"],
                    "priority": "medium",
                }
            ],
            "data_scope": {
                "source_file_name": "sales.csv",
                "source_rows": 10,
                "used_rows": 9,
                "excluded_rows": 1,
                "referenced_columns": ["revenue"],
                "filters_applied": [],
                "time_grain": None,
                "notes": ["One row was excluded by an explicit policy."],
            },
            "limitations": [],
            "warnings": [],
            "suggested_follow_ups": ["Inspect missing values."],
        }
    )


def test_evidence_item_is_json_safe_and_bounded() -> None:
    item = EvidenceItem.model_validate(_evidence(records=[{"region": "North", "value": 10.0}]))
    assert item.model_dump(mode="json")["lineage"]["source_file_name"] == "sales.csv"


@pytest.mark.parametrize(
    "payload",
    [
        _evidence(source_rows=10, used_rows=10, excluded_rows=1),
        _evidence(metrics={"unsafe": float("nan")}),
        _evidence(operation="filter_rows"),
        _evidence(lineage={"source_file_name": "C:\\private\\sales.csv", "input_ref": "source"}),
        _evidence(extra_field="forbidden"),
        _evidence(records=[{"value": index} for index in range(101)]),
    ],
)
def test_evidence_rejects_invalid_counts_non_json_paths_extras_and_limits(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(payload)


def test_evidence_ledger_enforces_ids_steps_and_total_record_limit() -> None:
    with pytest.raises(ValidationError, match="continuous"):
        EvidenceLedger.model_validate({"items": [_evidence("E02", "S01")]})
    with pytest.raises(ValidationError, match="at most one"):
        EvidenceLedger.model_validate({"items": [_evidence("E01", "S01"), _evidence("E02", "S01")]})
    with pytest.raises(ValidationError, match="must not exceed 300"):
        EvidenceLedger.model_validate(
            {
                "items": [
                    _evidence(
                        f"E{index:02d}",
                        f"S{index:02d}",
                        records=[{"value": record} for record in range(100)],
                    )
                    for index in range(1, 5)
                ]
            }
        )


def test_report_requires_grounded_fact_and_risk_findings() -> None:
    with pytest.raises(ValidationError, match="require at least one"):
        Finding(
            finding_id="F01",
            kind="fact",
            title="Ungrounded",
            statement="No evidence.",
            evidence_ids=[],
            confidence="low",
        )
    interpretation = Finding(
        finding_id="F02",
        kind="interpretation",
        title="Tentative",
        statement="An explicitly ungrounded interpretation.",
        evidence_ids=[],
        confidence="low",
    )
    assert interpretation.evidence_ids == []


def test_report_rejects_duplicate_ids_paths_and_extra_fields() -> None:
    payload = _report().model_dump(mode="json")
    payload["anomalies"] = [payload["findings"][0]]
    with pytest.raises(ValidationError, match="finding IDs must be unique"):
        AnalysisReport.model_validate(payload)

    payload = _report().model_dump(mode="json")
    payload["data_scope"]["source_file_name"] = "../sales.csv"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)

    payload = _report().model_dump(mode="json")
    payload["code"] = "print('forbidden')"
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_report_references_must_exist_in_current_ledger() -> None:
    report = _report()
    validate_report_evidence_references(report, {"E01"})
    with pytest.raises(ValueError, match="unknown Evidence IDs"):
        validate_report_evidence_references(report, {"E02"})
