"""Natural-language dataset analysis MCP boundary."""

from typing import Any, Literal


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
    del file_path, question, reasoning_effort
    return {
        "status": "not_implemented",
        "message": "Hy3-assisted analysis will be implemented in phases D and E.",
    }
