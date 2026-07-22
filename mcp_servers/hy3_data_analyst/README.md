# Hy3 数据分析 MCP

Hy3 数据分析 MCP 是一个可安装的本地 stdio MCP Server。当前版本可以安全检查 CSV、
JSON 和 JSONL 数据集；后续阶段将通过 OpenAI 兼容接口调用 Hy3，让 Hy3 负责规划分析和
解释证据，并由 Pandas 完成确定性的数值计算。

> 当前进度：阶段 A～D 的离线开发已经完成，阶段 E～M 尚未实现。
> 当前开发分支：`hy3-data-analyst-mcp`。
> 最后更新日期：2026-07-22。

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

Server 当前会公开以下三个工具：

- `inspect_dataset`：已经实现并可用。
- `analyze_dataset`：工具接口已存在，阶段 E 完成前会明确返回尚未实现的信息。
- `suggest_visualization`：工具接口已存在，阶段 F 完成前会明确返回尚未实现的信息。

## 完整开发进度

| 阶段 | 工作范围 | 当前状态 | 已完成结果或待办事项 |
| --- | --- | --- | --- |
| A | 软件包骨架和 FastMCP stdio Server | 已完成 | 已创建项目元数据、控制台入口、Server 和三个工具接口。 |
| B | 配置、文件路径安全和数据加载 | 已完成 | 可在允许目录内读取 CSV、JSON 数组和 JSONL，并执行文件、行数和列数限制。 |
| C | 数据集概览和 `inspect_dataset` | 已完成 | 可在没有 `HY3_API_KEY` 时执行确定性的、可序列化为 JSON 的数据检查。 |
| D | OpenAI 兼容的 Hy3 API 客户端 | 离线部分已完成 | 普通响应、结构化响应、延迟创建、依赖注入、错误映射、超时和有限重试均已通过 mock 测试。真实 TokenHub 测试待 API Key。 |
| E | 分析计划、执行器、Planner、证据、分析服务和 `analyze_dataset` | 待开发 | 尚未实现。 |
| F | 图表模型、字段验证、提示词和 `suggest_visualization` | 待开发 | 尚未实现。 |
| G | MCP 协议和最终质量门禁 | 待开发 | 当前阶段的检查已经通过；最终门禁需在阶段 E、F 完成后执行。 |
| H | Wheel 构建和全新环境一键安装验证 | 待开发 | 软件包元数据已经存在，最终隔离安装验证尚未执行。 |
| I | CodeBuddy 和 Cursor 配置 | 待开发 | 配置模板和真实客户端验证尚未完成。 |
| J | 完整中英文说明、架构和安全文档 | 待开发 | 当前文件主要记录开发状态，还不是最终完整使用手册。 |
| K | Windows 和 Ubuntu CI | 待开发 | GitHub Actions 工作流尚未创建。 |
| L | 真实客户端验证和演示录制 | 待开发 | 需要 TokenHub 权限以及用户参与客户端操作和录屏。 |
| M | 根 README 入口和 Pull Request 准备 | 待开发 | 必须等前面的阶段全部通过后再执行。 |

## 阶段 D 的实现详情

`src/hy3_data_analyst_mcp/hy3_client.py` 中的客户端已经实现：

- 延迟创建 `AsyncOpenAI`，因此导入 MCP Server 时不会建立网络连接。
- 支持配置 `base_url`、API Key、模型、超时时间、重试次数和 reasoning effort。
- 使用非流式 Chat Completion 请求。
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
调用额度。只有显式提供 API Key 并开启 live test 时才会执行。

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
Pytest：                 54 passed，2 skipped
项目总覆盖率：           86%
hy3_client.py 覆盖率：  92%
Ruff 格式检查：          通过
Ruff 代码检查：          通过
Mypy 严格类型检查：      通过
git diff --check：       通过
```

两个跳过项分别是：

1. 真实 TokenHub 冒烟测试：当前没有提供 `HY3_API_KEY`，也没有显式开启 live test。
2. Windows 符号链接安全测试：当前 Windows 环境不允许创建符号链接；在允许创建符号链接的
   环境中，该测试仍可执行。

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

当前环境没有提供真实 API Key，因此上述 live test 尚未执行。这不会影响阶段 D 的离线
实现和 mock 验收结果，但真实 TokenHub 兼容性仍需在获得密钥后确认。

## 下一阶段

阶段 E 将实现：

- 受 Pydantic Schema 约束的分析计划。
- 白名单形式的确定性 Pandas 执行器。
- Planner 提示词和一次结构修复机会。
- 分析证据的构造和传递。
- 基于确定性证据的结果解释。
- 完整分析服务编排。
- 可用的 `analyze_dataset` MCP 工具。

项目不会接受或执行模型生成的任意 Python、Shell 或 SQL，也不会使用 `eval()` 或
`exec()` 执行模型输出。
