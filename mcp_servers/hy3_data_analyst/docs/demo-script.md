# Demo script

1. Install the wheel and set `HY3_API_KEY`, `HY3_BASE_URL`, `HY3_MODEL`, and an absolute `HY3_DATA_DIR`.
2. Add the CodeBuddy or Cursor MCP template and reload the client.
3. Confirm that all three tools are discovered.
4. Ask: “Inspect sales.csv, compare regional revenue and profit, identify anomalies, and recommend two charts.”
5. Record calls to `inspect_dataset`, `analyze_dataset`, and `suggest_visualization` in that order.
6. Before publishing, check that no API key, personal path, notification, or unrelated window is visible.

The recording remains a manual phase-L deliverable because it requires authenticated clients and a real Hy3
endpoint. Compress the final capture to a readable GIF only after reviewing every frame for secrets.
