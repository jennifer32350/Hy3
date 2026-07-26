# Architecture

The stdio MCP boundary validates tool arguments and delegates to services. The data layer resolves every
path inside `HY3_DATA_DIR`, enforces size and shape limits, loads supported text formats, and builds bounded
profiles. Hy3 receives only constrained context and returns Pydantic-validated plans or chart specifications.
The executor maps plans to fixed Pandas functions; it never evaluates generated code. Deterministic evidence
is then passed to Hy3 for a grounded explanation.

The v0.2 Phase B schema layer now defines bounded multi-step workflows, operation-specific parameter
unions, Evidence Ledgers, and structured reports. A dataset-aware static validator rejects invalid step
graphs, unknown or incompatible columns, alias conflicts, excessive pivot output, and step-budget
violations before execution. These schemas are intentionally not connected to the v0.1 runtime yet;
workflow execution and planner integration belong to Phase C.

```text
MCP client -> tool boundary -> secure loader/profile -> Hy3 planner -> plan validation
                                                     -> Pandas executor -> evidence -> Hy3 explanation
```
