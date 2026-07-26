# Architecture

The stdio MCP boundary validates tool arguments and delegates to services. The data layer resolves every
path inside `HY3_DATA_DIR`, enforces size and shape limits, loads supported text formats, and builds bounded
profiles. Hy3 receives only constrained context and returns Pydantic-validated plans or chart specifications.
The executor maps plans to fixed Pandas functions; it never evaluates generated code. Deterministic evidence
is then passed to Hy3 for a grounded explanation.

The v0.2 Phase B schema layer defines bounded multi-step workflows, operation-specific parameter unions,
Evidence Ledgers, and structured reports. A dataset-aware static validator rejects invalid step graphs,
unknown or incompatible columns, alias conflicts, excessive pivot output, and step-budget violations
before execution.

Phase C connects the alpha workflow runtime. Hy3 plans at most six Phase C whitelist steps and gets one
repair attempt. The deterministic executor materializes filter Views as copies, executes Evidence steps
against source or an earlier View, and assigns continuous Evidence IDs under per-step and workflow-wide
serialization budgets. Only bounded Workflow and Ledger data reaches the interpreter. Compatibility
`plan` and `evidence` fields mirror the explicit primary step.

```text
MCP client -> tool boundary -> secure loader/profile -> Hy3 workflow planner -> static validation
                              -> deterministic View/Evidence executor -> bounded ledger -> Hy3 explanation
```
