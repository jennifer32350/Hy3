# v0.2 阶段 C：多步骤执行器与运行时接入

本文记录技术规格第 17 节“阶段 C”的实现。阶段 C 在阶段 B 的严格 Schema 和静态校验之上，
接入 v0.2-alpha 多步骤运行时；不实现阶段 D 的质量策略执行、可信报告和 Grounding，也不提前
实现阶段 E/F 的补充操作或图表渲染。

## 实现范围

- `analysis/workflow_executor.py`
  - 从源 DataFrame 深复制初始逻辑 View，任何步骤都不原地修改调用者数据；
  - `filter_rows` 生成新的内部 DataFrame View 和有界 `StepAudit`；
  - Evidence 步骤生成连续 `E01..E06`，每步和整个 Ledger 分别执行记录上限；
  - 实现 `filter_rows`、`multi_aggregate`、`value_counts` 和 `period_compare`；
  - 将原有 `describe`、`groupby_aggregate`、`top_k`、`correlation`、`time_trend`、
    `missing_values` 和 `outlier_iqr` 接入 Workflow；
  - 任一步失败后停止，并返回失败 `step_id`、已完成 Evidence 和 View 审计；
  - `distribution`、`pivot_table`、`derived_metric` 在阶段 C 明确拒绝，不做隐式降级。
- `analysis/workflow_planner.py`
  - Planner 只接收问题、行列数、重复行数、字段类型、缺失率、唯一值数和有界统计；
  - 只允许阶段 C 的 11 类操作和 1～6 个连续步骤；
  - 首次模型输出或数据集感知校验失败时只修复一次，第二次失败安全返回；
  - 阶段 C 只允许默认非破坏性质量策略，其他策略留到阶段 D。
- `analysis/service.py` 与 `tools/analyze_dataset.py`
  - `analyze_dataset` 增加向后兼容的可选 `max_steps=6`；
  - 返回 `workflow`、`evidence_ledger`、`step_audits` 和 `step_timings_ms`；
  - 原有 `plan` 和 `evidence` 始终镜像 `primary_step_id` 指定的主步骤；
  - Interpreter 只接收已验证 Workflow 和有界 Ledger，兼容解释必须引用本次 Evidence ID。
- 配置
  - 新增 `HY3_MAX_WORKFLOW_STEPS`、`HY3_MAX_EVIDENCE_RECORDS_PER_STEP` 和
    `HY3_MAX_EVIDENCE_RECORDS_TOTAL`；
  - 配置只能降低 6/100/300 的硬上限，不能放大资源边界。

## 关键执行语义

1. 运行前由 `validate_workflow` 完成步骤依赖、列、类型、别名和资源静态校验。
2. `source` 和每个 Filter View 都保留完整的受限内部行；Evidence 截断不影响后续计算。
3. `contains` 使用 `regex=False` 的字面子串；日期过滤和期间比较的转换失败值不匹配。
4. `value_counts(normalize=true)` 在存在 `group_by` 时使用组内分母。
5. `period_compare` 支持环比、同比和显式闭区间，基期为零时变化率为 `null` 并警告。
6. 筛选得到零行时保留该步审计；首个依赖空 View 的步骤稳定失败，后续步骤不执行。
7. 原始 DataFrame 和源文件均不修改；执行器不调用 `eval`、`exec`、`DataFrame.query`、
   `pandas.eval`、动态导入或模型生成表达式。

## 测试覆盖

- 三步 `filter_rows -> multi_aggregate/value_counts` 工作流及精确数值；
- 综合经营分析一次调用完成区域多指标聚合、IQR 异常和期间对比三个步骤；
- Filter 的 all/any、空值、大小写、日期和非正则字面 contains；
- 多指标聚合、组内频数占比、显式/最近期间比较、零基期和无数据失败；
- 空 View 依赖失败、已完成 Evidence/Audit 保留、单步/全局 Ledger 截断；
- Planner 修复成功、两次无效后失败、Interpreter 非法 Evidence ID；
- `max_steps` 工具 Schema、配置硬上限和原始 DataFrame 不变。

## 阶段边界

- `QualityPolicy` 的 drop/error/coerce 审计、统一 `quality_summary` 属于阶段 D；阶段 C Planner
  只接受默认 `keep/keep/strict/coerce`。
- 结构化 `AnalysisReport`、Interpreter Repair 和数值 Grounding 属于阶段 D。
- `distribution`、`pivot_table`、`derived_metric` 属于阶段 E。
- Chart Spec、PNG Renderer 和 `render_visualization` 属于阶段 F。

阶段 C 完成后，公开 MCP 工具仍恰好为三个；没有数据库、Web UI、多表 Join、预测模型或任意
代码执行路径。
