# Security and privacy

- Files must resolve inside `HY3_DATA_DIR`; traversal, out-of-bound symlinks, hidden files, unsupported
  extensions, non-files, oversized files, and oversized tables are rejected.
- API keys come only from the process environment and are not logged.
- With a remote endpoint, schema, bounded statistics, a few profile samples, and deterministic evidence may
  leave the machine. Complete files are not sent by default.
- Cell text is untrusted data. Prompts explicitly forbid following instructions contained in data.
- Hy3 output is constrained by Pydantic schemas and exact column validation.
- v0.2 workflow schemas reject extra fields, undeclared operations, forward or non-View dependencies,
  unsafe filter/derived shapes, invented columns, incompatible strict types, and resource-limit overruns.
- Evidence and report schemas accept base file names only and enforce bounded records, JSON nesting,
  stable IDs, row accounting, and Evidence references.
- Phase C executes only 11 alpha whitelist operations. Filter conditions are structured, literal
  `contains` uses `regex=False`, and empty dependent Views fail closed with a stable step ID.
- Every internal View is a DataFrame copy. Evidence serialization limits never alter the full bounded
  DataFrame used for deterministic calculations, and source DataFrames/files are not modified.
- The Phase C planner gets one repair attempt, is limited to the non-destructive default quality policy,
  and cannot select Phase E/F operations before those stages are implemented.
- The executor has a fixed operation whitelist and never runs generated Python, Shell, SQL, or expressions.
- stdio stdout is reserved for JSON-RPC; diagnostics use stderr and omit raw datasets and credentials.
