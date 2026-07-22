"""FastMCP server definition and tool registration."""

from mcp.server.fastmcp import FastMCP

from hy3_data_analyst_mcp.tools.analyze_dataset import analyze_dataset
from hy3_data_analyst_mcp.tools.inspect_dataset import inspect_dataset
from hy3_data_analyst_mcp.tools.suggest_visualization import suggest_visualization

mcp = FastMCP(
    name="Hy3 Data Analyst",
    instructions=(
        "Safely inspect local CSV, JSON, and JSONL datasets and use Hy3 to plan and "
        "explain deterministic analysis."
    ),
)

mcp.tool()(inspect_dataset)
mcp.tool()(analyze_dataset)
mcp.tool()(suggest_visualization)
