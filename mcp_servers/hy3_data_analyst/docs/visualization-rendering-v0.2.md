# v0.2 阶段 F：可信图表与安全 PNG 渲染

阶段 F 将原有的图表文字建议扩展为可执行 Chart Spec，并新增 `render_visualization`。Hy3 只
选择简单的图表类型、字段和聚合；本地编译器生成受限 `AnalysisWorkflow`，再由校验器、质量层
与工作流执行器计算数据。Renderer 只读取绑定到 `evidence_id` 的确定性 records。

## 公开契约

`suggest_visualization` 保留原有参数和 `suggestions` 返回字段，并增加 `quality_policy`、
`data_plan`、`evidence_id`、`sort`、`limit` 和 `notes`。建议数量仍兼容 1～5。

`render_visualization` 参数边界：

- `max_charts`：1～3，默认 2，并且不能超过 `HY3_MAX_CHARTS`；
- `width`：480～1920，默认 1200；
- `height`：320～1080，默认 720；
- `quality_policy`：与分析工具相同的显式质量策略；
- `chart_specs`：可选；传入 `suggest_visualization.charts` 后复用已验证计划，不再请求 Hy3
  重新规划；计划仍会在本地重新校验和执行；
- 每张图返回一段 JSON TextContent 元数据和一个 `image/png` ImageContent。

支持 bar、line、scatter、histogram 和 box。字段必须存在于绑定 Evidence 的 records 中，数值
轴必须包含有限数值；无有效点时安全失败。排序、limit、缺失剔除、非有限值剔除、确定性采样、
Top-N 和 Other 合并均写入可视化元数据，返回给客户端的数据与实际绘图数据一致。

## 输出安全

- Matplotlib 强制使用无界面 Agg backend，不启动浏览器或 GUI；
- `HY3_OUTPUT_DIR` 必须预先存在，只在渲染工具中要求；
- URL、UNC、符号链接和 Windows reparse point 被拒绝；
- 服务端生成 UUID 文件名，不使用用户 goal/title；
- PNG 先在内存中生成并校验签名与大小，再使用 `xb` 排他写入；
- 写入后重新解析路径，确认仍位于输出根目录且大小未变化；
- 单图硬上限 5 MB，批次中任一失败会清理本次已经创建的图，不触碰旧文件。

旧图文件采用调用方管理策略：Server 不自动删除既有输出，避免后台清理误删用户仍在使用的
生成物。调用方可根据 TextContent 中的输出文件名，在确认不再需要后清理。

## 验证范围

自动化测试覆盖 Chart Spec Schema、虚构字段和 Evidence 绑定、一次 Repair、五类图表 PNG、
尺寸与 MIME、缺失/非有限值、类别折叠、文件大小、排他写入、输出目录缺失、链接/reparse
point，以及 FastMCP `tools/list` 的四工具协议面。

CodeBuddy 四工具真实调用已完成；Cursor/第二客户端图像展示和录屏仍依赖用户客户端与授权
Hy3 endpoint，属于阶段 G 人工验收，离线测试不能替代。
