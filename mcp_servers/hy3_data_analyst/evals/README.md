# Hy3 Data Analyst MCP 离线评测

本目录是 v0.2 技术规格“阶段 A：评测基线”的产物。它只增加评测资产和测试，不改变
`src/` 下的生产行为，也不会调用 Hy3、访问网络或修改原始数据。

## 资产

- `data/`：4 个完全合成、脱敏的数据集，分别覆盖销售、运营、匿名用户行为和数据质量；
  格式包括 CSV、JSON 数组和 JSONL。
- `cases/v0.2-phase-a.json`：36 个机器可读问题，基础统计、复合分析、趋势、异常、质量和
  可视化各 6 个。
- `baselines/v0.1.json`：当前 v0.1 单步 Schema 和确定性执行器的冻结结果。
- `run_evals.py`：固定白名单的离线 Oracle，验证案例中的 49 个精确数值断言、数据/清单
  SHA-256，以及 v0.1 兼容执行结果。

每个案例包含技术规格要求的 `case_id`、`dataset`、`question`、`required_operations`、
`required_evidence_values`、`forbidden_claims` 和 `expected_status`。额外的 `category` 用于统计
六类覆盖，`v01_plan` 仅在完整问题可由一个 v0.1 操作表示时存在。

## 运行

在 `mcp_servers/hy3_data_analyst` 下执行：

```powershell
uv run python evals/run_evals.py
uv run pytest tests/unit/test_eval_baseline.py
```

评测器不会读取案例中的代码或表达式。所有期望值使用结构化检查类型计算，例如
`group_sum`、`period_change`、`iqr_outliers` 和 `invalid_date_count`。

## v0.1 基线解释

离线基线的 36 个问题中，18 个完整问题能由一个 v0.1 `AnalysisPlan` 表示，离线能力完成率
为 50%；这 18 个计划的确定性执行成功率为 100%。v0.1 没有稳定 Evidence ID，因此稳定
Evidence ID 引用率记为 0%。

Planner 成功率和真实端到端成功率依赖 Hy3 API，当前离线阶段没有授权网络调用，因此在
快照中保持 `null`，不得把离线可表示率冒充真实模型指标。后续阶段可以在显式启用 live
评测后追加独立结果，但不得覆盖此冻结快照。

数据或案例有意变更时，SHA-256 校验会失败。应先审查期望值和范围，再通过
`--print-v01-baseline` 查看候选快照；不要在未审查时自动覆盖基线文件。
