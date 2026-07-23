"""Visualization suggestion MCP boundary."""

from typing import Any

from hy3_data_analyst_mcp.analysis.visualization import VisualizationService
from hy3_data_analyst_mcp.config import load_settings
from hy3_data_analyst_mcp.errors import Hy3DataAnalystError

MAX_GOAL_LENGTH = 4000


async def suggest_visualization(
    file_path: str,
    goal: str,
    max_suggestions: int = 3,
) -> dict[str, Any]:
    """Suggest chart specifications for a dataset and analysis goal.

    Args:
        file_path: Path to a dataset under the configured allowed data directory.
        goal: Analysis or communication goal for the visualizations.
        max_suggestions: Maximum number of chart suggestions, from 1 through 5.
    """
    normalized_goal = goal.strip()
    if not normalized_goal or len(normalized_goal) > MAX_GOAL_LENGTH:
        return {
            "error": "InvalidToolArgument",
            "message": f"goal must contain between 1 and {MAX_GOAL_LENGTH} characters.",
            "hint": "Provide a concise visualization goal and retry.",
        }
    if not 1 <= max_suggestions <= 5:
        return {
            "error": "InvalidToolArgument",
            "message": "max_suggestions must be between 1 and 5.",
            "hint": "Choose a max_suggestions value in the allowed range and retry.",
        }
    try:
        return await VisualizationService(load_settings()).suggest(
            file_path, normalized_goal, max_suggestions=max_suggestions
        )
    except Hy3DataAnalystError as exc:
        return exc.as_dict()
