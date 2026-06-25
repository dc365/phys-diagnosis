# 天气形势分析与物理量诊断工作台

这是一个天气形势分析与物理量诊断工程，用于基于 **ECMWF/EC 模式 NetCDF 格点数据**进行：

- NetCDF 数据读取与变量标准化
- 天气系统客观识别
- 物理量诊断
- 多灾种风险评分
- MapLibre GIS 展示

## 当前天气系统算法补充

近期已补充以下天气系统或支撑诊断算法：

- 锋面候选细分：冷锋、暖锋、静止锋、混合锋面候选。
- 850/700/500hPa 切变线候选。
- 500/700/850hPa 低涡、冷涡候选。
- 200/300hPa 高空急流与急流出口辐散区。
- 高空 PV 异常 / 干侵入支撑诊断。
- 地面温度、露点和 10m 风边界候选。
- 低层辐合、高空辐散轴线提取。
- 副高 588/5880 单位自适应。

详细说明见 `docs/weather_system_optimization_roadmap.md`、`docs/weather_system_layering.md` 和 `docs/front_classification.md`。
