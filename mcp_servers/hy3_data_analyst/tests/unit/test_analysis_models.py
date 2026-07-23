"""Tests for constrained analysis plan schemas."""

import pytest
from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.models import AnalysisPlan, validate_plan_columns


def test_groupby_plan_requires_complete_arguments() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(operation="groupby_aggregate", rationale="compare groups")


def test_plan_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(operation="describe", rationale="summary", code="print(1)")  # type: ignore[call-arg]


def test_plan_rejects_invented_columns() -> None:
    plan = AnalysisPlan(operation="top_k", target_columns=["invented"], rationale="rank")
    with pytest.raises(ValueError, match="unknown columns"):
        validate_plan_columns(plan, ["revenue"])


def test_hy3_json_schema_requires_every_plan_field() -> None:
    assert set(AnalysisPlan.model_json_schema()["required"]) == {
        "operation",
        "target_columns",
        "group_by",
        "aggregation",
        "sort_order",
        "limit",
        "time_column",
        "rationale",
    }
