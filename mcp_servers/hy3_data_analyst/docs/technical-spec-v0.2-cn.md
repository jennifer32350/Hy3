# Hy3 Data Analyst MCP v0.2 技术规格与 AI 开发约束

> 文档状态：开发输入稿
> 目标版本：v0.2
> 前置阅读：[v0.2 PRD](product-requirements-v0.2-cn.md)、[当前子项目 README](../README.md)
> 若开发计划与本文的技术边界冲突，以本文为准。

## 1. 给执行开发的 AI Agent 的强制指令

1. 编码前完整阅读 PRD、本文、当前 README、架构说明、安全说明和相关源代码。
2. 先执行 `git status --short --branch`，保留用户已有修改，不使用破坏性 Git 命令。
3. 只修改 `mcp_servers/hy3_data_analyst` 及确有必要的 CI/根 README，不改 `finetune`。
4. 按第 17 节顺序实施；每阶段测试通过后再进入下一阶段。
5. 不硬编码 API Key、用户绝对路径、测试 Token 或个人信息。
6. 不执行 Hy3 生成的代码、SQL、Shell、正则或字符串 Pandas 表达式。
7. 禁止使用 `eval`、`exec`、`DataFrame.query`、`pandas.eval` 或动态导入完成分析。
8. 计划、参数、报告和图表规格均使用 `extra="forbid"` 的 Pydantic Schema。
9. 数据计算只在本地确定性执行器完成；Hy3 只规划、修复、解释和选择图表。
10. 新功能必须有正常、边界、错误和安全测试，不得只依赖 live test。
11. 未经用户明确要求，不提交、不推送、不创建 PR。
12. 未定义的决策采用最小安全实现；涉及公开接口或安全边界时先询问用户。

## 2. 当前技术基线

- Python 3.10～3.13，FastMCP stdio；
- OpenAI 兼容接口调用 Hy3；
- Pandas/NumPy 确定性计算，Pydantic 严格 Schema；
- CSV、JSON 数组和 JSONL；
- 默认最大 20 MB、100,000 行、200 列；
- 7 类单步操作；Planner 最多修复一次；
- Interpreter 只接收有界 Evidence，不接收完整 DataFrame。

v0.2 必须保留这些安全设计，不得重写为模型生成代码后执行的方案。

## 3. 目标架构与数据流

```text
MCP Client
  -> Tool Boundary
  -> Secure Loader / Dataset Profile / Quality Assessment
  -> Hy3 Workflow Planner
  -> Workflow Validator
  -> Deterministic Workflow Executor
       -> Internal DataFrame Views
       -> Evidence Ledger
  -> Hy3 Report Interpreter
  -> Structured Report / Validated Chart Spec
  -> Deterministic PNG Renderer
```

强制约束：

- 完整 DataFrame 只存在本地，不发送给 Hy3。
- Planner 只接收问题、字段元数据、有限统计和质量摘要。
- Interpreter 只接收问题、已验证 Workflow 和有界 Evidence Ledger。
- 中间 DataFrame 可保留全部受限行；对外和发给模型的记录必须截断。
- 每个 View 步骤产生新 DataFrame，不原地修改输入 View。
- 图表只使用本地确定性数据，禁止使用 Hy3 生成的数据点。

## 4. 公开 MCP 工具契约

### 4.1 `inspect_dataset`

保留现有签名和返回字段。新增 `quality`：

```text
score: 0..100
severity: info | warning | error
issues: QualityIssue[]
analyzed_rows: int
source_modified: false
```

质量分数由本地固定规则计算并测试，不能由 Hy3 生成，也不能作为数据可用性的唯一判断。

### 4.2 `analyze_dataset`

扩展签名：

```python
analyze_dataset(
    file_path: str,
    question: str,
    reasoning_effort: Literal["low", "high"] = "high",
    output_mode: Literal["concise", "detailed"] = "detailed",
    max_steps: int = 6,
    quality_policy: QualityPolicy | None = None,
) -> dict[str, Any]
```

边界：问题长度 1～4000；`max_steps` 为 1～6；配置只能降低、不能突破硬上限 6。

保留 v0.1 字段并增加 v0.2 字段：

```text
status
plan                 # primary_step 的旧式兼容摘要
evidence             # primary_step 的兼容 Evidence
conclusion           # 等于 executive_summary
evidence_references
limitations
warnings
elapsed_ms
workflow
evidence_ledger
report
quality_summary
step_timings_ms
```

Workflow 必须明确 `primary_step_id`；兼容字段只能镜像该步骤，不能临时选择首尾步骤。

### 4.3 `suggest_visualization`

保留现有参数，可增加 `quality_policy`。每项建议新增 `data_plan`、`evidence_id`、`sort`、
`limit` 和 `notes`。规格只能描述确定性数据准备步骤，不允许携带模型生成的数据点。

### 4.4 `render_visualization`

新增工具：

```python
render_visualization(
    file_path: str,
    goal: str,
    max_charts: int = 2,
    width: int = 1200,
    height: int = 720,
    quality_policy: QualityPolicy | None = None,
) -> MCP content blocks
```

边界：图数 1～3；宽 480～1920；高 320～1080；只输出 PNG；单图最大 5 MB。
返回 TextContent 元数据和 ImageContent。只有本工具要求 `HY3_OUTPUT_DIR`。

## 5. Workflow Schema

所有模型必须 `extra="forbid"`，所有集合必须有长度限制。

### 5.1 `AnalysisWorkflow`

```text
version: Literal["2.0"]
goal: str                         # 1..1000
primary_step_id: str
quality_policy: QualityPolicy
steps: list[AnalysisStep]         # 1..6
rationale: str                    # 1..2000
```

### 5.2 `AnalysisStep`

```text
step_id: str                      # ^S0[1-6]$
operation: Operation
input_ref: str                    # source 或此前 View 步骤 ID
params: discriminated union
purpose: str                      # 1..1000
```

规则：

- `S01` 只能引用 `source`；步骤按列表连续编号；
- 只能引用此前产生 DataFrame View 的步骤；
- 不允许重复 ID、跳号、前向引用或循环依赖；
- 至少一个步骤产生分析 Evidence；
- `primary_step_id` 必须指向分析 Evidence 步骤。

产生 View、可被后续引用的操作只有：`filter_rows`、`derived_metric`。

产生 Evidence、不可作为 DataFrame 输入的操作：`describe`、`groupby_aggregate`、
`multi_aggregate`、`top_k`、`value_counts`、`correlation`、`time_trend`、`period_compare`、
`missing_values`、`distribution`、`outlier_iqr`、`pivot_table`。

禁止用已经截断的 Evidence 继续计算。未来若需要通用表格链，必须另行设计内部 Table Artifact。

## 6. Evidence Schema

```text
evidence_id: str                  # ^E0[1-9]$
step_id: str
operation: Operation
summary: str                      # 1..1000
metrics: dict[str, JsonValue]
records: list[dict[str, JsonValue]]
source_rows: int
used_rows: int
excluded_rows: int
truncated: bool
warnings: list[str]               # 最多 20
lineage:
  source_file_name: str           # 仅文件名
  input_ref: str
  referenced_columns: list[str]
  quality_actions: list[str]
```

规则：

- View 步骤生成 StepAudit，但不占 Evidence ID；
- 每步最多序列化 100 条记录，整个 ledger 最多 300 条；
- 内部计算不得因序列化截断而改变；
- 非有限浮点转为 null 并警告；
- 禁止返回绝对路径、API Key 或完整原始数据集。

## 7. 操作白名单及确定性语义

### 7.1 通用边界

- 列名精确匹配，不做模糊替换；目标列最多 20，分组列最多 5；
- 返回记录限制为 1～100；
- 聚合只允许 sum/mean/count/min/max/median；排序只允许 asc/desc；
- 输出别名匹配 `^[A-Za-z_][A-Za-z0-9_]{0,63}$`，且不得冲突；
- 需要数值列的操作必须验证类型或遵循显式转换策略。

### 7.2 现有操作增强

- `describe`：数值列增加 q1/q3；类别统计保持有界；
- `groupby_aggregate`：记录实际参与聚合的行数；
- `top_k`：相同值采用原始行序作为稳定第二排序键；
- `correlation`：仅 Pearson；样本少于 3 或零方差返回 null 和 warning；
- `time_trend`：支持 day/week/month/quarter/year，默认 month；
- `missing_values`：返回 count、rate、severity；
- `outlier_iqr`：返回受限原始行号；IQR=0 时明确警告。

### 7.3 `filter_rows`

```text
combine: all | any
conditions: FilterCondition[]     # 1..10

FilterCondition:
  column
  operator: eq | ne | gt | gte | lt | lte | in | not_in |
            contains | between | is_null | not_null
  value: JsonScalar | null
  values: JsonScalar[]            # 最多 100
  case_sensitive: bool
```

- `contains` 是字面子串，必须 `regex=False`；
- `between` 恰好两个同类型闭区间边界；
- `in/not_in` 需要 1～100 个标量；
- `is_null/not_null` 禁止 value/values；
- 转换失败值不得被当成匹配；
- 过滤为 0 行时停止依赖该 View 的后续步骤并返回稳定错误；
- Audit 记录过滤前后行数，不返回全部排除行。

### 7.4 `multi_aggregate`

```text
group_by: str[]                    # 1..5
metrics: AggregateMetric[]         # 1..20
sort_by: str | null
sort_order: asc | desc
limit: int                         # 1..100

AggregateMetric:
  column
  aggregation
  alias
```

不同指标可采用不同聚合。`count` 可用于非数值列，其余聚合要求数值。别名必须唯一，
`sort_by` 必须是输出列。

### 7.5 `value_counts`

```text
column: str
group_by: str[]                    # 0..3
normalize: bool
include_null: bool
sort_order: asc | desc
limit: int                         # 1..100
```

始终返回整数 count。`normalize=true` 时增加 0～1 的 share；有 group_by 时分母为各组内部总数，
并在 summary 中明确说明。

### 7.6 `period_compare`

```text
time_column: str
target_columns: str[]              # 1..10
aggregation
grain: month | quarter | year
comparison: previous_period | year_over_year | explicit
group_by: str[]                    # 0..3
period_a: DateRange | null
period_b: DateRange | null
```

- previous_period 使用最大有效日期所属的最近两个完整粒度期间；
- year_over_year 比较最大有效日期所属期间与上一年同期间；
- explicit 要求两个合法闭区间；
- 当前期间不完整必须警告；
- 输出两期值、绝对变化和变化率；
- 基期为 0 时变化率为 null 并警告；
- 无有效日期或任一期间无数据时安全失败。

### 7.7 `distribution`

```text
target_columns: str[]              # 1..10
quantiles: float[]                 # 1..9，严格递增，0..1
bins: int                          # 5..50
```

默认分位数为 0.25/0.5/0.75。输出 count、missing、mean、std、min、max、quantiles 和确定性等宽
分箱。常量列返回单一有效分箱和 warning，不得崩溃。

### 7.8 `pivot_table`

```text
rows: str[]                        # 1..3
columns: str[]                     # 1..2
metrics: AggregateMetric[]         # 1..10
fill_value: float | null
```

预测单元格超过 1000 时执行前拒绝。只允许白名单聚合。输出使用长表记录，避免动态列爆炸。

### 7.9 `derived_metric`

```text
output_column: str
operator: add | subtract | multiply | divide
left: Operand
right: Operand

Operand:
  {kind: column, column: profit}
  或 {kind: constant, value: 100}
```

- 一步只允许一个二元运算；复杂指标通过数个显式步骤构造；
- 两个 Operand 不得同时为常量；列 Operand 必须为数值列；
- 除零结果为 null 并记录数量；
- 禁止幂、函数调用、括号、字符串公式和自定义运算符；
- 新列只存在于新 View，不覆盖现有列、不写原文件。

## 8. 规划、校验和执行

### 8.1 Planner 输入

仅包含：问题、max_steps、列名/dtype/语义类型、行列数、缺失率、唯一值数量、有界统计、
重复行数、质量摘要和允许的操作。禁止完整 DataFrame、绝对路径和密钥。

### 8.2 模型调用上限

- Workflow 初次生成一次，失败最多修复一次；再次失败立即报错；
- 本地执行成功后 Interpreter 调用一次，报告无效最多修复一次；
- 不允许无限循环；Repair Prompt 不含异常堆栈、敏感路径或多余原始数据。

### 8.3 静态校验顺序

1. Pydantic Schema；
2. 步骤数量和连续 ID；
3. primary_step；
4. input_ref 顺序与 View 类型；
5. 列名和派生列名；
6. 参数和字段类型；
7. 预测输出规模；
8. 质量策略；
9. 资源预算。

### 8.4 执行语义

- 从 source 创建初始逻辑 View，步骤按序执行；
- View 步骤产生新 DataFrame，Evidence 步骤产生 EvidenceItem；
- 记录每步耗时；
- 任一步骤失败后停止，返回失败 step_id、已完成审计/Evidence 和可操作 hint；
- 不对未完成 Workflow 调用 Interpreter；
- 报告修复不得重新执行数据计算。

## 9. 数据质量策略

```text
QualityPolicy:
  missing: keep | drop_referenced | error        # 默认 keep
  duplicates: keep | drop | error                # 默认 keep
  numeric_conversion: strict | coerce            # 默认 strict
  date_conversion: strict | coerce               # 默认 coerce
```

- keep 保留数据，操作必须记录实际 used_rows；
- drop_referenced 只删除 Workflow 引用列中有缺失的行并记录数量；
- duplicates=drop 只在内存副本删除完整重复行；不允许任意子集去重；
- coerce 只转换相关步骤引用的列，失败值设 null 并记录数量；
- strict 遇到相关转换失败时必须报错，不得部分计算；
- 原始 DataFrame 和文件永不修改。

`quality_summary` 至少返回：source_rows、analysis_base_rows、duplicate_rows_found、
duplicate_rows_removed、rows_removed_for_missing、numeric_values_coerced_to_null、
date_values_coerced_to_null、policies_applied、`source_modified=false`。

## 10. 报告 Schema 与 Grounding

```text
AnalysisReport:
  executive_summary: str                 # 1..4000
  findings: Finding[]                    # 1..8
  anomalies: Finding[]                   # 0..8
  recommendations: Recommendation[]      # 0..8
  data_scope: DataScope
  limitations: str[]                     # 0..20
  warnings: str[]                        # 0..20
  suggested_follow_ups: str[]            # 0..5

Finding:
  finding_id: str                        # ^F\d{2}$
  kind: fact | interpretation | risk
  title: str
  statement: str
  evidence_ids: str[]
  confidence: high | medium | low

Recommendation:
  recommendation_id: str                 # ^R\d{2}$
  statement: str
  basis_evidence_ids: str[]              # 1..5
  priority: high | medium | low
```

校验规则：

- 所有引用 ID 必须存在于本次 ledger；fact/risk 至少引用一条 Evidence；
- Recommendation 必须有 Evidence 依据；
- Evidence 截断或含严重质量警告时 confidence 最高为 medium；
- correlation 解释禁止使用“导致、造成、驱动”等因果措辞；
- 报告数值必须能在所引 Evidence 的 metrics/records 找到等值或格式化等值；
- 实现保守的数值 grounding validator；不能可靠匹配时修复/删除数值表达，不能放宽校验；
- 报告首次失败允许修复一次；再次失败返回 `InvalidAnalysisReportError`，并保留本地 Evidence
  供用户核验。

输出模式：detailed 返回完整受限 ledger；concise 每步最多 5 条 records，但不省略 metrics、
Evidence ID、warnings 和 report。两种模式的计算必须一致。

## 11. 可视化

### 11.1 Chart Spec

只允许 bar、line、scatter、histogram、box。规格包含 chart_type、title、x、y、color、
aggregation、sort、limit、data_plan、evidence_id、rationale、notes。

字段必须来自源数据或 data_plan 的安全输出列。Hy3 只选择规格；本地 Visualization Executor
重新执行 data_plan；Renderer 只读取确定性结果。

### 11.2 数据与渲染边界

- 最大绘图点 5,000；超出后确定性聚合或等距采样并标记；
- 类别图最多 30 类，超出使用 Top-N 并将其余合并为 Other；
- 缺失、截断、采样和异常规则写入元数据；
- 使用 Matplotlib Agg，不引入浏览器或 GUI；
- 文件名使用 UUID，不使用用户 title/goal；
- 仅写入解析后的输出目录，排他创建，禁止覆盖；
- 创建后复核路径仍在输出目录内；
- 测试只写临时目录，stdout 不输出 Matplotlib 日志。

## 12. 配置

新增：

```text
HY3_MAX_WORKFLOW_STEPS=6
HY3_MAX_EVIDENCE_RECORDS_PER_STEP=100
HY3_MAX_EVIDENCE_RECORDS_TOTAL=300
HY3_OUTPUT_DIR=
HY3_MAX_CHARTS=3
HY3_MAX_CHART_FILE_SIZE_MB=5
```

- 步骤硬上限 6；每步记录硬上限 100；总记录硬上限 300；图数硬上限 3；
- `HY3_OUTPUT_DIR` 仅渲染时必需，必须预先存在、可解析且为目录；
- Server 不自动创建用户指定目录；
- 配置继续为不可变 Settings；`.env.example` 只放占位符，不自动加载。

## 13. 错误模型

新增异常：`InvalidAnalysisWorkflowError`、`WorkflowExecutionError`、
`DataQualityPolicyError`、`InvalidAnalysisReportError`、`VisualizationRenderError`、
`OutputAccessDeniedError`。

错误保持稳定结构：

```json
{
  "error": "StableErrorClass",
  "message": "不含密钥、堆栈和绝对路径的说明",
  "hint": "用户下一步可以采取的动作",
  "step_id": "S03"
}
```

step_id 只在工作流错误中出现。堆栈只能进入受控 stderr 调试日志，默认不输出。

## 14. 安全与资源边界

### 14.1 文件和路径

- 所有读取路径复用现有安全 resolver；
- 输出使用独立 resolver，防止 `..`、绝对文件名、符号链接和重解析点逃逸；
- 不接受 URL、UNC 远程位置或命名管道；
- 不修改、移动或删除源文件。

### 14.2 提示词注入

- 文件名、列名、类别值和样例行都视为不可信数据；
- System Prompt 明确禁止遵循数据中的指令；
- 不发送完整高基数文本样例；
- 模型输出必须经过 Schema 和语义校验，不能只依赖提示词。

### 14.3 硬限制

- 默认 20 MB、100,000 行、200 列；
- 最大 6 步；Filter 最大 10 条条件；Pivot 最大 1,000 单元格；
- 每步 100 条、总计 300 条 Evidence records；
- 单次最多 3 张图、每张 5 MB；
- Planner 与 Interpreter 各最多 2 次调用（含一次修复）；
- 不实现无限重试，API 暂时错误沿用当前有限重试。

## 15. 建议代码结构

```text
src/hy3_data_analyst_mcp/
├─ analysis/
│  ├─ workflow_models.py
│  ├─ workflow_planner.py
│  ├─ workflow_validator.py
│  ├─ workflow_executor.py
│  ├─ operations/
│  │  ├─ filters.py
│  │  ├─ aggregates.py
│  │  ├─ periods.py
│  │  ├─ distributions.py
│  │  └─ derived.py
│  ├─ evidence.py
│  ├─ report_models.py
│  ├─ report_service.py
│  └─ quality.py
├─ visualization/
│  ├─ models.py
│  ├─ planner.py
│  ├─ executor.py
│  ├─ renderer.py
│  └─ security.py
└─ tools/
   └─ render_visualization.py
```

不要为匹配目录一次性移动所有文件。采用可审查的小步修改，只在减少循环依赖或提升测试性时
移动现有实现。

## 16. 测试规格

### 16.1 单元测试

- 新 Schema 的有效、缺字段、额外字段和边界值；
- 步骤 ID、前向引用、非 View 引用、primary step、最大步骤数；
- 每个新操作的正常、空结果和类型错误；
- filter 的 null、日期、数值、非正则 contains、all/any；
- period compare 的零基期、无数据、不完整期间、无效日期；
- derived metric 的冲突、常量常量、非数值、除零、非法操作；
- 质量策略 keep/drop/error/coerce/strict；
- Evidence ID、总量截断和 lineage；
- 报告 ID 引用、数值 grounding、相关非因果；
- 输出目录穿越、覆盖、符号链接和大小限制；
- NaN、Infinity、Timestamp 和 NumPy 标量的 JSON 安全转换。

### 16.2 集成测试

- Mock Hy3 生成有效多步骤 Workflow；
- Workflow 首次无效后修复成功，以及两次无效后安全失败；
- 中间 View 被正确使用；某步失败后后续不执行；
- Evidence 成功后报告修复成功/最终失败；
- Chart Spec 字段和派生别名验证；
- PNG 实际生成、尺寸检查和基本非空验证。

### 16.3 MCP 协议测试

- `tools/list` 在新增渲染工具后恰好返回 4 个工具；
- 每个工具 description 和 inputSchema 完整；
- 已安装环境的 initialize/list/call 通过；
- 渲染返回正确 MIME 的 ImageContent；
- stdout 不受日志污染。

### 16.4 评测集

建议结构：

```text
evals/cases/*.json
evals/data/*
evals/run_evals.py
```

每个 case 包含 case_id、dataset、question、required_operations、required_evidence_values、
forbidden_claims、expected_status。真实 Hy3 评测默认跳过并由环境变量显式开启；确定性执行器
评测必须完全离线。

### 16.5 质量命令

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=hy3_data_analyst_mcp --cov-report=term-missing
git diff --check
```

## 17. 强制实施顺序

### 阶段 A：评测基线

创建 3～5 个脱敏数据集和至少 30 个问题，保存 v0.1 基线，不修改生产行为。

完成条件：离线数值期望可重复运行。

### 阶段 B：Schema 与校验器

实现 Workflow、Step、Params、Evidence、Report Schema 和全部静态校验，暂不接 Hy3。

完成条件：非法 Workflow 全部在执行前被拒绝。

### 阶段 C：v0.2-alpha 执行器

实现 View、Ledger、filter、multi_aggregate、value_counts、period_compare；接入 Planner、Repair
和 analyze service，保留兼容字段。

完成条件：综合经营分析一次调用完成至少 3 步且数值全对。

### 阶段 D：质量策略和可信报告

实现 QualityPolicy、审计、Report、Interpreter、Grounding Validator 和输出模式。

完成条件：事实性 Finding 均有有效 Evidence，所有数据排除可见。

### 阶段 E：补齐操作

实现 distribution、pivot_table、derived_metric 和对应测试。

完成条件：PRD 核心复合场景进入评测并通过。

### 阶段 F：图表

实现 Chart Spec、Visualization Executor、安全 PNG Renderer 和 `render_visualization`。

完成条件：客户端能查看真实图表，图中数据与 Evidence 一致。

### 阶段 G：发布验收

运行质量门禁和 CI，在 Cursor/CodeBuddy 实测，更新中英文文档与录屏，扫描密钥和路径。

## 18. Definition of Done

- PRD 的 FR-001～FR-310 已实现，或存在用户批准的书面降级说明；
- 至少 30 个评测问题，核心成功率不低于 85%；
- 离线期望数值 100% 正确；事实性数值结论均有 Evidence；
- 原始文件从未修改；不存在动态代码/表达式执行路径；
- 三个旧工具兼容，新渲染工具协议通过；
- Ruff、Mypy、Pytest、覆盖率和 CI 全通过；
- Cursor、CodeBuddy 完成真实验证和录屏；
- 文档完整，Git diff 无密钥、个人路径、缓存和无关文件。

## 19. 禁止的实现捷径

- 让 Hy3 输出并执行 Python/Pandas 代码；
- 将问题拼接进 `DataFrame.query()` 或自由格式公式；
- 把完整数据发送给 Hy3 计算；
- 用截断 Evidence 继续计算；
- 无限重试或静默替换无效计划；
- 静默删除缺失/重复数据；
- 接受模型虚构列名、别名或图表数据；
- 使用用户 goal/title 作为输出文件名；
- 在 stdio stdout 打印日志；
- 跳过 Windows 路径安全和错误测试；
- 在 v0.2 顺手加入数据库、Web UI、多表 Join 或预测模型。
