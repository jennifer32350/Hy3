"""Hy3-backed v0.2 workflow planning with exactly one repair attempt."""

from __future__ import annotations

import json

from hy3_data_analyst_mcp.analysis.prompts import (
    WORKFLOW_PLANNER_SYSTEM_PROMPT,
    WORKFLOW_REPAIR_SYSTEM_PROMPT,
)
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema, validate_workflow
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    InvalidAnalysisWorkflowError,
)
from hy3_data_analyst_mcp.hy3_client import Hy3Client
from hy3_data_analyst_mcp.models import DatasetProfile

PHASE_C_ALLOWED_OPERATIONS = [
    "describe",
    "groupby_aggregate",
    "multi_aggregate",
    "top_k",
    "value_counts",
    "correlation",
    "time_trend",
    "period_compare",
    "missing_values",
    "outlier_iqr",
    "filter_rows",
]


class WorkflowPlanner:
    """Create and dataset-validate one bounded workflow, repairing at most once."""

    def __init__(self, client: Hy3Client) -> None:
        self._client = client

    async def create_workflow(
        self,
        question: str,
        profile: DatasetProfile,
        *,
        reasoning_effort: str,
        max_steps: int,
    ) -> AnalysisWorkflow:
        context = _planning_context(question, profile, max_steps=max_steps)
        dataset = DatasetSchema.from_profile(profile)
        try:
            workflow = await self._client.complete_structured(
                system_prompt=WORKFLOW_PLANNER_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=AnalysisWorkflow,
                reasoning_effort=reasoning_effort,
            )
            _validate_phase_c_workflow(workflow, dataset, max_steps=max_steps)
            return workflow
        except (Hy3ResponseError, InvalidAnalysisWorkflowError, ValueError) as first_error:
            try:
                repaired = await self._client.complete_structured(
                    system_prompt=WORKFLOW_REPAIR_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "planning_context": json.loads(context),
                            "validation_error": _safe_validation_message(first_error),
                        },
                        ensure_ascii=False,
                    ),
                    response_model=AnalysisWorkflow,
                    reasoning_effort=reasoning_effort,
                )
                _validate_phase_c_workflow(repaired, dataset, max_steps=max_steps)
                return repaired
            except (Hy3ResponseError, InvalidAnalysisWorkflowError, ValueError) as exc:
                raise InvalidAnalysisWorkflowError(
                    "Hy3 could not produce a valid constrained workflow after one repair attempt.",
                    "Rephrase the question using exact dataset column names and supported "
                    "operations.",
                ) from exc


def _validate_phase_c_workflow(
    workflow: AnalysisWorkflow,
    dataset: DatasetSchema,
    *,
    max_steps: int,
) -> None:
    unsupported = [
        step for step in workflow.steps if step.operation not in PHASE_C_ALLOWED_OPERATIONS
    ]
    if unsupported:
        step = unsupported[0]
        raise InvalidAnalysisWorkflowError(
            f"Operation {step.operation} is not available in v0.2-alpha Phase C.",
            "Use an operation from the Phase C whitelist.",
            step_id=step.step_id,
        )
    if workflow.quality_policy.model_dump() != {
        "missing": "keep",
        "duplicates": "keep",
        "numeric_conversion": "strict",
        "date_conversion": "coerce",
    }:
        raise InvalidAnalysisWorkflowError(
            "Phase C supports only the non-destructive default quality policy.",
            "Use missing=keep, duplicates=keep, numeric_conversion=strict, and "
            "date_conversion=coerce.",
        )
    validate_workflow(workflow, dataset, max_steps=max_steps)


def _planning_context(question: str, profile: DatasetProfile, *, max_steps: int) -> str:
    columns = [
        {
            "name": column.name,
            "pandas_dtype": column.pandas_dtype,
            "semantic_type": column.semantic_type,
            "missing_rate": column.missing_rate,
            "unique_count": column.unique_count,
            "statistics": column.statistics,
        }
        for column in profile.columns
    ]
    return json.dumps(
        {
            "question": question,
            "max_steps": max_steps,
            "allowed_operations": PHASE_C_ALLOWED_OPERATIONS,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "duplicate_row_count": profile.duplicate_row_count,
            "columns": columns,
        },
        ensure_ascii=False,
    )


def _safe_validation_message(error: Exception) -> str:
    if isinstance(error, InvalidAnalysisWorkflowError):
        return error.message
    if isinstance(error, Hy3ResponseError):
        return "The model response did not satisfy the workflow schema."
    return "The workflow failed dataset-aware validation."
