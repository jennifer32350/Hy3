"""Hy3-backed structured visualization recommendations with field validation."""

import json
from pathlib import Path
from typing import Any

from hy3_data_analyst_mcp.analysis.models import (
    VisualizationSuggestions,
    validate_visualization_columns,
)
from hy3_data_analyst_mcp.analysis.prompts import (
    VISUALIZATION_REPAIR_PROMPT,
    VISUALIZATION_SYSTEM_PROMPT,
)
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import Hy3ResponseError, InvalidAnalysisPlanError
from hy3_data_analyst_mcp.hy3_client import Hy3Client


class VisualizationService:
    """Create bounded, validated chart descriptions without rendering files."""

    def __init__(self, settings: Settings, *, client: Hy3Client | None = None) -> None:
        self._settings = settings
        self._client = client or Hy3Client(settings)

    async def suggest(
        self,
        file_path: str | Path,
        goal: str,
        *,
        max_suggestions: int,
    ) -> dict[str, Any]:
        source_path = resolve_data_file(
            file_path,
            allowed_directory=self._settings.data_dir,
            max_file_size_mb=self._settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=self._settings)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=0)
        context = json.dumps(
            {
                "goal": goal,
                "max_suggestions": max_suggestions,
                "columns": [
                    {"name": item.name, "semantic_type": item.semantic_type}
                    for item in profile.columns
                ],
            },
            ensure_ascii=False,
        )
        result = await self._generate_with_repair(context, profile.column_names)
        return {
            "status": "ok",
            "suggestions": [
                suggestion.model_dump(mode="json")
                for suggestion in result.suggestions[:max_suggestions]
            ],
        }

    async def _generate_with_repair(
        self, context: str, columns: list[str]
    ) -> VisualizationSuggestions:
        try:
            result = await self._client.complete_structured(
                system_prompt=VISUALIZATION_SYSTEM_PROMPT,
                user_prompt=context,
                response_model=VisualizationSuggestions,
            )
            validate_visualization_columns(result, columns)
            return result
        except (Hy3ResponseError, ValueError) as first_error:
            try:
                repaired = await self._client.complete_structured(
                    system_prompt=VISUALIZATION_REPAIR_PROMPT,
                    user_prompt=f"{context}\nValidation error: {first_error}",
                    response_model=VisualizationSuggestions,
                )
                validate_visualization_columns(repaired, columns)
                return repaired
            except (Hy3ResponseError, ValueError) as exc:
                raise InvalidAnalysisPlanError(
                    "Hy3 could not produce valid visualization suggestions "
                    "after one repair attempt.",
                    "Rephrase the goal using exact dataset column names and retry.",
                ) from exc
