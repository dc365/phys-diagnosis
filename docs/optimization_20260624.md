# 2026-06-24 天气系统算法与风险判别优化说明

本次优化聚焦前一轮审查提出的 6 个优先问题，目标是在不推翻现有项目结构的前提下，提高 EC/NAFP NetCDF 数据接入后的业务稳定性、GIS 出图一致性和风险判别可信度。

## 1. EC 降水累计量与时段量处理

`weather_diag/diagnosis/nafp_layers.py` 增加了降水标准化逻辑：

- `tp / total_precipitation / precip` 等累计型字段优先使用 `当前时效 - 前一时效` 转换为时段降水。
- `rain3 / rain6 / rain24 / rainmax3` 等原生时段产品直接使用当前文件，不再误做相邻时效差分。
- 支持单位自动转换：`m` 转 `mm`，`kg m-2` 作为 mm 等效量处理。
- 风险输入同时补充 `precip_3h / precip_6h / precip_24h`，其中 `precipitation` 默认指向 6h 时段降水。

这样可以避免把 EC 后期累计降水直接当成当前时段降水，导致强降水风险随预报时效虚高。

## 2. 强对流风险关键因子完整度与评分封顶

`weather_diag/features/risk_scoring.py` 与风险输出链路增加了质量元数据：

- `input_completeness`
- `missing_critical_factors`
- `available_critical_factors`
- `score_cap_value`
- `score_cap_applied`

对冰雹、雷暴大风、旋转风暴/超级单体、短时强降水、持续性强降水等风险，若 CAPE、垂直风切变、SRH、DCAPE、冻结层、LCL、降水等关键因子缺失，会在格点层面降低置信度，并对风险分数进行上限约束。

相关质量信息已传递到：

- `weather_diag/features/risk.py`
- `weather_diag/pipeline.py`
- `weather_diag/diagnosis/nafp_situation.py`
- `weather_diag/diagnosis/area_risk.py`
- `weather_diag/diagnosis/nafp_features.py`

前端或报告可以直接展示“缺少哪些关键因子”和“是否触发评分封顶”。

## 3. 低层辐合与高空辐散弱场误报控制

`weather_diag/features/convergence.py` 增强为“绝对阈值 + 分位阈值 + 形态学 + 面积/强度过滤”：

- 低层辐合必须满足负散度绝对阈值，例如 `<= -1e-5 s^-1`。
- 高空辐散必须满足正散度绝对阈值，例如 `>= 1e-5 s^-1`。
- 同时保留区域分位阈值，避免季节/区域差异过大。
- 增加 `morphology_opening_grid / morphology_closing_grid`，抑制孤立噪声并修补小断裂。
- 增加 `min_area_km2`、`min_mean_strength`、`min_max_strength` 等过滤条件。

NAFP 综合形势中的低层辐合/高空辐散也同步采用了该思想，并在系统对象中输出 `threshold_value`、`percentile_threshold`、`absolute_threshold`、`area_km2`、`mean_strength`、`max_strength`。

## 4. 水汽输送带与低空急流改为沿风场追踪轴线

`weather_diag/features/transport_objects.py` 新增流线式轴线追踪：

- 从高值连通区内的最大值格点出发。
- 沿 `u/v` 风向双向追踪。
- 追踪过程中约束必须留在候选 mask 内。
- 若流线追踪失败，则回退到原 PCA 几何主轴。

`moisture_transport.py` 和 `low_level_jet.py` 现在会输出：

- `axis_method`: `streamline_axis` 或 `pca_component_axis`
- `axis_length_km`

NAFP 综合形势也会保留 `axis_method`、`axis_length_km` 和来源区域面积。

## 5. 高低压中心改用物理距离和物理面积阈值

`weather_diag/features/pressure.py` 支持：

- `min_distance_km`
- `edge_margin_km`
- `min_closed_area_km2`

原来的 `min_distance_grid / edge_margin_grid` 仍保留为兼容回退。算法会根据经纬度分辨率换算为网格窗口，避免 0.25°、0.5°、1° 数据下阈值含义不一致。

输出中新增：

- `closed_area_km2`
- `min_distance_grid_used`
- `edge_margin_grid_used`

NAFP 综合形势中的海平面高低压中心也会保留闭合等压线面积证据。

## 6. 锋面候选由面进一步抽取为线

`weather_diag/features/front.py` 支持锋面候选轴线输出：

- 默认 `front_candidate.output_geometry: axis`。
- 业务图层输出 `LineString`。
- 调试时可改为 `area` 输出候选锋区面。

NAFP 综合形势中的 `front_candidate` 也改为线对象：

```json
{
  "geometry": {
    "type": "line",
    "coordinates": [[lon, lat], ...]
  }
}
```

同时保留 `source_area_bbox` 和 `source_area_point_count` 用于调试和解释。

## 验证情况

已执行：

```bash
find backend weather_diag scripts docs -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 python -m py_compile
pytest -q tests/test_transport_features.py tests/test_convergence_features.py tests/test_pressure_features.py tests/test_risk_features.py tests/test_front_features.py
```

结果：

```text
19 passed
```

另做了合成场 smoke test，覆盖锋面轴线、辐合/辐散、高低压中心和风险质量元数据。

## 后续建议

本次是工程可运行级优化，阈值仍需用历史个例校准。建议后续建立 20–50 个典型天气过程样本，对槽线、锋面、高低压、辐合辐散、降水/强对流风险分别做人工标注校验，形成可持续调参基准。

## 2026-06-25 补充：副高边界平滑与天气系统说明文档

- 副高 588 区原始 Polygon 来自格点 mask union，边界会沿格点呈台阶状。现在默认启用 `subtropical_high.smooth_boundary=true`，通过局地公里坐标中的 buffer 圆角化与拓扑保持简化，使 MapLibre 展示轮廓更接近业务天气图中的平滑 5880gpm 包络线。
- 平滑只作用于展示 geometry，不改变 `area_grid_points`、`mean_height`、`ridge_point`、`north_boundary_lat` 等诊断指标。
- 新增 `docs/weather_systems.md`，系统说明高低压、副高、槽脊、辐合辐散、低空急流、水汽输送、锋面候选和风险区的业务定义、输入要素、算法步骤与输出几何。
