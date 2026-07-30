"""Visualization rendering MCP boundary."""

from __future__ import annotations

import base64
import json

from mcp.types import ImageContent, TextContent

from hy3_data_analyst_mcp.analysis.visualization import VisualizationRenderService
from hy3_data_analyst_mcp.analysis.visualization_executor import (
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
)
from hy3_data_analyst_mcp.analysis.workflow_models import QualityPolicy
from hy3_data_analyst_mcp.config import load_settings
from hy3_data_analyst_mcp.errors import Hy3DataAnalystError
from hy3_data_analyst_mcp.tools.suggest_visualization import MAX_GOAL_LENGTH


async def render_visualization(
    file_path: str,
    goal: str,
    max_charts: int = 2,
    width: int = 1200,
    height: int = 720,
    quality_policy: QualityPolicy | None = None,
) -> list[TextContent | ImageContent]:
    """Plan and render Evidence-bound PNG charts from a local dataset.

    Args:
        file_path: Path to a dataset under the configured allowed data directory.
        goal: Analysis or communication goal for the charts.
        max_charts: Maximum charts to render, from 1 through 3.
        width: PNG width in pixels, from 480 through 1920.
        height: PNG height in pixels, from 320 through 1080.
        quality_policy: Explicit missing, duplicate, numeric, and date handling policy.
    """
    normalized_goal = goal.strip()
    invalid = _argument_error(normalized_goal, max_charts, width, height)
    if invalid is not None:
        return [TextContent(type="text", text=json.dumps(invalid, ensure_ascii=False))]
    try:
        settings = load_settings()
        if max_charts > settings.max_charts:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "InvalidToolArgument",
                            "message": (
                                f"max_charts exceeds the configured limit of {settings.max_charts}."
                            ),
                            "hint": "Choose a max_charts value within HY3_MAX_CHARTS.",
                        },
                        ensure_ascii=False,
                    ),
                )
            ]
        charts = await VisualizationRenderService(settings).render(
            file_path,
            normalized_goal,
            max_charts=max_charts,
            width=width,
            height=height,
            quality_policy=quality_policy,
        )
    except Hy3DataAnalystError as exc:
        return [TextContent(type="text", text=json.dumps(exc.as_dict(), ensure_ascii=False))]

    content: list[TextContent | ImageContent] = []
    for index, chart in enumerate(charts, start=1):
        metadata = {
            "status": "ok",
            "chart_index": index,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "byte_size": len(chart.png),
            "output_path": str(chart.output_path),
            "evidence": chart.evidence,
            "quality": chart.quality,
        }
        content.extend(
            [
                TextContent(
                    type="text",
                    text=json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                ),
                ImageContent(
                    type="image",
                    data=base64.b64encode(chart.png).decode("ascii"),
                    mimeType="image/png",
                ),
            ]
        )
    return content


def _argument_error(goal: str, max_charts: int, width: int, height: int) -> dict[str, str] | None:
    if not goal or len(goal) > MAX_GOAL_LENGTH:
        message = f"goal must contain between 1 and {MAX_GOAL_LENGTH} characters."
    elif not 1 <= max_charts <= 3:
        message = "max_charts must be between 1 and 3."
    elif not MIN_WIDTH <= width <= MAX_WIDTH:
        message = f"width must be between {MIN_WIDTH} and {MAX_WIDTH}."
    elif not MIN_HEIGHT <= height <= MAX_HEIGHT:
        message = f"height must be between {MIN_HEIGHT} and {MAX_HEIGHT}."
    else:
        return None
    return {
        "error": "InvalidToolArgument",
        "message": message,
        "hint": "Choose bounded visualization arguments and retry.",
    }
