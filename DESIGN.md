# 天气形势分析与物理量诊断工作台设计约定

## Visual Theme and Atmosphere

界面定位为气象值班研判台，不是通用 SaaS 后台。整体气质冷静、密集、可追溯，像高空天气图、雷达屏和业务填图台合在一起。第一屏必须让人立刻知道这里在做数值预报资料诊断、天气系统识别和物理量证据复核。

## Color Palette and Roles

| Token | Value | Role |
| --- | --- | --- |
| `--sky-canvas` | `oklch(96.2% 0.009 220)` | 主画布，高空云图冷灰 |
| `--cloud-panel` | `oklch(99% 0.004 220)` | 普通面板 |
| `--cloud-panel-raised` | `oklch(100% 0 0)` | 抬升面板和当前状态 |
| `--cloud-inset` | `oklch(94.7% 0.012 220)` | 输入、表头、内嵌区域 |
| `--radar-cyan` | `oklch(57% 0.105 214)` | 主操作、选中态、证据节点 |
| `--warning-red` | `oklch(47% 0.16 31)` | 高风险和错误 |
| `--alert-amber` | `oklch(61% 0.13 72)` | 中风险和注意 |
| `--field-green` | `oklch(52% 0.105 158)` | 数据可用、成功 |

## Typography Rules

使用系统字体栈，Latin first，CJK fallback：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif`。中文界面不做负字距，数字统一使用 tabular numerals。标题靠字重和层级建立秩序，避免营销页式大字号。

## Component Stylings

按钮使用 6px 半径，按压时 `scale(0.96)`，只动画 `transform, background-color, color, box-shadow`。面板使用 8px 半径，以 1px 等值线边界和轻阴影表达层级。状态条不是营销指标卡，而是值班运行条：有效时间、完整率、天气系统、风险诊断、状态说明。

## Layout Principles

桌面端固定左侧导航，右侧工作区独立滚动。页面内容遵循“先定参数、再看状态、再看对象和证据”的顺序。诊断、区域风险和算法治理使用相同的模块头、操作条、状态条和证据面板结构。主工作区顶部保留一条工作台路径，用于提示数据编码、多时效诊断、天气系统、风险复核和规则治理之间的关系。

## Depth and Elevation

深度由背景色阶和细边界表达，不使用玻璃拟态、厚重投影、装饰渐变。主画布、侧栏、面板、输入区分别使用 `--sky-canvas`、`--cloud-panel`、`--cloud-panel-raised`、`--cloud-inset`。

## Do's and Don'ts

- Do: 把证据链、source_grid、字段、阈值和贡献权重放在可追溯轨迹上。
- Do: 让长列表有分组、摘要和局部滚动。
- Do: 数字右对齐，时效、评分和百分比使用等宽数字。
- Do: 色彩只表达风险、成功、行动和证据。
- Do not: 用卡片堆满页面。
- Do not: 使用紫蓝渐变、玻璃拟态或大面积装饰色。
- Do not: 让侧栏和主画布像两个不同产品。

## Responsive Behavior

桌面端为 244px 到 264px 左导航加右侧工作区。1180px 以下降低列数，760px 以下导航改为顶部网格，所有工作流改为单列。触控目标最小 40px，预报时效和治理组别使用可横向或局部滚动的矩阵。

## Agent Prompt Guide

- 新增诊断模块：使用 `--sky-canvas` 画布、`--cloud-panel` 面板、8px 半径、14px 模块间距，顶部必须有参数区和状态条。
- 新增证据详情：使用 1px `--analysis-rail` 轨迹，节点为 `--radar-cyan`，每个证据项显示字段、数值、贡献和来源。
- 新增表格：表头背景 `--cloud-inset`，行分隔线 `--line-soft`，数字列右对齐，禁止交替斑马纹除非超过 12 列。
