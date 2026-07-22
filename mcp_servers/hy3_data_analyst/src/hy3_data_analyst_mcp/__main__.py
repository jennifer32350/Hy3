"""Console entry point for the stdio MCP server."""

from hy3_data_analyst_mcp.server import mcp


def main() -> None:
    """Run the Hy3 Data Analyst MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
