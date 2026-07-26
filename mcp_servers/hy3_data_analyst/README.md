# Hy3 数据分析 MCP

Hy3 数据分析 MCP 是一个可安装的本地 stdio MCP Server。当前版本可以安全检查 CSV、
JSON 和 JSONL 数据集，并通过 OpenAI 兼容接口调用 Hy3，让 Hy3 负责规划分析和解释证据，
由 Pandas 完成确定性的数值计算。

> 当前进度：阶段 A～K 的可自动化工作已完成；真实客户端验证、录屏和 PR 尚未完成。
> 当前开发分支：`hy3-data-analyst-mcp`。
> 最后更新日期：2026-07-25。

## v0.2 开发状态

v0.2 严格按技术规格分阶段实施。阶段 A（评测基线）已完成：新增 4 个合成脱敏数据集和
36 个机器可读案例，覆盖基础统计、复合分析、趋势、异常、质量和可视化六类，并冻结当前
v0.1 的离线确定性结果。评测包含 49 个精确数值断言，不调用 Hy3 或修改生产行为。

运行方式和基线口径见 [离线评测说明](evals/README.md)。阶段 B（Schema 与静态校验）也已
完成：新增严格 Workflow/Step/Params、Evidence Ledger、Report Schema 和数据集感知校验器，
非法步骤依赖、列名、类型、别名、Pivot 规模和资源预算均在执行前拒绝。实现说明见
[v0.2 Schema 与静态校验](docs/schema-validation-v0.2.md)。

阶段 B 尚未接入 Hy3 或公开 MCP 工具，现有 v0.1 运行行为保持不变。阶段 C 及后续执行器、
质量策略、可信报告服务和图表功能尚未开始。

## 当前已经具备的能力

- 使用 `src` 目录结构组织代码，并提供可安装的 Python 软件包。
- 安装后提供 `hy3-data-analyst-mcp` 控制台命令。
- 提供基于 FastMCP 的 stdio MCP Server，并声明三个 MCP 工具。
- 仅通过环境变量读取经过校验的不可变配置。
- 限制数据文件访问目录，防止路径穿越，并检查扩展名和文件大小。
- 安全读取 UTF-8、UTF-8-SIG 编码的 CSV、JSON 数组和 JSONL 文件。
- 用户明确指定时支持 GB18030 编码。
- 生成数据集概览，包括字段结构、语义类型、缺失值、重复行、数值统计、类别高频值、
  日期范围和可安全序列化为 JSON 的样例行。
- `inspect_dataset` 工具已经可用，并且不需要 Hy3 API Key。
- 提供延迟创建、可注入测试依赖的 `AsyncOpenAI` Hy3 客户端。
- 支持普通文本响应和基于 JSON Schema 的结构化响应。
- 将认证、权限、限流、超时、网络连接、服务器、无效响应和其他 SDK 错误转换为安全的
  项目异常。
- 对暂时性错误执行有限次数重试；认证和权限错误不会重试。
- 提供受 Pydantic Schema 约束的分析计划，只允许 7 类固定操作。
- 在执行前验证计划中的所有列名；无效计划只允许 Hy3 修复一次。
- 通过本地 Pandas 执行描述统计、分组聚合、Top-K、相关性、月度趋势、缺失值和 IQR
  异常值分析，不执行模型生成的代码或表达式。
- 将有界的确定性 Evidence 发送给 Hy3 解释，并返回计划、证据、结论、引用、限制和警告。

Server 当前会公开以下三个工具：

- `inspect_dataset`：已经实现并可用。
- `analyze_dataset`：已经实现并可用；需要配置 `HY3_API_KEY`。
- `suggest_visualization`：已经实现并可用；需要配置 `HY3_API_KEY`。

## 完整开发进度

| 阶段 | 工作范围 | 当前状态 | 已完成结果或待办事项 |
| --- | --- | --- | --- |
| A | 软件包骨架和 FastMCP stdio Server | 已完成 | 已创建项目元数据、控制台入口、Server 和三个工具接口。 |
| B | 配置、文件路径安全和数据加载 | 已完成 | 可在允许目录内读取 CSV、JSON 数组和 JSONL，并执行文件、行数和列数限制。 |
| C | 数据集概览和 `inspect_dataset` | 已完成 | 可在没有 `HY3_API_KEY` 时执行确定性的、可序列化为 JSON 的数据检查。 |
| D | OpenAI 兼容的 Hy3 API 客户端 | 已完成 | mock 测试及真实 TokenHub 普通响应均已通过，并已修正官方 chat-template reasoning 参数兼容性。 |
| E | 分析计划、执行器、Planner、证据、分析服务和 `analyze_dataset` | 已完成 | 7 类白名单操作、列名校验、一次修复、Evidence、解释和真实 TokenHub 端到端分析均已通过。 |
| F | 图表模型、字段验证、提示词和 `suggest_visualization` | 已完成 | 结构化建议、字段校验、一次修复及真实 TokenHub 图表建议均已通过。 |
| G | MCP 协议和最终质量门禁 | 已完成 | Ruff、Mypy、Pytest、覆盖率和已安装 stdio `tools/list` 均已验证。 |
| H | Wheel 构建和全新环境一键安装验证 | 已完成 | sdist/wheel 构建、用户级 `uv tool install` 和独立目录 stdio 握手成功。 |
| I | CodeBuddy 和 Cursor 配置 | 模板已完成 | 两个无密钥、无个人路径模板已创建；真实客户端验证待用户环境。 |
| J | 完整中英文说明、架构和安全文档 | 进行中 | README 已记录逐功能进度，架构、安全和演示脚本已创建；英文 README 仍待补充。 |
| K | Windows 和 Ubuntu CI | 已完成（待远端运行） | 已创建 Windows/Ubuntu、Python 3.10/3.12 矩阵工作流；需推送后获得真实 CI 结果。 |
| L | 真实客户端验证和演示录制 | 待开发 | 需要 TokenHub 权限以及用户参与客户端操作和录屏。 |
| M | 根 README 入口和 Pull Request 准备 | 待开发 | 必须等前面的阶段全部通过后再执行。 |

## 阶段 D 的实现详情

`src/hy3_data_analyst_mcp/hy3_client.py` 中的客户端已经实现：

- 延迟创建 `AsyncOpenAI`，因此导入 MCP Server 时不会建立网络连接。
- 支持配置 `base_url`、API Key、模型、超时时间、重试次数和 reasoning effort。
- 使用非流式 Chat Completion 请求。
- 普通响应和结构化响应均显式设置 `max_tokens=16384`，避免 Hy3 的推理过程耗尽默认输出
  额度后只返回空的最终答案。
- 按 Hy3 官方接口通过 `chat_template_kwargs.reasoning_effort` 传递推理模式，将工具的
  `low` 映射为 `no_think`，将 `high` 保持为 `high`，并使用推荐的 temperature/top_p。
- 使用 JSON Schema 请求结构化输出，并通过 Pydantic 再次校验结果。
- 拒绝空文本响应以及不符合 Schema 的结构化响应。
- HTTP 401 和 403 会立即转换为 `Hy3AuthenticationError`，不会重试。
- HTTP 429、超时、连接失败和 HTTP 5xx 会执行有限重试，重试耗尽后返回安全错误。
- 其他 OpenAI SDK API 异常会转换为通用且安全的项目异常。
- 不记录 API Key、Authorization Header、完整请求体或完整原始数据。

阶段 D 的集成测试已经覆盖：

- 正常的普通文本响应。
- 正常的结构化响应及 Pydantic 校验。
- 空响应和无效结构化响应。
- HTTP 401、403、429 和 500。
- 请求超时和网络连接失败。
- 暂时性故障后重试成功。
- 达到最大重试次数后安全失败。
- 其他 SDK 错误的安全映射。
- 可选的真实 TokenHub 冒烟测试。

真实 TokenHub 测试默认跳过，避免本地测试或 CI 在未授权的情况下使用密钥、网络和远程
调用额度。只有显式提供 API Key 并开启 live test 时才会执行。2026-07-23 已使用环境变量完成
真实验证，API Key 未写入文件或测试输出。

## 环境变量

当前配置层支持以下环境变量：

```text
HY3_API_KEY
HY3_BASE_URL
HY3_MODEL
HY3_TIMEOUT_SECONDS
HY3_MAX_RETRIES
HY3_REASONING_EFFORT
HY3_DATA_DIR
HY3_MAX_FILE_SIZE_MB
HY3_MAX_ROWS
HY3_MAX_COLUMNS
```

主要规则：

- `HY3_DATA_DIR` 必须提供，并且必须是能够解析到的现有目录。
- `HY3_API_KEY` 仅在调用依赖 Hy3 的功能时必须提供。
- `inspect_dataset` 不依赖 `HY3_API_KEY`。
- 默认服务地址为 `https://tokenhub.tencentmaas.com/v1`。
- 默认模型为 `hy3`。
- 不要把真实 API Key 或个人绝对路径提交到 Git。
- `.env.example` 只用作配置参考；Server 不会自动加载 `.env` 文件。

## 当前测试和质量检查结果

最近一次验证在 Windows、Python 3.13.2 环境中完成：

```text
Pytest（离线）：                  148 passed，1 skipped
项目总覆盖率：                   90%
workflow_validator.py 覆盖率：   98%
Ruff 格式检查：          通过
Ruff 代码检查：          通过
Mypy 严格类型检查：      通过
git diff --check：       通过
```

跳过项是 Windows 符号链接安全测试：当前 Windows 环境不允许创建符号链接；在允许创建
符号链接的环境中，该测试仍可执行。真实 TokenHub 调用不属于阶段 B，未在本轮质量门禁中
启用。

仓库中自带的 `uv.exe` 也已经成功执行离线测试。当前运行环境的默认 uv 缓存目录没有写入
权限，因此测试时将 `UV_CACHE_DIR` 临时指向了仓库内的可写缓存目录。这只是当前环境的
解决方式，不是项目运行的强制要求。

## 开发检查命令

在当前子项目目录运行以下命令：

```powershell
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=hy3_data_analyst_mcp --cov-report=term-missing
```

如果默认 uv 缓存目录不可写，可以先将缓存指向任意可写目录：

```powershell
$env:UV_CACHE_DIR = "ABSOLUTE_PATH_TO_WRITABLE_CACHE"
```

## 可选的 TokenHub 真实测试

真实测试必须通过进程环境提供密钥，禁止将密钥写进代码或提交到 Git：

```powershell
$env:HY3_API_KEY = "YOUR_TOKENHUB_API_KEY"
$env:HY3_RUN_LIVE_TESTS = "1"
uv run pytest -m live tests/integration/test_hy3_client.py
```

2026-07-23 的真实验证发现，顶层 `reasoning_effort` 会导致 TokenHub 返回空的标准
`message.content`，内容只出现在非标准 reasoning 字段。客户端现已按 Hy3 官方调用方式改为
`chat_template_kwargs.reasoning_effort`；`low` 映射为 `no_think` 后 live test 正常返回标准
content。真实 `analyze_dataset` 随后成功完成分组计划、4 条本地 Evidence 和证据解释；真实
`suggest_visualization` 成功返回 bar 与 scatter 两项通过字段校验的建议。

## 阶段 E 的实现详情

- `AnalysisPlan` 使用严格 Schema，禁止额外字段，操作仅限 `describe`、
  `groupby_aggregate`、`top_k`、`correlation`、`time_trend`、`missing_values` 和
  `outlier_iqr`。
- 每种操作会校验必需参数，Planner 还会把目标列、分组列和时间列与真实数据集列名比对，
  拒绝模型发明的列。
- 首次计划无效时执行一次受约束修复；第二次仍无效则返回可读的
  `InvalidAnalysisPlanError`。
- Executor 仅调用预先编写的 Pandas 函数，不使用 `eval()`、`exec()`、动态 SQL、
  `DataFrame.query()` 或模型生成代码。
- 执行结果最多返回 100 条记录，并在截断时附带警告。
- Planner 只接收问题、列语义、局部统计和行数；解释器只接收问题、已验证计划和确定性
  Evidence，不会接收完整 DataFrame。
- `analyze_dataset` 拒绝空问题和超过 4000 字符的问题，并把项目异常转换成稳定的工具错误。

阶段 E 测试覆盖 7 类执行器、非数值列错误、无效日期列、计划参数约束、额外字段、虚构
列名、修复成功、两次失败、Evidence 传递以及端到端分析服务编排。

## 阶段 F～K 的实现和部署状态

- 图表建议只允许 bar、line、scatter、histogram 和 box，所有字段映射都必须来自真实列名；
  无效结果仅修复一次，不会静默替换字段。
- 已生成 `dist/hy3_data_analyst_mcp-0.1.0-py3-none-any.whl` 和源码包。
- 已通过 `uv tool install --force .` 安装用户级命令，并在子项目之外完成 stdio 初始化；
  `tools/list` 返回且只返回三个预期工具。
- [CodeBuddy 模板](examples/codebuddy.mcp.json) 和 [Cursor 模板](examples/cursor.mcp.json)
  均使用占位密钥与占位绝对路径。Cursor 模板复制到 `.cursor/mcp.json` 后需重载客户端。
- 已添加 [架构说明](docs/architecture.md)、[安全说明](docs/security.md) 和
  [演示脚本](docs/demo-script.md)，示例销售数据位于 `examples/data/sales.csv`。
- CI 工作流覆盖 Windows/Ubuntu 和 Python 3.10/3.12，但只有推送到 GitHub 后才能确认远端
  runner 结果。

## 下一阶段

TokenHub API 及服务端真实调用已经验证。仍需用户参与的下一步是在 CodeBuddy 和 Cursor 中
分别确认客户端发现及调用三个工具，并按演示脚本录制 GIF/视频。未经明确授权，本轮不会
提交、推送或创建 PR。
