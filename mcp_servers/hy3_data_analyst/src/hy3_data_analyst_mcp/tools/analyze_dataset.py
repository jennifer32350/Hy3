"""Natural-language dataset analysis MCP boundary."""

from typing import Any, Literal

from hy3_data_analyst_mcp.analysis.service import AnalysisService
from hy3_data_analyst_mcp.analysis.workflow_models import QualityPolicy
from hy3_data_analyst_mcp.config import load_settings
from hy3_data_analyst_mcp.errors import Hy3DataAnalystError

MAX_QUESTION_LENGTH = 4000


async def analyze_dataset(
    file_path: str,
    question: str,
    reasoning_effort: Literal["low", "high"] = "high",
    output_mode: Literal["concise", "detailed"] = "detailed",
    max_steps: int = 6,
    quality_policy: QualityPolicy | None = None,
) -> dict[str, Any]:
    """Answer a natural-language question using Hy3 planning and Pandas calculations.

    Args:
        file_path: Path to a dataset under the configured allowed data directory.
        question: Natural-language analysis question to answer from the dataset.
        reasoning_effort: Hy3 reasoning effort, either ``low`` or ``high``.
        output_mode: Return a concise or detailed bounded Evidence Ledger.
        max_steps: Maximum workflow steps, from 1 through the hard limit of 6.
        quality_policy: Explicit missing, duplicate, numeric, and date handling policy.
    """
    normalized_question = question.strip()
    if not normalized_question or len(normalized_question) > MAX_QUESTION_LENGTH:
        return {
            "error": "InvalidToolArgument",
            "message": f"question must contain between 1 and {MAX_QUESTION_LENGTH} characters.",
            "hint": "Provide a concise analysis question and retry.",
        }
    if not 1 <= max_steps <= 6:
        return {
            "error": "InvalidToolArgument",
            "message": "max_steps must be between 1 and 6.",
            "hint": "Choose a bounded workflow size and retry.",
        }
    try:
        settings = load_settings()
        return await AnalysisService(settings).analyze(
            file_path,
            normalized_question,
            reasoning_effort=reasoning_effort,
            max_steps=max_steps,
            output_mode=output_mode,
            quality_policy=quality_policy,
        )
    except Hy3DataAnalystError as exc:
        return exc.as_dict()
