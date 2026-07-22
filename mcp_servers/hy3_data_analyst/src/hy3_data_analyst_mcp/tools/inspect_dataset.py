"""Dataset inspection MCP boundary."""

from typing import Any

from hy3_data_analyst_mcp.config import load_settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.data.profiler import MAX_SAMPLE_ROWS, profile_dataset
from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import Hy3DataAnalystError


async def inspect_dataset(
    file_path: str,
    encoding: str = "utf-8",
    sample_rows: int = 5,
) -> dict[str, Any]:
    """Safely inspect a local CSV, JSON, or JSONL dataset without calling Hy3.

    Args:
        file_path: Path to a dataset under the configured allowed data directory.
        encoding: Text encoding used to read the dataset.
        sample_rows: Number of safe sample rows to include, from 0 through 20.
    """
    if not 0 <= sample_rows <= MAX_SAMPLE_ROWS:
        return {
            "error": "InvalidToolArgument",
            "message": f"sample_rows must be between 0 and {MAX_SAMPLE_ROWS}.",
            "hint": "Choose a sample_rows value in the allowed range and retry.",
        }
    try:
        settings = load_settings()
        source_path = resolve_data_file(
            file_path,
            allowed_directory=settings.data_dir,
            max_file_size_mb=settings.max_file_size_mb,
        )
        frame = load_dataset(file_path, settings=settings, encoding=encoding)
        profile = profile_dataset(frame, source_path=source_path, sample_rows=sample_rows)
        return profile.model_dump(mode="json")
    except Hy3DataAnalystError as exc:
        return exc.as_dict()
