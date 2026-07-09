# MCP 多窗口接口改造交接文档

最近更新：2026-07-04

本文用于交接本次 `get_town_risk_dsl` 和 `get_point_risk` 两个 MCP 工具接口的代码改动、测试文件、接口文档、验证结果和后续联调建议。

第三方调用方的详细接口协议见：

```text
docs/mcp_third_party_integration.md
```

## 1. 本次改了哪些接口

### 1.1 `get_town_risk_dsl`

入口函数：

```text
weather_diag/mcp/area_risk_dsl_mcp.py::get_town_risk_dsl
```

核心实现：

```text
weather_diag/mcp/area_risk_dsl.py::get_town_risk_dsl_payload
```

主要改动：

- 新增 `windows` 多窗口模式。
- 新增三种时间匹配策略：
  - `single_latest_run`
  - `fixed_run`
  - `latest_per_valid_time`
- 新增并转发 `run_time`，用于 `fixed_run` 指定起报时间。
- 新增 `include_window_summary`，控制多窗口模式是否输出归纳结果。
- 保持未传 `windows` 时的原有返回结构不变。
- 多窗口模式返回：
  - `data.mode = "multi_window_evidence"`
  - `data.windows[]`
- 每个 window 返回：
  - `label`
  - `start_time`
  - `end_time`
  - `time_match_policy`
  - `model_metadata`
  - `dsl`
  - `failures`
- 支持一个时间窗口跨多个起报时间，DSL 中用多个 `@T/@DT/#PHY` 分组拼接。
- 不新增 `#RUN` 标记。
- 新增风险归纳 DSL：
  - `#SUMMARY_RISK`
  - `#SUMMARY_TOWN_RISK`
- 新增物理量归纳 DSL：
  - `#SUMMARY_PHY`
  - `#SUMMARY_TOWN_PHY`
- 物理量归纳规则：
  - `gte` 字段取最大值作为极值。
  - `lte` 字段取最小值作为极值。

### 1.2 `get_point_risk`

入口函数：

```text
weather_diag/mcp/area_risk_dsl_mcp.py::get_point_risk
```

核心实现：

```text
weather_diag/mcp/point_risk.py::get_point_risk_payload
```

主要改动：

- 新增 `windows` 多窗口模式。
- 复用和 `get_town_risk_dsl` 一致的三种时间匹配策略。
- 新增并转发 `run_time`，用于 `fixed_run` 指定起报时间。
- 新增 `include_window_summary`，控制多窗口模式是否输出归纳数组。
- 保持未传 `windows` 时的原有返回结构不变。
- MCP wrapper 支持结构化 `points` 和 `windows`，同时兼容原来的字符串/JSON 字符串形式。
- 显式传入的重复点位 ID 会直接报错，避免归纳时把不同点位合并。
- 多窗口模式返回：
  - `data.mode = "multi_window_point_risk"`
  - `data.windows[]`
- 每个 window 返回：
  - `label`
  - `start_time`
  - `end_time`
  - `time_match_policy`
  - `model_metadata`
  - `items`
  - `risk_summary`
  - `point_summary`
  - `physical_summary`
  - `point_physical_summary`
  - `failures`
- `get_point_risk` 仍然是 JSON 证据接口，不输出 DSL。

## 2. 需要交接的代码文件

### 2.1 运行时代码

| 文件 | 说明 |
| --- | --- |
| `weather_diag/mcp/area_risk_dsl_mcp.py` | 两个 MCP 工具的入口层。暴露并转发 `windows`、`time_match_policy`、`run_time`、`include_window_summary` 等参数。 |
| `weather_diag/mcp/area_risk_dsl.py` | `get_town_risk_dsl` 的核心实现。包含多窗口 payload、时间匹配、DSL 拼接、风险归纳和物理量归纳。 |
| `weather_diag/mcp/point_risk.py` | `get_point_risk` 的核心实现。包含多窗口 payload、点位证据、风险归纳、物理量归纳、结构化点位解析和重复点位 ID 校验。 |
| `weather_diag/diagnosis/area_risk.py` | 乡镇风险计算增加了请求级缓存参数，供多窗口模式复用产品读取和评分结果。 |

### 2.2 测试文件

| 文件 | 说明 |
| --- | --- |
| `tests/test_area_risk_dsl.py` | 覆盖乡镇 DSL 的结构化 `windows`、多窗口 DSL、风险归纳、物理量归纳、返回全部窗口等行为。 |
| `tests/test_point_risk_mcp.py` | 覆盖点位多窗口、缓存复用、风险归纳、物理量归纳、wrapper 参数转发、结构化点位/窗口、重复点位 ID 校验等行为。 |

## 3. 相关参考文档

| 文件 | 面向对象 | 说明 |
| --- | --- | --- |
| `docs/mcp_third_party_integration.md` | 第三方调用方、项目负责人 | 最完整的接口对接文档，包含字段说明、请求示例、响应示例和错误处理。 |
| `docs/mcp_multi_window_handoff.md` | 接手代码的人、项目负责人 | 本交接清单，说明代码改动、测试、验证和后续联调建议。 |
| `docs/api.md` | 项目 API 阅读者 | 原有 API 概览文档，已补充 MCP 详细文档入口。 |
| `docs/town_risk_dsl_multi_window_design.md` | 开发/审查人员 | `get_town_risk_dsl` 多窗口设计和实现计划。 |
| `docs/point_risk_multi_window_design.md` | 开发/审查人员 | `get_point_risk` 多窗口设计和实现计划。 |

## 4. AI 外置状态文件

这些文件不是运行时代码，但记录了本次任务的上下文、风险和审查结果。后续如果继续用 Codex/AI 协助维护，建议一起交接。

| 文件 | 说明 |
| --- | --- |
| `doc/api.md` | AI 外置接口摘要。 |
| `doc/progress.md` | 当前任务进度和完成状态。 |
| `doc/bugs.md` | 已发现风险、已修复问题、未解决环境问题。 |
| `doc/review.md` | 审查记录和当前审查结论。 |
| `doc/task/town-risk-dsl-multi-window.md` | `get_town_risk_dsl` 多窗口任务记录。 |
| `doc/task/point-risk-multi-window.md` | `get_point_risk` 多窗口任务记录。 |
| `doc/task/physical-summary.md` | 物理量归纳任务记录。 |
| `doc/task/mcp-third-party-integration-doc.md` | 第三方对接文档任务记录。 |

## 5. 参数协议摘要

两个工具共同新增或扩展的参数：

| 参数 | MCP wrapper 类型 | 说明 |
| --- | --- | --- |
| `windows` | `str | dict[str, Any] | list[Any] | None` | 开启多窗口模式。不传时保持原有单窗口返回结构。 |
| `time_match_policy` | `str | None` | 时间匹配策略，支持 `single_latest_run`、`fixed_run`、`latest_per_valid_time`。 |
| `run_time` | `str | None` | 当 `time_match_policy=fixed_run` 时必填，用于指定起报时间。 |
| `include_window_summary` | `bool` | 控制多窗口模式是否输出归纳结果。 |

`get_point_risk` 额外输入：

| 参数 | MCP wrapper 类型 | 说明 |
| --- | --- | --- |
| `points` | `str | dict[str, Any] | list[Any]` | 必填，支持单点、点位数组、原有文本格式、JSON 字符串格式。 |

注意：

- `models` 在 MCP wrapper 中仍然是字符串。
- 多模式用逗号分隔，例如：

```text
EC,CMA-GFS
```

## 6. 返回结构兼容性

未传 `windows` 时，保持原有结构：

- `get_town_risk_dsl` 返回顶层 `data.dsl`。
- `get_point_risk` 返回顶层 `data.items[]`。

传入 `windows` 时进入多窗口模式：

- `get_town_risk_dsl` 返回：

```text
data.mode = "multi_window_evidence"
data.windows[]
```

- `get_point_risk` 返回：

```text
data.mode = "multi_window_point_risk"
data.windows[]
```

接口只提供每个时间窗口的证据和确定性归纳，不负责生成跨窗口自然语言结论。第三方需要自行比较不同 window 的归纳字段，并生成最终分析结论。

## 7. 时间匹配规则

所有时间匹配都基于：

```text
valid_time = run_time + forecast_hour
```

三种策略：

| 策略 | 说明 |
| --- | --- |
| `single_latest_run` | 从最新起报时间开始找，取第一份能覆盖请求时间窗口内至少一个有效时次的数据。 |
| `fixed_run` | 只使用调用方指定的 `run_time`，再筛选落在窗口内的 forecast hour；如果没有命中则报错。 |
| `latest_per_valid_time` | 对窗口内每个有效时次，选择能覆盖该有效时次的最新起报时间，再按起报时间分组返回。 |

默认值：

| 模式 | 默认策略 |
| --- | --- |
| 不传 `windows` | `single_latest_run` |
| 传入 `windows` | `latest_per_valid_time` |

## 8. 已执行验证

实现阶段通过的目标验证：

```powershell
& 'C:\Users\lisr\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m py_compile weather_diag\mcp\area_risk_dsl.py weather_diag\mcp\point_risk.py weather_diag\mcp\area_risk_dsl_mcp.py tests\test_area_risk_dsl.py tests\test_point_risk_mcp.py
```

```powershell
& 'C:\Users\lisr\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests\test_area_risk_dsl.py tests\test_point_risk_mcp.py
```

结果：

```text
17 passed
```

对接文档修复后执行过的文档验证：

- `docs/mcp_third_party_integration.md` 中 18 个 JSON 示例块全部可解析。
- 已确认 `models` 类型说明、失败路径、`yesterday/today` 两个响应窗口都已写入文档。

完整测试套件注意事项：

- 当前 Windows 工作区中 `pytest -q` 不是全绿。
- 失败原因是已有样例数据路径、配置、服务脚本等环境问题，已记录在 `doc/bugs.md`。
- 这些 full-suite 失败不是本次 MCP 多窗口改造引入的特定失败。

## 9. 后续联调建议

交接后建议继续做：

- 用真实第三方 MCP 客户端测试结构化 `points/windows`。
- 同时测试 JSON 字符串形式的 `points/windows`，作为兼容兜底。
- 用真实数据调用一次 `get_town_risk_dsl`。
- 用真实数据调用一次 `get_point_risk`。
- 检查 `data.windows[].failures[]` 是否为空。
- 如果存在缺失产品导致的 failures，需要作为部分证据返回，不应当当成全量结论。

## 10. 建议交回文件清单

最小交接包只需要本交接文档、修改过的运行时代码和测试代码：

```text
docs/mcp_multi_window_handoff.md
weather_diag/mcp/area_risk_dsl_mcp.py
weather_diag/mcp/area_risk_dsl.py
weather_diag/mcp/point_risk.py
weather_diag/diagnosis/area_risk.py
tests/test_area_risk_dsl.py
tests/test_point_risk_mcp.py
```

以下文件不是最小交接包必需内容；如果接手方需要追溯设计过程、完整接口示例或 AI 协作状态，再按需提供：

```text
docs/mcp_third_party_integration.md
docs/api.md
docs/town_risk_dsl_multi_window_design.md
docs/point_risk_multi_window_design.md
doc/api.md
doc/progress.md
doc/bugs.md
doc/review.md
doc/task/town-risk-dsl-multi-window.md
doc/task/point-risk-multi-window.md
doc/task/physical-summary.md
doc/task/mcp-third-party-integration-doc.md
```
