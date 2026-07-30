# v0.2 Phase E deterministic operations

Phase E enables `distribution`, `pivot_table`, `derived_metric`, and `aggregate_ratio` in the workflow planner and
local executor. Dataset values remain untrusted data; none of these operations evaluates model
generated code or expression strings.

- `distribution` returns bounded per-column statistics, requested quantiles, and deterministic
  equal-width bins. Constant columns produce one bin and a warning; columns with no finite values
  produce null statistics, no bins, and a warning.
- `pivot_table` validates the aggregation whitelist through the strict workflow schema, rejects a
  predicted or actual size above 1000 cells, and emits at most 100 long-form Evidence records with
  explicit dimension, metric, aggregation, and value fields. `fill_value` is applied only to null
  aggregate results.
- `derived_metric` creates a deep-copied internal View using one structured add, subtract, multiply,
  or divide operation. It never overwrites an existing column or source file. Division-by-zero and
  non-finite results become null and are counted in the View's `StepAudit` warnings.
- `aggregate_ratio` computes two declared aggregates over the same pairwise-complete rows, then
  divides them locally. Its Evidence records contain both aggregate values and the ratio; a zero
  denominator produces null plus a warning. `scale=100` expresses a percentage.

Quality-policy discovery includes all source columns referenced by these operations. Derived output
columns are intentionally excluded from pre-workflow source conversion and missing-row handling;
they are created only when their View step executes.
