"""Validate Phase A cases and the frozen v0.1 deterministic baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

EVAL_ROOT = Path(__file__).resolve().parent
CASE_PATH = EVAL_ROOT / "cases" / "v0.2-phase-a.json"
RELEASE_CASE_PATH = EVAL_ROOT / "cases" / "v0.2-release.json"
DATA_ROOT = EVAL_ROOT / "data"
BASELINE_PATH = EVAL_ROOT / "baselines" / "v0.1.json"

CATEGORIES = {
    "basic_statistics",
    "composite_analysis",
    "trend",
    "anomaly",
    "quality",
    "visualization",
}
CASE_KEYS = {
    "case_id",
    "category",
    "dataset",
    "question",
    "required_operations",
    "required_evidence_values",
    "forbidden_claims",
    "expected_status",
    "v01_plan",
}
SUPPORTED_CHECKS = {
    "coerced_numeric_sum",
    "deduplicated_row_count",
    "duplicate_row_count",
    "group_mean",
    "group_ratio",
    "group_sum",
    "invalid_date_count",
    "invalid_numeric_count",
    "iqr_outliers",
    "missing_count",
    "numeric_max",
    "numeric_mean",
    "numeric_sum",
    "pearson",
    "period_change",
    "period_mean",
    "period_sum",
    "row_count",
    "value_count",
}
V02_SUPPORTED_REQUIREMENTS = {
    "correlation",
    "derived_metric",
    "describe",
    "distribution",
    "filter_rows",
    "groupby_aggregate",
    "missing_values",
    "multi_aggregate",
    "outlier_iqr",
    "period_compare",
    "pivot_table",
    "render_bar",
    "render_box",
    "render_histogram",
    "render_line",
    "render_scatter",
    "time_trend",
    "top_k",
    "value_counts",
}


class EvalValidationError(ValueError):
    """Raised when a committed evaluation asset is inconsistent."""


@dataclass(frozen=True)
class EvaluationSummary:
    """Small machine-readable summary printed by the offline runner."""

    case_count: int
    assertion_count: int
    dataset_count: int
    category_counts: dict[str, int]
    v01_representable_case_count: int
    v01_offline_capability_completion_rate: float
    v02_operation_covered_case_count: int
    v02_offline_operation_coverage_rate: float
    deterministic_numeric_accuracy: float
    v02_release_case_count: int
    v02_release_assertion_count: int
    v02_release_operations: list[str]
    live_planner_success_rate: None = None
    live_end_to_end_success_rate: None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_frame(name: str) -> pd.DataFrame:
    path = (DATA_ROOT / name).resolve()
    if path.parent != DATA_ROOT.resolve() or not path.is_file():
        raise EvalValidationError(f"Dataset is not a committed eval file: {name}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    raise EvalValidationError(f"Unsupported eval dataset format: {suffix}")


def _load_cases() -> list[dict[str, Any]]:
    payload = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 30:
        raise EvalValidationError("The case manifest must contain at least 30 cases.")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_case in payload:
        if not isinstance(raw_case, dict) or set(raw_case) != CASE_KEYS:
            raise EvalValidationError("Every case must contain exactly the documented fields.")
        case = dict(raw_case)
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise EvalValidationError(f"Invalid or duplicate case_id: {case_id!r}")
        seen_ids.add(case_id)
        if case["category"] not in CATEGORIES:
            raise EvalValidationError(f"Unknown category in {case_id}: {case['category']!r}")
        if case["expected_status"] != "supported":
            raise EvalValidationError(f"Unexpected expected_status in {case_id}.")
        if not isinstance(case["question"], str) or not case["question"].strip():
            raise EvalValidationError(f"Question is empty in {case_id}.")
        if not isinstance(case["required_operations"], list) or not case["required_operations"]:
            raise EvalValidationError(f"required_operations is empty in {case_id}.")
        unknown_operations = sorted(set(case["required_operations"]) - V02_SUPPORTED_REQUIREMENTS)
        if unknown_operations:
            raise EvalValidationError(
                f"Unsupported v0.2 requirements in {case_id}: {unknown_operations}."
            )
        if not isinstance(case["forbidden_claims"], list) or not case["forbidden_claims"]:
            raise EvalValidationError(f"forbidden_claims is empty in {case_id}.")
        checks = case["required_evidence_values"]
        if not isinstance(checks, list) or not checks:
            raise EvalValidationError(f"required_evidence_values is empty in {case_id}.")
        for check in checks:
            if not isinstance(check, dict) or check.get("check") not in SUPPORTED_CHECKS:
                raise EvalValidationError(f"Unknown oracle check in {case_id}: {check!r}")
            if "expected" not in check:
                raise EvalValidationError(f"Oracle check lacks expected value in {case_id}.")
        _load_frame(str(case["dataset"]))
        cases.append(case)

    category_counts = Counter(str(case["category"]) for case in cases)
    missing_categories = CATEGORIES - set(category_counts)
    if missing_categories:
        raise EvalValidationError(f"Case categories are missing: {sorted(missing_categories)}")
    return cases


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series[Any]:
    if column not in frame.columns:
        raise EvalValidationError(f"Unknown oracle column: {column}")
    return pd.to_numeric(frame[column], errors="coerce")


def _period_values(frame: pd.DataFrame, check: dict[str, Any]) -> pd.Series[Any]:
    time_column = str(check["time_column"])
    if time_column not in frame.columns:
        raise EvalValidationError(f"Unknown oracle time column: {time_column}")
    dates = pd.to_datetime(frame[time_column], errors="coerce")
    periods = dates.dt.to_period("M").astype("string")
    return _numeric(frame, str(check["column"]))[periods == str(check["period"])]


def _oracle_value(frame: pd.DataFrame, check: dict[str, Any]) -> Any:
    kind = str(check["check"])
    if kind == "row_count":
        return len(frame)
    if kind == "deduplicated_row_count":
        return len(frame.drop_duplicates())
    if kind == "duplicate_row_count":
        return int(frame.duplicated().sum())
    if kind == "missing_count":
        return int(frame[str(check["column"])].isna().sum())
    if kind == "numeric_sum":
        return float(_numeric(frame, str(check["column"])).sum())
    if kind == "numeric_mean":
        return float(_numeric(frame, str(check["column"])).mean())
    if kind == "numeric_max":
        return float(_numeric(frame, str(check["column"])).max())
    if kind in {"group_sum", "group_mean", "group_ratio"}:
        selected = frame[frame[str(check["group_by"])] == check["group"]]
        if kind == "group_ratio":
            numerator = _numeric(selected, str(check["numerator"])).sum()
            denominator = _numeric(selected, str(check["denominator"])).sum()
            return float(numerator / denominator)
        values = _numeric(selected, str(check["column"]))
        return float(values.sum() if kind == "group_sum" else values.mean())
    if kind == "value_count":
        return int((frame[str(check["column"])] == check["value"]).sum())
    if kind == "invalid_numeric_count":
        original = frame[str(check["column"])]
        return int((pd.to_numeric(original, errors="coerce").isna() & original.notna()).sum())
    if kind == "coerced_numeric_sum":
        return float(_numeric(frame, str(check["column"])).sum())
    if kind == "invalid_date_count":
        original = frame[str(check["column"])]
        return int((pd.to_datetime(original, errors="coerce").isna() & original.notna()).sum())
    if kind == "iqr_outliers":
        values = _numeric(frame, str(check["column"])).dropna()
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        return sorted(float(value) for value in values[(values < lower) | (values > upper)])
    if kind == "period_sum":
        return float(_period_values(frame, check).sum())
    if kind == "period_mean":
        return float(_period_values(frame, check).mean())
    if kind == "period_change":
        first_check = {**check, "period": check["period_a"]}
        second_check = {**check, "period": check["period_b"]}
        first = float(_period_values(frame, first_check).sum())
        second = float(_period_values(frame, second_check).sum())
        return second - first if check["measure"] == "absolute" else (second - first) / first
    if kind == "pearson":
        left = _numeric(frame, str(check["column_a"]))
        right = _numeric(frame, str(check["column_b"]))
        return float(left.corr(right))
    raise EvalValidationError(f"Unsupported oracle check: {kind}")


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, float) and isinstance(expected, (int, float)):
        return math.isclose(actual, float(expected), rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _values_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _run_v02_release_cases() -> tuple[int, int, list[str]]:
    """Execute committed Phase E workflows against production validators and executors."""
    from hy3_data_analyst_mcp.analysis.quality import prepare_analysis_data
    from hy3_data_analyst_mcp.analysis.workflow_executor import execute_workflow
    from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
    from hy3_data_analyst_mcp.analysis.workflow_validator import (
        DatasetSchema,
        validate_workflow,
    )
    from hy3_data_analyst_mcp.data.profiler import profile_dataset

    payload = json.loads(RELEASE_CASE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise EvalValidationError("The v0.2 release case manifest must be a non-empty list.")
    seen: set[str] = set()
    assertion_count = 0
    operations: set[str] = set()
    for raw_case in payload:
        if not isinstance(raw_case, dict) or set(raw_case) != {
            "case_id",
            "dataset",
            "workflow",
            "checks",
        }:
            raise EvalValidationError("Every v0.2 release case has an invalid shape.")
        case_id = str(raw_case["case_id"])
        if not case_id or case_id in seen:
            raise EvalValidationError(f"Invalid or duplicate v0.2 release case: {case_id!r}")
        seen.add(case_id)
        dataset = str(raw_case["dataset"])
        source_path = (DATA_ROOT / dataset).resolve()
        frame = _load_frame(dataset)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=0)
        schema = DatasetSchema.from_profile(profile)
        workflow = AnalysisWorkflow.model_validate(raw_case["workflow"])
        validate_workflow(workflow, schema)
        prepared = prepare_analysis_data(frame, workflow, schema)
        execution = execute_workflow(
            prepared.frame,
            workflow,
            source_file_name=source_path.name,
            dataset_schema=prepared.dataset_schema,
            quality_actions=prepared.quality_actions,
        )
        operations.update(step.operation for step in workflow.steps)
        primary = next(
            item
            for item in execution.evidence_ledger.items
            if item.step_id == workflow.primary_step_id
        )
        records = primary.model_dump(mode="json")["records"]
        checks = raw_case["checks"]
        if not isinstance(checks, list) or not checks:
            raise EvalValidationError(f"Release checks are empty in {case_id}.")
        for check in checks:
            if not isinstance(check, dict) or "expected" not in check:
                raise EvalValidationError(f"Invalid release check in {case_id}: {check!r}")
            actual = _release_check_value(records, check, case_id)
            if not _values_equal(actual, check["expected"]):
                raise EvalValidationError(
                    f"{case_id} {check.get('check')} expected {check['expected']!r}, "
                    f"got {actual!r}."
                )
            assertion_count += 1
    return len(payload), assertion_count, sorted(operations)


def _release_check_value(records: list[dict[str, Any]], check: dict[str, Any], case_id: str) -> Any:
    kind = check.get("check")
    if kind in {"record_field", "nested_field", "nested_count_sum"}:
        index = int(check["record"])
        try:
            record = records[index]
            value = record[str(check["field"])]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise EvalValidationError(f"Invalid record check in {case_id}.") from exc
        if kind == "record_field":
            return value
        if kind == "nested_field":
            if not isinstance(value, dict):
                raise EvalValidationError(f"Expected an object in {case_id}.")
            return value[str(check["key"])]
        if not isinstance(value, list):
            raise EvalValidationError(f"Expected a list in {case_id}.")
        return sum(int(item["count"]) for item in value)
    if kind == "matched_record_field":
        match = check.get("match")
        if not isinstance(match, dict) or not match:
            raise EvalValidationError(f"Invalid record match in {case_id}.")
        matched = [
            record
            for record in records
            if all(record.get(str(key)) == value for key, value in match.items())
        ]
        if len(matched) != 1:
            raise EvalValidationError(
                f"Expected one matched record in {case_id}, found {len(matched)}."
            )
        return matched[0][str(check["field"])]
    raise EvalValidationError(f"Unsupported release check in {case_id}: {kind!r}")


def _capture_current_v01(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from hy3_data_analyst_mcp.analysis.executor import execute_plan
    from hy3_data_analyst_mcp.analysis.models import AnalysisPlan, validate_plan_columns

    results: list[dict[str, Any]] = []
    representable = 0
    for case in cases:
        raw_plan = case["v01_plan"]
        if raw_plan is None:
            results.append(
                {
                    "case_id": case["case_id"],
                    "status": "unsupported",
                    "reason": (
                        "The complete request is not representable by one v0.1 analysis operation."
                    ),
                }
            )
            continue
        frame = _load_frame(str(case["dataset"]))
        plan = AnalysisPlan.model_validate(raw_plan)
        validate_plan_columns(plan, [str(column) for column in frame.columns])
        evidence = execute_plan(frame, plan)
        representable += 1
        results.append(
            {
                "case_id": case["case_id"],
                "status": "ok",
                "operation": plan.operation,
                "evidence_records": evidence.model_dump(mode="json")["records"],
                "evidence_warnings": evidence.warnings,
            }
        )

    dataset_names = sorted({str(case["dataset"]) for case in cases})
    return {
        "schema_version": "1.0",
        "product_version": "0.1.0",
        "captured_on": "2026-07-25",
        "measurement_scope": "offline deterministic executor; no Hy3 API calls",
        "case_manifest_sha256": _sha256(CASE_PATH),
        "dataset_sha256": {name: _sha256(DATA_ROOT / name) for name in dataset_names},
        "metrics": {
            "total_case_count": len(cases),
            "v01_representable_case_count": representable,
            "offline_capability_completion_rate": representable / len(cases),
            "deterministic_execution_success_rate": 1.0 if representable else 0.0,
            "stable_evidence_id_reference_rate": 0.0,
            "planner_success_rate": None,
            "end_to_end_success_rate": None,
            "model_metrics_note": (
                "Planner and end-to-end rates require an explicitly enabled live run."
            ),
        },
        "results": results,
    }


def run_evaluation(*, verify_current_v01: bool = True) -> EvaluationSummary:
    """Run exact offline oracle assertions and validate the committed v0.1 snapshot."""
    cases = _load_cases()
    assertion_count = 0
    frames: dict[str, pd.DataFrame] = {}
    for case in cases:
        dataset = str(case["dataset"])
        frame = frames.setdefault(dataset, _load_frame(dataset))
        for check in case["required_evidence_values"]:
            actual = _oracle_value(frame, check)
            if not _values_equal(actual, check["expected"]):
                raise EvalValidationError(
                    f"{case['case_id']} {check['check']} expected {check['expected']!r}, "
                    f"got {actual!r}."
                )
            assertion_count += 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = _capture_current_v01(cases)
    if baseline["case_manifest_sha256"] != _sha256(CASE_PATH):
        raise EvalValidationError("The v0.1 baseline does not match the case manifest hash.")
    expected_hashes = {
        name: _sha256(DATA_ROOT / name) for name in sorted({str(case["dataset"]) for case in cases})
    }
    if baseline["dataset_sha256"] != expected_hashes:
        raise EvalValidationError("The v0.1 baseline does not match the eval dataset hashes.")
    if verify_current_v01 and baseline != current:
        raise EvalValidationError(
            "The current v0.1-compatible executor differs from the frozen baseline."
        )

    category_counts = Counter(str(case["category"]) for case in cases)
    metrics = baseline["metrics"]
    operation_covered = sum(
        set(case["required_operations"]) <= V02_SUPPORTED_REQUIREMENTS for case in cases
    )
    release_case_count, release_assertion_count, release_operations = _run_v02_release_cases()
    return EvaluationSummary(
        case_count=len(cases),
        assertion_count=assertion_count,
        dataset_count=len(frames),
        category_counts=dict(sorted(category_counts.items())),
        v01_representable_case_count=int(metrics["v01_representable_case_count"]),
        v01_offline_capability_completion_rate=float(metrics["offline_capability_completion_rate"]),
        v02_operation_covered_case_count=operation_covered,
        v02_offline_operation_coverage_rate=operation_covered / len(cases),
        deterministic_numeric_accuracy=1.0,
        v02_release_case_count=release_case_count,
        v02_release_assertion_count=release_assertion_count,
        v02_release_operations=release_operations,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-v01-baseline",
        action="store_true",
        help="Print a freshly captured v0.1 baseline to stdout without writing files.",
    )
    parser.add_argument(
        "--skip-current-v01-check",
        action="store_true",
        help="Validate frozen assets without importing the current production executor.",
    )
    args = parser.parse_args()
    cases = _load_cases()
    if args.print_v01_baseline:
        print(json.dumps(_capture_current_v01(cases), ensure_ascii=False, indent=2))
        return 0
    summary = run_evaluation(verify_current_v01=not args.skip_current_v01_check)
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
