# Architecture

The stdio MCP boundary validates tool arguments and delegates to services. The data layer resolves every
path inside `HY3_DATA_DIR`, enforces size and shape limits, loads supported text formats, and builds bounded
profiles. Hy3 receives only constrained context and returns Pydantic-validated plans or chart specifications.
The executor maps plans to fixed Pandas functions; it never evaluates generated code. Deterministic evidence
is then passed to Hy3 for a grounded explanation.

```text
MCP client -> tool boundary -> secure loader/profile -> Hy3 planner -> plan validation
                                                     -> Pandas executor -> evidence -> Hy3 explanation
```
