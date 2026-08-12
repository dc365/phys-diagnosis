# 算法说明

> 天气系统的业务定义、输入要素、算法步骤和地图几何输出，详见 [`docs/weather_systems.md`](weather_systems.md)。
> 本文件保留物理量、诊断流程和风险评分的详细说明。

## 诊断量

### 散度

```text
div = du/dx + dv/dy
convergence = -div
```

低层散度负值表示辐合；高空散度正值表示辐散。

### 相对涡度

```text
vorticity = dv/dx - du/dy
```

北半球正涡度通常表示气旋性旋转。

### 温度平流

```text
temperature_advection = - V · ∇T
```

正值表示暖平流，负值表示冷平流，前提是温度单位和符号定义一致。

### 水汽通量与水汽辐合

```text
Fq = qV
moisture_flux_divergence = ∇ · Fq
moisture_convergence = -∇ · Fq
```

`moisture_flux_divergence` 为负值表示水汽辐合；对业务展示可用
`moisture_convergence = -moisture_flux_divergence` 转成正值含义。

### K 指数

```text
K = (T850 - T500) + Td850 - (T700 - Td700)
```

当前版本在缺少露点时用温度和相对湿度近似计算露点。

## 天气系统识别

当前版本采用规则阈值与物理量证据链结合的对象识别算法：

- 高低压：海平面气压局地极值 + 边界剔除 + 多圈闭合等压线判定
- 低压辐合/高压辐散：500hPa 高度距平中心 + 850hPa 散度分位
- 副高：500hPa 位势高度 >= 5880gpm 区域，并计算西伸脊点、南北界、面积强度和主体形态。
- 辐合区：850hPa 散度负值阈值连通区域
- 高空辐散：200/300hPa 散度正值阈值连通区域
- 低空急流：850hPa 风速高值带 + 水汽通量高值
- 水汽输送带：850hPa 水汽通量高值带
- 槽脊：500hPa 位势高度距平尾部 + 等高线曲率 + 500hPa 涡度支撑轴线
- 锋面候选：温度梯度 + 风场形变 + 锋生函数 + 低层辐合 + 温度平流综合评分

天气系统接口保留完整候选对象，同时为每个对象写入展示元数据：

- `salience_score`：由置信度、几何尺度/连通格点数和证据完整度计算的 0-1 显著性评分。
- `type_rank`：同类对象内的显著性排序。
- `display_rank`：跨类型展示排序，主系统优先。
- `primary`：是否作为地图默认展示的主天气系统。
- `base_confidence`：对原本使用固定模板置信度的候选系统，保留重算前的基础置信度。

地图 NAFP 天气系统默认只展示 `primary=true` 的主系统，避免每类 `max_objects` 打满后遮挡过多；接口仍保留完整候选列表，便于后续查看支撑对象和算法调试。

### 地面高压/低压中心

地图天气系统中的 `high` / `low` 使用海平面气压 `mslp`：

1. 对气压场做轻量平滑，降低单格点噪声。
2. 用局地最大/最小值寻找候选中心。
3. 剔除靠近资料边界的极值点，避免边界截断造成伪中心。
4. 从中心值向外按 `contour_interval_hpa` 逐圈扩展，检查包含中心的高压/低压区域是否仍为闭合区域。
5. 至少满足 `min_closed_contours` 圈闭合等压线，并达到 `min_prominence_hpa` 的相对周边差异后才输出中心。

默认阈值：

- `pressure_system.min_prominence_hpa`：中心相对周边的最小差异，默认 0.5 hPa。
- `pressure_system.min_distance_grid`：局地极值搜索窗口，默认 6 个格点。
- `pressure_system.max_centers`：每类最大输出中心数，默认 20。
- `pressure_system.contour_interval_hpa`：闭合等压线检查间隔，默认 1.0 hPa。
- `pressure_system.min_closed_contours`：最少闭合等压线圈数，默认 2。
- `pressure_system.max_closed_contours`：最多向外检查圈数，默认 8。
- `pressure_system.edge_margin_grid`：边界剔除宽度，默认 2 个格点。
- `pressure_system.smoothing_sigma_grid`：气压场平滑尺度，默认 1.0 个格点。

输出仍为点要素，但证据中会包含闭合等压线圈数、最外闭合等压线值、中心到外圈的气压差和闭合区域格点数。

### NAFP 500hPa 副热带高压

NAFP 天气形势诊断中的副高使用 `gh/500`：

1. 根据高度场单位选择 588dagpm 或 5880gpm 阈值。
2. 提取达到阈值的最大连续 588 区，过滤过小斑块。
3. 统计主体中心、最大/平均高度、面积格点数、东西边界和南北界。
4. 在最西侧达到阈值的格点中选高度最高点作为西伸脊点。
5. 按经向/纬向跨度给出 `axis_orientation`，用于区分纬向带状、西伸明显或紧凑型主体。
6. 对业务展示 Polygon 做边界平滑：将格点 union 得到的 588 区边界投影到局地公里坐标，按 `boundary_smooth_km` 做圆角化，再用 `boundary_simplify_km` 做拓扑保持简化；该步骤只改善地图观感，不改变西伸脊点、北界、平均高度和面积格点数等诊断统计。

输出字段包括 `center`、`ridge_point`、`north_boundary_lat`、`south_boundary_lat`、`west_boundary_lon`、`east_boundary_lon`、`area_grid_points`、`max_height`、`mean_height`、`threshold_height`、`axis_orientation`、`boundary_smoothed`、`boundary_smooth_km` 和 `boundary_simplify_km`。证据中保留高度阈值、连续面积、西伸脊点和北界信息。

批量天气形势诊断会在成功时效中抽取完整的副高样本，按预报时效排序后比较首末两个样本，输出 `subtropical_high_trend`：

- `west_extension`：比较西伸脊点经度，向西超过 0.25 度记为西伸，向东超过 0.25 度记为东退。
- `north_shift`：比较北界纬度，北界升高超过 0.25 度记为北抬，降低超过 0.25 度记为南落。
- `area_change`：比较 588 区格点面积，相对变化超过 5% 记为扩大或缩小。
- `intensity_change`：比较主体平均高度，变化超过 0.1 个原始高度单位记为增强或减弱。

趋势诊断只使用指标完整的副高样本；若有效样本不足两个，会返回 `available=false` 和“副高时效演变样本不足”的摘要，不影响批量接口返回各时效的单时次诊断结果。

### NAFP 锋面候选

NAFP 天气形势诊断中的锋面候选使用实际 EC 高空产品：

- `tt/850`：850hPa 温度，计算水平温度梯度。
- `uv/850`：850hPa 风场，计算形变和锋生函数。
- `div/850`：850hPa 散度，负值作为低层辐合信号。
- `ttadv/850`：850hPa 温度平流，取绝对值作为冷暖平流变化信号。
- `rh/850`：850hPa 相对湿度，可作为锋区水汽配合信号。

综合评分使用温度梯度和动力支撑共同约束：

```text
frontogenesis = max(-[(Tx^2*dudx + Ty^2*dvdy + Tx*Ty*(dudy+dvdx))] / |∇T|, 0)

front_score = weighted(
  norm(|∇T850|),
  norm(frontogenesis),
  norm(wind_deformation),
  norm(max(-div850, 0)),
  norm(|ttadv850|),
  norm(rh850)
)
```

默认阈值来自后台默认阈值矩阵：

- `system.front_candidate.tt850_gradient_percentile`：温度梯度高值分位，默认 80。
- `system.front_candidate.score_percentile`：综合评分高值分位，默认 82。
- `system.front_candidate.dynamic_support_percentile`：锋生、形变、辐合、平流等支撑项的高值分位，默认 70。
- `system.front_candidate.min_support_components`：风场可用时至少满足的动力支撑项数，默认 1。
- `system.front_candidate.min_points`：连通区最小格点数，默认 10。
- `system.front_candidate.max_objects`：最大输出锋面候选对象数，默认 12。

当 `uv850` 可用时，锋区不仅需要综合评分和温度梯度达标，还必须至少有一个动力支撑项达标，避免单纯温度梯度造成大片误报。输出为 `front_candidate` 多边形区域，并按连通面积和平均评分保留主要对象；证据中包含温度梯度阈值、综合评分阈值、锋生/形变阈值、支撑项数量、连通区大小和输出排序。

### NAFP 500hPa 槽脊轴线候选

NAFP 天气形势诊断中的槽脊轴线使用 `gh/500`，可选使用 `uv/500`：

1. 计算纬向平均背景场。
2. 用 `gh500 - zonal_mean(gh500)` 得到 500hPa 位势高度距平。
3. 对距平场做轻量平滑，并用公里尺度近似导数计算梯度、拉普拉斯和等高线曲率。
4. 用“距平尾部 + 曲率支撑”形成连续槽脊带，避免局地闭合低值或高值中心直接劫持轴线。
5. 在连续带内综合局地低值/高值轴、曲率、距平强度、梯度和可选涡度支撑评分，按主轴投影抽取评分最高的轴线点。
6. 对原始折线按弧长重采样，B 样条平滑后再回贴到评分脊线，并做二次轻平滑，输出 `line` 几何轴线。
7. 当 `uv/500` 可用时，槽线记录正涡度支撑，脊线记录负涡度支撑。

默认阈值来自后台默认阈值矩阵：

- `system.trough_ridge.axis_anomaly_percentile`：槽脊轴线距平尾部分位，默认 20。槽线使用低端 p20，脊线使用高端 p80。
- `system.trough_ridge.curvature_percentile`：曲率支撑分位，默认 55。
- `system.trough_ridge.vorticity_support`：涡度符号支撑，默认阈值 0。
- `system.trough_ridge.min_points_per_line`：轴线最小连续点数，默认 4。
- `system.trough_ridge.max_lines`：每类最大输出轴线数，默认 8。

诊断结果默认仅保留槽/脊轴线 LineString；如需调试候选区，应作为单独 debug 图层输出，同时输出 `geometry.type=line` 的槽线/脊线轴线。轴线证据包含距平尾部分位、曲率均值、涡度符号支撑、连通点数和输出排序；轴线识别来自客观 Z500/UV500 场，不从业务天气图图片中识别棕色线段。

### NAFP 低压辐合与高压辐散候选

NAFP 天气形势诊断中的低压/高压候选使用 `gh/500` 与 `div/850`：

1. 计算纬向平均背景场。
2. 用 `gh500 - zonal_mean(gh500)` 得到 500hPa 位势高度距平。
3. 低压辐合：高度负距平达到低端分位，同时 `div850` 达到低端分位，负散度表示低层辐合。
4. 高压辐散：高度正距平达到高端分位，同时 `div850` 达到高端分位，正散度表示低层辐散。
5. 对叠加掩膜提取连通区，并按格点数排序截断输出。

默认阈值来自后台默认阈值矩阵：

- `system.low_pressure.gh500_anomaly_percentile`：低压候选高度负距平分位，默认 20。
- `system.low_pressure.div850_convergence_percentile`：低压候选低层辐合分位，默认 10。
- `system.high_pressure.gh500_anomaly_percentile`：高压候选高度正距平分位，默认 80。
- `system.high_pressure.div850_divergence_percentile`：高压候选低层辐散分位，默认 90。
- `system.pressure_center.min_points`：低压/高压候选连续区最小格点数，默认 12。
- `system.pressure_center.max_centers`：每类最大输出个数，默认 6。

当前输出为 `low_pressure_convergence` 和 `high_pressure_divergence` 候选区，属于 500/850hPa 配合的自动诊断证据；地面 `high` / `low` 中心另由海平面气压局地极值和闭合等压线识别。若后续接入 850/925hPa 高度场，可继续补充更贴近低层环流的中心判据。

### NAFP 低空急流、水汽输送和水汽辐合

当前版本使用 `uv/850` 与 `q/850` 补充教程中的低层风场和水汽判断逻辑：

1. 计算 `uv850_speed = sqrt(u850^2 + v850^2)`。
2. 计算 `moisture_flux850 = uv850_speed * q850`。
3. 对低空急流和水汽输送带计算风向一致性：`direction_coherence = length(mean(unit_wind_vector))`。
4. 计算 `moisture_flux_divergence850 = d(q*u)/dx + d(q*v)/dy`，负值表示水汽辐合。
5. 对 `moisture_flux_divergence850`、`div850`、`div200/div300` 做轻量格点平滑，降低单格点噪声。
6. 输出 `low_level_jet`、`moisture_transport`、`moisture_convergence` 三类对象。
7. 同时输出 `low_level_convergence` 与 `upper_divergence`，用于识别低层触发和高空抽吸配合。
8. 水汽辐合、低层辐合和高空辐散均按连通面积与平滑后的强度排序，只保留主要对象。

默认阈值来自后台默认阈值矩阵：

- `system.low_level_jet.wind_speed_min`：850hPa 低空急流风速下限，默认 10 m/s。
- `system.low_level_jet.moisture_flux_percentile`：急流区水汽通量配合分位，默认 70。
- `system.low_level_jet.min_direction_coherence`：低空急流轴风向一致性下限，默认 0.65。
- `system.low_level_jet.max_objects`：最大输出低空急流对象数，默认 12。
- `system.moisture_transport.flux_percentile`：水汽输送带高值分位，默认 75。
- `system.moisture_transport.min_direction_coherence`：水汽输送带风向一致性下限，默认 0.65。
- `system.moisture_transport.max_objects`：最大输出水汽输送带对象数，默认 12。
- `system.moisture_convergence.flux_divergence_percentile`：水汽通量散度低值分位，默认 10。
- `system.moisture_convergence.smoothing_sigma_grid`：水汽通量散度平滑尺度，默认 1。
- `system.moisture_convergence.max_objects`：最大输出水汽辐合对象数，默认 12。
- `system.low_level_convergence.div850_percentile`：低层散度低值分位，默认 10。
- `system.low_level_convergence.smoothing_sigma_grid`：低层散度平滑尺度，默认 1。
- `system.low_level_convergence.max_objects`：最大输出低层辐合对象数，默认 12。
- `system.upper_divergence.divergence_percentile`：高空散度高值分位，默认 90。
- `system.upper_divergence.smoothing_sigma_grid`：高空散度平滑尺度，默认 1。
- `system.upper_divergence.max_objects`：最大输出高空辐散对象数，默认 12。

低层辐合在 `uv850` 可用时，还会用风场反算散度做符号一致性过滤；高空辐散会把 200/300hPa 候选放入同一排序池后截断。它们仍属于自动诊断对象，需要结合 500hPa 形势、700hPa 上升运动、温度平流、实况和雷达订正。

### NAFP 批量天气形势演变

批量天气形势诊断在单时次结果之上输出 `situation_evolution`，用于管理界面展示完整天气形势演变面板。当前纳入 5 类主系统：

- 副高：复用 `subtropical_high_trend`，比较西伸脊点、北界、588 区面积和主体平均高度。
- 槽线：使用 `trough_candidate` 中 `geometry.type=line` 且 `primary=true` 的轴线对象。
- 脊线：使用 `ridge_candidate` 中 `geometry.type=line` 且 `primary=true` 的轴线对象。
- 低空急流：使用 `low_level_jet` 主线状对象。
- 水汽输送：使用 `moisture_transport` 主线状对象。

线状系统按预报时效排序，只比较首末两个完整样本。每个样本统计：

- `object_count`：主展示线对象数量。
- `mean_center_lon` / `mean_center_lat`：主线对象坐标均值中心。
- `mean_axis_length_degrees`：主线对象折线长度均值，单位为经纬度度。
- `mean_confidence`：主线对象平均置信度。

趋势项包括：

- `position_change`：中心经向/纬向迁移，超过 0.25 度分别记为东移/西移、北抬/南落。
- `count_change`：主对象数量增多、减少或持平。
- `length_change`：轴线长度相对变化超过 5% 记为增长或缩短。
- `confidence_change`：平均置信度变化超过 0.03 记为增强或减弱。

该设计故意只使用 `primary=true` 的主线对象：槽脊接口仍保留轴线和距平候选区域，演变摘要不把支撑诊断的候选区域混入主天气系统演变。

## 风险评分

强降水潜势综合评分：

- 水汽通量
- 水汽辐合
- 低层辐合
- 700hPa 上升运动
- K 指数
- CAPE
- 模式降水

强对流潜势综合评分：

- CAPE
- CIN
- K 指数
- 深层风切变
- LI、DCAPE、SRH 或 0-1km 切变
- 低层辐合
- 低层水汽
- 高空辐散、PV 和 PV 平流

多风险格点输出直接按灾种生成 6 类风险场：

- `risk_persistent_heavy_rain_score`：持续性强降水，综合水汽输送、水汽辐合、上升运动和累计降水。
- `risk_short_duration_heavy_rain_score`：短时强降水，综合低层水汽、CAPE/K 指数、低层触发和水汽辐合。
- `risk_thunderstorm_gale_score`：雷暴大风/下击暴流，综合 DCAPE、深层风切变、CAPE 和低层触发。
- `risk_hail_score`：冰雹，综合 CAPE、深层风切变和冷性层结代理指标。
- `risk_rotating_storm_score`：旋转风暴/超级单体潜势，综合 CAPE、深层风切变、低层切变或 SRH。
- `risk_severe_convection_composite_score`：强对流综合风险，由短时强降水、雷暴大风/下击暴流、冰雹和旋转风暴风险取大值。

这 6 类风险产品均输出为 0-1 格点场，格点值表示该风险类别的相对风险评分。风险类别不是互斥结论，同一格点可以同时具有短时强降水、雷暴大风/下击暴流、冰雹等多个风险分值；最终面/点诊断会把这些格点场整理为 `risk_diagnoses` 多灾种结论列表。前端展示时按两个业务通道组织：强降水风险包含持续性强降水和短时强降水，强对流风险包含短时强降水、雷暴大风/下击暴流、冰雹、旋转风暴/超级单体潜势。

pipeline 产品层对每一类风险单独生成格点和风险区对象：

1. 每个因子先归一化为 0-1 分值，再乘以 `weights` 得到贡献场。
2. 综合评分达到 `score_threshold` 的连通区输出为潜势对象。
3. 对象内若有格点达到 `high_score_threshold`，标记为 `risk_level=high`，并记录 `core_point_count`。
4. 若只达到中等阈值，标记为 `risk_level=moderate` 和 `zone=outer`。
5. 对每个对象统计平均贡献最高的前三个因子，写入 `dominant_factors` 和 evidence。
6. 对风险区关联空间重叠或邻近的天气系统，写入 `supporting_systems`。
7. 对象按最大评分、平均评分和面积排序，只保留 `max_objects` 个主要风险区。

风险区关联优先考虑低空急流、水汽输送、水汽辐合、低层辐合、高空辐散、
锋面候选、槽线候选等业务相关系统。关联结果包含 `relation`、距离、
相关性评分和一句诊断理由，用于解释“潜势区为什么成立”。

诊断结论生成器会进一步把主导物理量和关联天气系统组织成值班口径：

- `headline`：一句话给出潜势等级和综合评分。
- `reasoning`：列出主导证据、关联天气系统、缺测提醒等解释。
- `action_hint`：给出实况订正或重点监测提示。

NAFP 诊断接口输出 `diagnosis_conclusions`，pipeline 生成的
`analysis.json` 输出 `conclusions`。

默认产品层阈值：

- `persistent_heavy_rain_risk.score_threshold`：持续性强降水中等风险阈值，默认 0.60。
- `persistent_heavy_rain_risk.high_score_threshold`：持续性强降水高风险核心阈值，默认 0.75。
- `persistent_heavy_rain_risk.max_objects`：最大输出持续性强降水风险区数量，默认 8。
- `short_duration_heavy_rain_risk.score_threshold`：短时强降水中等风险阈值，默认 0.60。
- `short_duration_heavy_rain_risk.high_score_threshold`：短时强降水高风险核心阈值，默认 0.75。
- `short_duration_heavy_rain_risk.max_objects`：最大输出短时强降水风险区数量，默认 8。
- `thunderstorm_gale_risk.score_threshold`：雷暴大风/下击暴流中等风险阈值，默认 0.58。
- `thunderstorm_gale_risk.high_score_threshold`：雷暴大风/下击暴流高风险核心阈值，默认 0.72。
- `thunderstorm_gale_risk.max_objects`：最大输出雷暴大风/下击暴流风险区数量，默认 8。
- `hail_risk.score_threshold`：冰雹中等风险阈值，默认 0.58。
- `hail_risk.high_score_threshold`：冰雹高风险核心阈值，默认 0.72。
- `hail_risk.max_objects`：最大输出冰雹风险区数量，默认 8。
- `rotating_storm_risk.score_threshold`：旋转风暴/超级单体中等风险阈值，默认 0.55。
- `rotating_storm_risk.high_score_threshold`：旋转风暴/超级单体高风险核心阈值，默认 0.70。
- `rotating_storm_risk.max_objects`：最大输出旋转风暴/超级单体风险区数量，默认 8。
- `severe_convection_composite_risk.score_threshold`：强对流综合中等风险阈值，默认 0.60。
- `severe_convection_composite_risk.high_score_threshold`：强对流综合高风险核心阈值，默认 0.72。
- `severe_convection_composite_risk.max_objects`：最大输出强对流综合风险区数量，默认 8。

动力抬升潜势综合：

- 700hPa 上升运动
- 500hPa 相对涡度
- 850hPa 低层辐合
- 200/300hPa 高空辐散
- 300hPa PV 平流

雨雪相态初判综合：

- 2m 气温
- 925hPa 温度
- 850hPa 温度
- 湿球 0℃ 层高度

当前相态输出为 `rain`、`mixed`、`snow`、`freezing_rain` 或 `unknown` 的初判。若缺少完整探空或模式廓线，只能作为格点资料相态提示，不能替代业务订正。

所有权重和阈值以后台默认阈值矩阵为准，可通过
`GET /api/v1/admin/algorithms/threshold-matrix` 查看和保存。后台同时提供
`GET /api/v1/admin/algorithms/rule-explanations`，用于管理页展示诊断依据、
输入场、算法步骤、阈值条目和证据输出契约。

---

## 2026-06-24 业务化优化补充

本轮对天气系统算法和风险判别做了 6 项优化，详见 `docs/optimization_20260624.md`：

1. EC/ECMWF `tp` 累计降水自动转时段量，风险输入增加 `precip_1h/3h/6h/24h`。
2. 强对流风险输出关键因子完整度、缺失因子和评分上限约束。
3. 低层辐合/高空辐散同时使用分位阈值和绝对散度阈值，并增加强度过滤。
4. 水汽输送带、低空急流在有风场时使用流线追踪轴线。
5. 高低压中心使用 km 级物理距离和闭合面积过滤，兼容不同分辨率。
6. 锋面候选默认从面对象抽取为 LineString 轴线，面对象仅作为 debug 输出。
