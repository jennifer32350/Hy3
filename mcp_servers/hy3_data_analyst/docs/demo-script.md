# Demo script

1. Install the v0.2 wheel and set `HY3_API_KEY`, `HY3_BASE_URL`, `HY3_MODEL`, an absolute
   `HY3_DATA_DIR`, and an existing local `HY3_OUTPUT_DIR`.
2. Add the CodeBuddy or Cursor MCP template and reload the client.
3. Confirm that exactly four tools are discovered, including `render_visualization`.
4. Ask: “Inspect sales.csv, compare regional revenue and profit, calculate profit margin, identify
   anomalies, and render two charts.”
5. Verify that the report cites Evidence IDs and visibly accounts for the missing record, duplicate row,
   and `profit=-900` anomaly.
6. Record calls to `inspect_dataset`, `analyze_dataset`, `suggest_visualization`, and
   `render_visualization`; confirm that the client displays returned PNG ImageContent.
7. Exercise one safe failure for an invalid path or derived metric and confirm the stable error response.
8. Before publishing, check that no API key, personal path, notification, or unrelated window is visible.

The recording remains a manual phase-L deliverable because it requires authenticated clients and a real Hy3
endpoint. Compress the final capture to a readable GIF only after reviewing every frame for secrets.
