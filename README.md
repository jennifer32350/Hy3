# Hy3 Data Analyst MCP

一个基于 MCP（Model Context Protocol）的本地数据分析 Server。它读取受限目录内的
CSV、JSON 或 JSONL 文件，调用 Hy3 规划分析与解释结果，并由本地 Pandas 执行确定性计算。
任何支持 stdio MCP 的客户端都可以直接接入。

## 功能

Server 暴露 4 个工具：

| Tool | 作用 | 主要参数 | 是否调用 Hy3 |
| --- | --- | --- | --- |
| `inspect_dataset` | 检查字段、缺失值、重复值、类型和样例数据 | `file_path`、`encoding`、`sample_rows` | 否 |
| `analyze_dataset` | 根据自然语言问题规划并执行数据分析，返回证据与结论 | `file_path`、`question`、`reasoning_effort`、`output_mode`、`max_steps` | 是 |
| `suggest_visualization` | 根据分析目标生成经过字段校验的图表方案 | `file_path`、`goal`、`max_suggestions` | 是 |
| `render_visualization` | 将图表方案渲染为 PNG，并返回 MCP `ImageContent` | `file_path`、`goal`、`max_charts`、`width`、`height`、`chart_specs` | 是 |

核心推理由 Hy3 完成；数据读取、统计计算和图片渲染均在本地执行。Server 不执行模型生成的
Python、SQL 或 Shell 代码。

## 安装

要求 Python 3.10～3.13，并已安装 [uv](https://docs.astral.sh/uv/)。在仓库根目录运行：

```bash
uv tool install --force ./mcp_servers/hy3_data_analyst
hy3-data-analyst-mcp
```

第二条命令会以 stdio 模式启动 Server，通常由 MCP 客户端自动执行，无需手动常驻。

如需从源码开发：

```bash
cd mcp_servers/hy3_data_analyst
uv sync --all-groups
uv run hy3-data-analyst-mcp
```

## 配置

所有凭据和本机路径都通过环境变量传入，代码中没有硬编码 API Key。

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `HY3_API_KEY` | Hy3 工具必填 | 无 | TokenHub 或兼容服务的 API Key |
| `HY3_BASE_URL` | 否 | `https://tokenhub.tencentmaas.com/v1` | OpenAI 兼容接口地址 |
| `HY3_MODEL` | 否 | `hy3` | 模型名称 |
| `HY3_DATA_DIR` | 是 | 无 | 可读取数据文件所在的绝对目录 |
| `HY3_OUTPUT_DIR` | 仅渲染必填 | 无 | 已存在且可写的图片输出绝对目录 |
| `HY3_TIMEOUT_SECONDS` | 否 | `60` | API 超时秒数 |
| `HY3_MAX_RETRIES` | 否 | `2` | 临时错误重试次数 |
| `HY3_REASONING_EFFORT` | 否 | `high` | `low` 或 `high` |

完整配置示例见 `mcp_servers/hy3_data_analyst/.env.example`。Server 不会自动加载 `.env`
文件；请在 MCP 客户端配置的 `env` 中传入变量。不要提交真实密钥或个人绝对路径。

## MCP 客户端接入

仓库提供以下无密钥模板：

- CodeBuddy：`mcp_servers/hy3_data_analyst/examples/codebuddy.mcp.json`
- WorkBuddy：`mcp_servers/hy3_data_analyst/examples/workbuddy.mcp.json`
- Cursor：`mcp_servers/hy3_data_analyst/examples/cursor.mcp.json`

项目级配置示例：

```json
{
  "mcpServers": {
    "hy3-data-analyst": {
      "type": "stdio",
      "command": "hy3-data-analyst-mcp",
      "args": [],
      "env": {
        "HY3_API_KEY": "YOUR_TOKENHUB_API_KEY",
        "HY3_BASE_URL": "https://tokenhub.tencentmaas.com/v1",
        "HY3_MODEL": "hy3",
        "HY3_DATA_DIR": "ABSOLUTE_PATH_TO_DATA",
        "HY3_OUTPUT_DIR": "ABSOLUTE_PATH_TO_EXISTING_OUTPUT_DIRECTORY"
      }
    }
  }
}
```

放置位置：

- CodeBuddy：项目根目录 `.codebuddy/mcp.json`
- WorkBuddy：项目根目录 `workbuddy.mcp.json`
- Cursor：项目根目录 `.cursor/mcp.json`

保存配置后重启或重新加载客户端，确认工具列表中出现上述 4 个工具。

## 可运行 Demo

示例数据位于 `mcp_servers/hy3_data_analyst/examples/data/sales.csv`。将 `HY3_DATA_DIR` 指向
该目录、`HY3_OUTPUT_DIR` 指向一个已存在的空目录，然后在客户端中输入：

```text
依次调用 inspect_dataset、analyze_dataset、suggest_visualization 和
render_visualization 分析 sales.csv。按 region 计算 profit 与 revenue 的总和及利润率；
渲染时复用 suggest_visualization 返回的 charts，并列出 Evidence ID、结论和 PNG 路径。
不要脱离工具结果自行补数。
```

预期流程：先返回数据概览，再由 Hy3 生成分析计划；本地计算得到可追溯证据，最后返回结论
和 PNG 图表。`inspect_dataset` 可在不配置 `HY3_API_KEY` 时单独运行。

## 安全边界

- 只允许读取 `HY3_DATA_DIR` 内的 CSV、JSON 和 JSONL 文件，并限制文件大小、行数和列数。
- Hy3 只负责生成受 Schema 约束的计划与解释；所有数值由白名单本地操作计算。
- 图表只能写入预先存在的 `HY3_OUTPUT_DIR`，拒绝路径穿越、覆盖和链接目录。
- API Key、Authorization Header、完整原始数据和完整请求体不会写入日志。

## 验证

本地质量检查：

```bash
cd mcp_servers/hy3_data_analyst
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=hy3_data_analyst_mcp --cov-fail-under=85
uv build
```

CodeBuddy 已完成 4 个工具的真实调用验证。按照活动要求，提交 PR 前还需完成第二个 MCP
客户端的复验，并补充客户端实际调用过程的 GIF 或视频；演示材料中不得出现 API Key、个人
路径或未脱敏数据。

## 开发与提交

本项目对应“Build an MCP Server powered by Hy3”实战 issue，应用场景为数据分析。开发完成
后请从活动分支创建功能分支，并向目标分支 `rhinobird2026` 提交 Pull Request：

https://github.com/Tencent-Hunyuan/Hy3/tree/rhinobird2026

## License

本项目沿用仓库根目录的 `LICENSE`。
