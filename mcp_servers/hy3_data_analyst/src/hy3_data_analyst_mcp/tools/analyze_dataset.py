"""Natural-language dataset analysis MCP boundary."""

from typing import Any, Literal

from hy3_data_analyst_mcp.analysis.service import AnalysisService
from hy3_data_analyst_mcp.config import load_settings
from hy3_data_analyst_mcp.errors import Hy3DataAnalystError

MAX_QUESTION_LENGTH = 4000


async def analyze_dataset(
    file_path: str,
    question: str,
    reasoning_effort: Literal["low", "high"] = "high",
) -> dict[str, Any]:
    """Answer a natural-language question using Hy3 planning and Pandas calculations.

    Args:
        file_path: Path to a dataset under the configured allowed data directory.
        question: Natural-language analysis question to answer from the dataset.
        reasoning_effort: Hy3 reasoning effort, either ``low`` or ``high``.
    """
    normalized_question = question.strip()
    if not normalized_question or len(normalized_question) > MAX_QUESTION_LENGTH:
        return {
            "error": "InvalidToolArgument",
            "message": f"question must contain between 1 and {MAX_QUESTION_LENGTH} characters.",
            "hint": "Provide a concise analysis question and retry.",
        }
    try:
        settings = load_settings()
        return await AnalysisService(settings).analyze(
            file_path,
            normalized_question,
            reasoning_effort=reasoning_effort,
        )
    except Hy3DataAnalystError as exc:
        return exc.as_dict()
