# Hy3 Data Analyst MCP

[中文说明](README.md)

Hy3 Data Analyst MCP is an installable local stdio MCP server for safe analysis of CSV, JSON, and
JSONL datasets. Hy3 plans bounded workflows and explains results; local Pandas/NumPy code performs
all deterministic calculations. The server never executes model-generated Python, SQL, shell
commands, formulas, or `DataFrame.query()` expressions.

## v0.2 status

The repository implementation covers the automatable scope of phases A through G:

- 36 offline evaluation questions across four synthetic, de-identified datasets, with 49 exact
  deterministic assertions and a frozen v0.1 baseline;
- strict 1–6 step workflow schemas, dataset-aware validation, immutable Views, and an Evidence
  Ledger with stable IDs and lineage;
- 14 whitelisted operations, including filters, multi-metric aggregation, period comparison,
  distributions, bounded pivots, and structured derived metrics;
- explicit missing-value, duplicate, numeric-conversion, and date-conversion policies applied only
  to in-memory copies, with full row and coercion accounting;
- structured concise/detailed reports with Evidence references, numeric grounding, confidence
  limits, correlation non-causality checks, and one bounded repair attempt;
- strict chart specifications, deterministic chart-data execution, and safe Matplotlib Agg PNG
  rendering for bar, line, scatter, histogram, and box charts;
- Windows and Ubuntu CI for Python 3.10–3.13 with an 85% coverage gate.

External release evidence still requires an authenticated Hy3 endpoint and user-controlled clients:
remote CI results, live Hy3 metrics, Cursor/CodeBuddy verification, ImageContent display checks, and
demo recording must not be represented as complete until they are actually performed.

## Public tools

- `inspect_dataset`: deterministic profile and quality assessment; no API key required.
- `analyze_dataset`: bounded multi-step analysis and grounded report; requires `HY3_API_KEY`.
- `suggest_visualization`: validated, executable chart specifications; requires `HY3_API_KEY`.
- `render_visualization`: deterministic PNG charts returned as MCP text metadata and image content;
  requires `HY3_API_KEY` and `HY3_OUTPUT_DIR`.

Existing parameters and response fields from v0.1 remain available. v0.2 adds optional workflow,
quality, reporting, and visualization fields.

## Install

From this directory:

```powershell
uv sync --all-groups
uv run hy3-data-analyst-mcp
```

Build or install the package:

```powershell
uv build
uv tool install --force .
```

The checked-in [Cursor](examples/cursor.mcp.json) and
[CodeBuddy](examples/codebuddy.mcp.json) files are placeholder-only templates. Replace their paths
and API-key placeholders locally; never commit secrets or personal absolute paths.

## Configuration

```text
HY3_API_KEY
HY3_BASE_URL=https://tokenhub.tencentmaas.com/v1
HY3_MODEL=hy3
HY3_TIMEOUT_SECONDS=60
HY3_MAX_RETRIES=2
HY3_REASONING_EFFORT=high

HY3_DATA_DIR=/absolute/path/to/data
HY3_MAX_FILE_SIZE_MB=20
HY3_MAX_ROWS=100000
HY3_MAX_COLUMNS=200
HY3_MAX_WORKFLOW_STEPS=6
HY3_MAX_EVIDENCE_RECORDS_PER_STEP=100
HY3_MAX_EVIDENCE_RECORDS_TOTAL=300

HY3_OUTPUT_DIR=/absolute/path/to/existing/chart-output
HY3_MAX_CHARTS=3
HY3_MAX_CHART_FILE_SIZE_MB=5
```

`HY3_DATA_DIR` must be an existing directory. `HY3_OUTPUT_DIR` is optional for the other three tools
and required only when rendering. The server does not automatically load `.env` files or create a
user-supplied output directory.

## Analysis semantics

The workflow operation whitelist is:

```text
describe, groupby_aggregate, multi_aggregate, top_k, value_counts,
correlation, time_trend, period_compare, missing_values, distribution,
outlier_iqr, pivot_table, filter_rows, derived_metric
```

Filters use structured literal operators. Derived metrics allow one binary add, subtract, multiply,
or divide operation over numeric columns/constants. Pivots are rejected before execution when their
predicted output exceeds 1,000 cells and are emitted in long form. Division by zero and non-finite
values become audited nulls rather than executable exceptions or JSON-invalid values.

## Rendering boundaries

`render_visualization` accepts 1–3 charts, widths from 480–1920 pixels, and heights from 320–1080
pixels. Chart points come only from locally re-executed, validated data plans and remain bound to the
returned Evidence. The renderer uses Matplotlib's non-interactive Agg backend, UUID file names,
exclusive writes, a pre-existing resolved output directory, and a 5 MB per-image hard limit.

Source files are never modified. Output-path traversal, links/reparse points, overwrite attempts,
and writes outside `HY3_OUTPUT_DIR` fail closed.

## Quality gates

```powershell
uv run python evals/run_evals.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=hy3_data_analyst_mcp --cov-fail-under=85
uv build
git diff --check
```

The offline evaluator reports exact numeric accuracy and v0.2 required-operation coverage. Planner
success and end-to-end success remain `null` offline because they require explicit live Hy3 calls.

See [architecture](docs/architecture.md), [security](docs/security.md), the
[v0.2 technical specification](docs/technical-spec-v0.2-cn.md), and the
[demo checklist](docs/demo-script.md) for the complete contract and release boundaries.
