"""Tests for every deterministic whitelist executor."""

import pandas as pd
import pytest

from hy3_data_analyst_mcp.analysis.executor import execute_plan
from hy3_data_analyst_mcp.analysis.models import AnalysisPlan
from hy3_data_analyst_mcp.errors import UnsupportedAnalysisOperationError


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-15", "2026-02-01", "bad"],
            "region": ["East", "West", "East", "West"],
            "revenue": [10.0, 20.0, 30.0, 1000.0],
            "profit": [1.0, 2.0, None, 100.0],
            "note": ["a", "b", "c", "d"],
        }
    )


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        (
            AnalysisPlan(operation="describe", target_columns=["revenue"], rationale="summary"),
            "column",
        ),
        (
            AnalysisPlan(
                operation="groupby_aggregate",
                target_columns=["revenue"],
                group_by=["region"],
                aggregation="sum",
                rationale="groups",
            ),
            "region",
        ),
        (
            AnalysisPlan(operation="top_k", target_columns=["revenue"], limit=2, rationale="top"),
            "revenue",
        ),
        (
            AnalysisPlan(
                operation="correlation", target_columns=["revenue", "profit"], rationale="corr"
            ),
            "correlation",
        ),
        (
            AnalysisPlan(
                operation="time_trend",
                target_columns=["revenue"],
                time_column="date",
                aggregation="sum",
                rationale="trend",
            ),
            "date",
        ),
        (AnalysisPlan(operation="missing_values", rationale="quality"), "missing_count"),
        (
            AnalysisPlan(operation="outlier_iqr", target_columns=["revenue"], rationale="outliers"),
            "outlier_count",
        ),
    ],
)
def test_whitelisted_operations(frame: pd.DataFrame, plan: AnalysisPlan, expected: str) -> None:
    evidence = execute_plan(frame, plan)
    assert evidence.records
    assert expected in evidence.records[0]


def test_numeric_operation_rejects_text(frame: pd.DataFrame) -> None:
    plan = AnalysisPlan(operation="outlier_iqr", target_columns=["note"], rationale="bad type")
    with pytest.raises(UnsupportedAnalysisOperationError, match="numeric columns"):
        execute_plan(frame, plan)


def test_time_trend_rejects_invalid_date_column(frame: pd.DataFrame) -> None:
    plan = AnalysisPlan(
        operation="time_trend",
        target_columns=["revenue"],
        time_column="note",
        aggregation="sum",
        rationale="bad dates",
    )
    with pytest.raises(UnsupportedAnalysisOperationError, match="valid dates"):
        execute_plan(frame, plan)
