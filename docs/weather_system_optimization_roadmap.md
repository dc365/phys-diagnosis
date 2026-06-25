# 天气系统算法优化记录

本轮按“先主天气系统、再支撑诊断、最后风险联动”的顺序优化天气系统算法。目标是让业务默认图层更多输出 Point / LineString / 平滑 Polygon，避免把所有诊断都作为大面积候选区展示。

## 1. 已调整内容

### 1.1 副热带高压

`weather_diag/features/subtropical_high.py`

- 增加 588 / 5880 / ECMWF geopotential 单位自适应。
- 新增 `height_unit`、`threshold_source`、`contour_value`、`area_km2` 等属性。
- 保留原有边界平滑逻辑，地图展示更平滑，但不改变诊断统计。

### 1.2 锋面分类

`weather_diag/features/front.py`

- 已支持 `cold_front`、`warm_front`、`stationary_front`、`mixed_front`、`front_candidate`。
- 分类基于 `∇T` 法向风 `V850·∇T/|∇T|` 和温度平流 `-V850·∇T`。
- 配置参数已加入 `configs/thresholds.yaml` 的 `front_candidate` 节点。

### 1.3 切变线

`weather_diag/features/shear_line.py`

新增独立切变线算法：

- 输入：`uv850/uv700/uv500`，可选 `temperature`、`moisture`。
- 判据：正涡度带、低层辐合、风场形变、风速支撑。
- 如果温度梯度也很强，则输出 `front_with_shear`，否则输出 `shear_line`。
- 这样可以把“风场切变线”和“温度锋面”分开，避免槽线或锋面算法被迫解释所有线状系统。

### 1.4 低涡 / 冷涡

`weather_diag/features/vortex.py`

新增 850/700/500hPa 低涡与冷涡候选：

- 高度场闭合低值中心；
- 可选相对涡度正值支撑；
- 可选温度负距平冷心支撑；
- 输出 Point 对象，用于关联槽线、强降水和冷涡强对流风险。

### 1.5 高空急流和急流出口区

`weather_diag/features/upper_jet.py`

新增：

- `upper_jet`：200/300hPa 风速高值轴；
- `upper_jet_exit_region`：高空急流相关辐散区候选。

高空急流用于补足强降水和强对流的高空动力支撑。

### 1.6 PV 异常 / 干侵入支撑诊断

`weather_diag/features/pv_anomaly.py`

新增高空 PV 异常区，用于强对流、冰雹、雷暴大风和斜压系统发展的支撑诊断。默认建议作为辅助图层，而不是主天气系统。

### 1.7 低层辐合 / 高空辐散轴线

`weather_diag/features/convergence.py`

在保留 Polygon 面对象的基础上，新增：

- `detect_low_level_convergence_axes(...)`
- `detect_upper_divergence_axes(...)`

默认业务图可显示轴线，debug 图层再显示原始面对象。

### 1.8 低空急流 / 水汽输送带排序

`weather_diag/features/transport_objects.py`

原排序偏向“长线”。本轮改成综合排序：

```text
rank_score = mean_value + max_value + capped_length + direction_coherence
```

同时增加流线追踪转角限制和小缺口容忍，降低长而弱、方向杂乱的伪轴线优先级。

## 2. 已加入配置

`configs/thresholds.yaml` 新增或扩展：

- `subtropical_high.auto_unit`
- `front_candidate.cross_front_wind_min_ms`
- `front_candidate.stationary_cross_front_max_ms`
- `front_candidate.front_type_consistency_min`
- `front_candidate.front_type_mixed_gap`
- `shear_line`
- `vortex`
- `upper_jet`
- 低空急流 / 水汽输送带综合排序参数

## 3. 下一步建议

### 3.1 接入综合形势接口

新增模块目前已可作为独立 feature 算法使用。下一步建议把它们接入 `weather_diag/diagnosis/nafp_situation.py`：

- `shear_line_850/700/500`
- `cold_vortex_500`、`vortex_700/850`
- `upper_jet_200/300`
- `pv_anomaly_300`
- convergence / divergence axis

接入时注意不要把所有辅助层都作为主图层默认展示。建议 `primary` 策略为：主系统优先，支撑诊断默认折叠。

### 3.2 前端图层分组

建议 MapLibre 图层分组：

```text
主天气系统：副高、槽线、脊线、锋面、切变线、低涡/冷涡、低空急流、水汽输送带
支撑诊断：低层辐合、辐合轴、高空辐散、辐散轴、PV异常、高空急流、急流出口区
风险图层：强降水、短时强降水、雷暴大风、冰雹、旋转风暴、强对流综合
Debug：mask、bbox、score_grid、source_area
```

### 3.3 验证集

建议用 `test_datas/NAFP_ECTHIN_NC` 里典型个例建立人工标注验证集：

- 槽线和切变线的平均距离误差；
- 副高西伸脊点误差；
- 低涡/冷涡命中率；
- 锋面冷/暖/静止分类准确率；
- 风险区和实况/业务预警重叠度。
