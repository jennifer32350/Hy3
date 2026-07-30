"""Tests for the reproducible Phase A evaluation baseline."""

import json
import subprocess
import sys
from pathlib import Path

CATEGORIES = {
    "basic_statistics",
    "composite_analysis",
    "trend",
    "anomaly",
    "quality",
    "visualization",
}


def test_phase_a_eval_assets_and_v01_baseline_are_reproducible() -> None:
    project_root = Path(__file__).parents[2]
    completed = subprocess.run(
        [sys.executable, str(project_root / "evals" / "run_evals.py")],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["case_count"] == 36
    assert summary["dataset_count"] == 4
    assert summary["assertion_count"] >= summary["case_count"]
    assert set(summary["category_counts"]) == CATEGORIES
    assert all(count == 6 for count in summary["category_counts"].values())
    assert 0 < summary["v01_representable_case_count"] < summary["case_count"]
    assert 0 < summary["v01_offline_capability_completion_rate"] < 1
    assert summary["v02_operation_covered_case_count"] == summary["case_count"]
    assert summary["v02_offline_operation_coverage_rate"] == 1.0
    assert summary["deterministic_numeric_accuracy"] == 1.0
    assert summary["v02_release_case_count"] == 3
    assert summary["v02_release_assertion_count"] == 9
    assert summary["v02_release_operations"] == [
        "derived_metric",
        "describe",
        "distribution",
        "pivot_table",
    ]
    assert summary["live_planner_success_rate"] is None
    assert summary["live_end_to_end_success_rate"] is None
