# v0.2 阶段 B：Schema 与静态校验

本文记录技术规格第 17 节“阶段 B”的实现。阶段 B 只定义和校验结构，不连接 Hy3、不执行
Workflow，也不改变现有三个 MCP 工具的运行行为。

## 实现范围

- `analysis/workflow_models.py`
  - `AnalysisWorkflow`、14 类以 `operation` 为判别字段的 `AnalysisStep`；
  - 现有 7 类操作和新增 7 类操作的独立 Params；
  - `QualityPolicy`、Filter 条件、聚合指标、日期范围和派生指标 Operand；
  - 所有模型 `extra="forbid"`，步骤、条件、列、记录、分组、指标等集合均有硬上限。
- `analysis/workflow_validator.py`
  - 连续步骤 ID、primary step、前向引用、循环和非 View 引用在运行前拒绝；
  - 根据 `DatasetSchema` 精确校验列名、数值/日期类型和派生列血缘；
  - 校验输出别名冲突、Filter 值类型、Pivot 预测单元格和可降低的步骤预算；
  - 失败使用带可选 `step_id` 的稳定 `InvalidAnalysisWorkflowError`。
- `analysis/evidence.py`
  - `EvidenceItem`、`EvidenceLineage` 和 `EvidenceLedger`；
  - 单步 100 条、Ledger 300 条、连续 Evidence ID、JSON 有界性和安全文件名校验。
- `analysis/report_models.py`
  - `AnalysisReport`、`Finding`、`Recommendation` 和 `DataScope`；
  - fact/risk 的 Evidence 要求、ID 唯一性以及本次 Ledger 引用存在性校验。

## 静态校验顺序

1. Pydantic 解析和额外字段拒绝；
2. 1～6 步及 `S01..S06` 连续编号；
3. `primary_step_id` 必须指向 Evidence 步骤；
4. `input_ref` 只能使用 `source` 或先前的 `filter_rows`/`derived_metric` View；
5. 针对输入 View 校验真实列和派生列；
6. 按质量策略校验数值/日期类型及操作参数；
7. 在执行前拒绝超过 1000 单元格的 Pivot；
8. 校验质量策略枚举；
9. 应用最多 6 步且只能降低的资源预算。

## 阶段边界

阶段 B 没有改造 `AnalysisPlanner`、`AnalysisService` 或现有 Executor。Workflow 执行、View
物化、Evidence 生成、Planner/Repair 接入均属于阶段 C；质量策略执行、报告解释与数值
Grounding 属于阶段 D；图表仍属于阶段 F。

因此当前公开 MCP 工具继续使用 v0.1 单步路径。新增 Schema 可以独立构造和验证，但不会被
Server 自动调用。这一隔离确保阶段 B 的 Schema 设计可单独审查和回归。
