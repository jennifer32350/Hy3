"""End-to-end orchestration for Hy3-planned deterministic analysis."""

import json
import time
from pathlib import Path
from typing import Any

from hy3_data_analyst_mcp.analysis.executor import execute_plan
from hy3_data_analyst_mcp.analysis.models import EvidenceInterpretation
from hy3_data_analyst_mcp.analysis.planner import AnalysisPlanner
from hy3_data_analyst_mcp.analysis.prompts import INTERPRETER_SYSTEM_PROMPT
from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.hy3_client import Hy3Client


class AnalysisService:
    """Load, profile, plan, execute, and explain one dataset question."""

    def __init__(self, settings: Settings, *, client: Hy3Client | None = None) -> None:
        self._settings = settings
        self._client = client or Hy3Client(settings)

    async def analyze(
        self,
        file_path: str | Path,
        question: str,
        *,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        started = time.monotonic()
        source_path = resolve_data_file(
            file_path,
            allowed_directory=self._settings.data_dir,
            max_file_size_mb=self._settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=self._settings)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=3)
        plan = await AnalysisPlanner(self._client).create_plan(
            question, profile, reasoning_effort=reasoning_effort
        )
        evidence = execute_plan(frame, plan)
        interpretation = await self._client.complete_structured(
            system_prompt=INTERPRETER_SYSTEM_PROMPT,
            user_prompt=json.dumps(
                {
                    "question": question,
                    "plan": plan.model_dump(),
                    "evidence": evidence.model_dump(),
                },
                ensure_ascii=False,
                default=str,
            ),
            response_model=EvidenceInterpretation,
            reasoning_effort=reasoning_effort,
        )
        return {
            "status": "ok",
            "plan": plan.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "conclusion": interpretation.conclusion,
            "evidence_references": interpretation.evidence_references,
            "limitations": interpretation.limitations,
            "warnings": evidence.warnings,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }
