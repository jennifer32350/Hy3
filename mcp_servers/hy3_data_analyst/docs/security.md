# Security and privacy

- Files must resolve inside `HY3_DATA_DIR`; traversal, out-of-bound symlinks, hidden files, unsupported
  extensions, non-files, oversized files, and oversized tables are rejected.
- API keys come only from the process environment and are not logged.
- With a remote endpoint, schema, bounded statistics, a few profile samples, and deterministic evidence may
  leave the machine. Complete files are not sent by default.
- Cell text is untrusted data. Prompts explicitly forbid following instructions contained in data.
- Hy3 output is constrained by Pydantic schemas and exact column validation.
- The executor has a fixed operation whitelist and never runs generated Python, Shell, SQL, or expressions.
- stdio stdout is reserved for JSON-RPC; diagnostics use stderr and omit raw datasets and credentials.
