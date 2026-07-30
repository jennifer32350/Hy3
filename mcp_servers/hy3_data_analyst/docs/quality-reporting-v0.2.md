# v0.2 阶段 D：质量策略与可信报告

本文记录技术规格第 17 节“阶段 D”的实现。阶段 D 建立在阶段 C 的多步骤确定性执行器之上，
只实现显式质量处理、审计、可信报告、Grounding 和输出模式；不包含阶段 E 的
`distribution`、`pivot_table`、`derived_metric`，也不包含阶段 F 的图表渲染。

## 质量策略执行

`analysis/quality.py` 在原始 DataFrame 的深复制上按固定顺序执行：

1. 统计完整重复行，并按 `keep/drop/error` 处理；
2. 只转换 Workflow 实际需要的数值和日期列；
3. `strict` 遇到非有限值或转换失败时安全报错，`coerce` 转为 null 并计数；
4. 基于 Workflow 引用列执行 `missing=keep/drop_referenced/error`；
5. 若策略删除全部分析行则停止，不调用执行器或报告模型。

`quality_summary` 稳定返回：

- 源行数和分析基准行数；
- 发现/删除的重复行；
- 引用列存在缺失的行及因缺失删除的行；
- 转为 null 的数值和日期数量；
- 实际策略说明与 `source_modified=false`。

每条 Evidence lineage 同时携带四类质量动作。源 DataFrame 和源文件均不修改；去重、删除和
转换只存在于本次调用的内存副本。

## 可信报告

`analysis/report_service.py` 使用阶段 B 的严格 `AnalysisReport` Schema，并增加本地语义校验：

- fact/risk 和 Recommendation 只能引用本次 Ledger 中存在的 Evidence ID；
- Finding、Recommendation 和执行摘要中的数字必须能在相应 Evidence 或质量摘要中找到
  等值/格式化等值；支持千位分隔和百分比表示；
- 引用截断 Evidence、Evidence warning 或显著质量风险时，置信度不得为 high；
- 引用 correlation Evidence 时拒绝“导致、造成、驱动、cause、drive”等因果措辞；
- `data_scope` 由本地 Workflow、Ledger 和质量摘要重建，不信任模型填写的路径、行数或列；
- Evidence 和质量 warning 会确定性合并到报告 warnings。

报告首次不符合 Schema 或语义规则时只 Repair 一次。第二次仍无效时，服务返回
`status="partial"`、`report=null`、安全的 `report_error` 和完整本地 Evidence Ledger；
已成功的确定性分析不会再被包装成整次工具失败。Repair 不重新规划或执行数据计算。

## 输出与兼容

`analyze_dataset` 新增：

- `output_mode: concise | detailed = detailed`；
- `quality_policy: QualityPolicy | null`。

`detailed` 返回完整的受限 Ledger；`concise` 每条 Evidence 最多返回 5 条 records，但不删除
Evidence ID、metrics、warnings 或 report，也不改变计算结果。原有 `plan`/`evidence` 始终
镜像 `primary_step_id`，`conclusion` 等于 `report.executive_summary`。

新增返回字段包括 `report` 和 `quality_summary`；阶段 C 的 `workflow`、`evidence_ledger`、
`step_audits`、`step_timings_ms` 保持可用。只有 `status="ok"` 时 `conclusion` 才来自
`report.executive_summary`；`partial` 使用固定说明并要求以 Ledger 为准。

## 测试覆盖

- missing/duplicates 的 keep、drop、error；
- numeric/date 的 coerce、strict、无效字符串和 Infinity；
- 原始 DataFrame 不变、删除后行数、转换计数和 lineage；
- Evidence ID、未知引用、格式化数值、百分比和不受支持数值；
- correlation 非因果、高置信度限制、确定性 data scope/warnings；
- 报告 Repair 成功及两次失败后保留 Evidence；
- concise/detailed 的计算一致性和 MCP inputSchema。

## 阶段边界

阶段 D 没有新增公开工具。补充操作属于阶段 E，图表与
`render_visualization` 属于阶段 F；数据库、Web UI、多表 Join、预测模型和任意代码执行仍不在
v0.2 范围内。
