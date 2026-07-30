"""Hy3-backed v0.2 workflow planning with exactly one repair attempt."""

from __future__ import annotations

import json

from pydantic import ValidationError

from hy3_data_analyst_mcp.analysis.prompts import (
    WORKFLOW_PLANNER_SYSTEM_PROMPT,
    WORKFLOW_REPAIR_SYSTEM_PROMPT,
)
from hy3_data_analyst_mcp.analysis.workflow_models import AnalysisWorkflow, QualityPolicy
from hy3_data_analyst_mcp.analysis.workflow_validator import DatasetSchema, validate_workflow
from hy3_data_analyst_mcp.errors import (
    Hy3ResponseError,
    Hy3StructuredOutputError,
    InvalidAnalysisWorkflowError,
)
from hy3_data_analyst_mcp.hy3_client import Hy3Client
from hy3_data_analyst_mcp.models import DatasetProfile

PHASE_E_ALLOWED_OPERATIONS = [
    "describe",
    "groupby_aggregate",
    "multi_aggregate",
    "aggregate_ratio",
    "top_k",
    "value_counts",
    "correlation",
    "time_trend",
    "period_compare",
    "missing_values",
    "distribution",
    "outlier_iqr",
    "pivot_table",
    "filter_rows",
    "derived_metric",
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
        quality_policy: QualityPolicy,
    ) -> AnalysisWorkflow:
        context = _planning_context(
            question,
            profile,
            max_steps=max_steps,
            quality_policy=quality_policy,
        )
        dataset = DatasetSchema.from_profile(profile)
        try:
            workflow = await self._client.complete_structured(
                system_prompt=WORKFLOW_PLANNER_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=AnalysisWorkflow,
                reasoning_effort=reasoning_effort,
            )
            _validate_phase_e_workflow(
                workflow,
                dataset,
                max_steps=max_steps,
                quality_policy=quality_policy,
            )
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
                _validate_phase_e_workflow(
                    repaired,
                    dataset,
                    max_steps=max_steps,
                    quality_policy=quality_policy,
                )
                return repaired
            except (Hy3ResponseError, InvalidAnalysisWorkflowError, ValueError) as exc:
                raise InvalidAnalysisWorkflowError(
                    "Hy3 could not produce a valid constrained workflow after one repair attempt.",
                    "Rephrase the question using exact dataset column names and supported "
                    "operations.",
                ) from exc


def _validate_phase_e_workflow(
    workflow: AnalysisWorkflow,
    dataset: DatasetSchema,
    *,
    max_steps: int,
    quality_policy: QualityPolicy,
) -> None:
    unsupported = [
        step for step in workflow.steps if step.operation not in PHASE_E_ALLOWED_OPERATIONS
    ]
    if unsupported:
        step = unsupported[0]
        raise InvalidAnalysisWorkflowError(
            f"Operation {step.operation} is not in the Phase E whitelist.",
            "Use an operation from the Phase E whitelist.",
            step_id=step.step_id,
        )
    if workflow.quality_policy != quality_policy:
        raise InvalidAnalysisWorkflowError(
            "The workflow quality policy does not match the requested policy.",
            "Copy requested_quality_policy exactly and retry.",
        )
    validate_workflow(workflow, dataset, max_steps=max_steps)


def _planning_context(
    question: str,
    profile: DatasetProfile,
    *,
    max_steps: int,
    quality_policy: QualityPolicy,
) -> str:
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
            "allowed_operations": PHASE_E_ALLOWED_OPERATIONS,
            "requested_quality_policy": quality_policy.model_dump(mode="json"),
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
        if isinstance(error.__cause__, ValidationError):
            details: list[str] = []
            for issue in error.__cause__.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:3]:
                location = ".".join(str(part) for part in issue["loc"]) or "workflow"
                details.append(f"{location}: {issue['msg']}")
            if details:
                return "Workflow schema validation failed: " + "; ".join(details)
        return "The model response did not satisfy the workflow schema."
    return "The workflow failed dataset-aware validation."
