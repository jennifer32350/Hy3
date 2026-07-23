"""Hy3-backed constrained analysis planning with one repair attempt."""

import json

from hy3_data_analyst_mcp.analysis.models import AnalysisPlan, validate_plan_columns
from hy3_data_analyst_mcp.analysis.prompts import PLANNER_SYSTEM_PROMPT, REPAIR_SYSTEM_PROMPT
from hy3_data_analyst_mcp.errors import Hy3ResponseError, InvalidAnalysisPlanError
from hy3_data_analyst_mcp.hy3_client import Hy3Client
from hy3_data_analyst_mcp.models import DatasetProfile


class AnalysisPlanner:
    """Ask Hy3 for a schema-constrained plan and validate dataset columns."""

    def __init__(self, client: Hy3Client) -> None:
        self._client = client

    async def create_plan(
        self,
        question: str,
        profile: DatasetProfile,
        *,
        reasoning_effort: str,
    ) -> AnalysisPlan:
        context = _planning_context(question, profile)
        try:
            plan = await self._client.complete_structured(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=AnalysisPlan,
                reasoning_effort=reasoning_effort,
            )
            validate_plan_columns(plan, profile.column_names)
            return plan
        except (Hy3ResponseError, ValueError) as first_error:
            try:
                repaired = await self._client.complete_structured(
                    system_prompt=REPAIR_SYSTEM_PROMPT,
                    user_prompt=(
                        f"Allowed columns and request:\n{context}\nValidation error: {first_error}"
                    ),
                    response_model=AnalysisPlan,
                    reasoning_effort=reasoning_effort,
                )
                validate_plan_columns(repaired, profile.column_names)
                return repaired
            except (Hy3ResponseError, ValueError) as exc:
                raise InvalidAnalysisPlanError(
                    "Hy3 could not produce a valid constrained analysis plan "
                    "after one repair attempt.",
                    "Rephrase the question using exact dataset column names and retry.",
                ) from exc


def _planning_context(question: str, profile: DatasetProfile) -> str:
    columns = [
        {
            "name": column.name,
            "semantic_type": column.semantic_type,
            "statistics": column.statistics,
        }
        for column in profile.columns
    ]
    return json.dumps(
        {"question": question, "row_count": profile.row_count, "columns": columns},
        ensure_ascii=False,
    )
