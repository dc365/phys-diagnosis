# 天气系统图层精简建议

为了避免 MapLibre 主图层过载，天气系统建议按三层输出：

## 主天气系统

默认展示，数量受 `PRIMARY_SYSTEM_LIMITS` 控制：

- `subtropical_high`：500hPa 副高 588 区；
- `trough` / `ridge`：500hPa 槽脊线；
- `shear_line` / `front_with_shear`：850/700/500hPa 切变线；
- `front_candidate`：锋面候选及冷锋/暖锋/静止锋细分；
- `cold_vortex` / `mid_level_vortex`：500/700/850hPa 冷涡或低涡；
- `low_level_jet`：低空急流轴；
- `moisture_transport`：水汽输送带。

## 支撑诊断层

默认折叠，需要时打开：

- `low_level_convergence` / `low_level_convergence_axis`；
- `upper_divergence` / `upper_divergence_axis`；
- `upper_jet` / `upper_jet_exit_region`；
- `pv_anomaly`；
- `surface_front_candidate` / `dryline_candidate`；
- `moisture_convergence`。

## 风险层

作为下游产品，不建议和主天气系统同时全部默认打开：

- 持续性强降水；
- 短时强降水；
- 雷暴大风；
- 冰雹；
- 旋转风暴/超级单体；
- 强对流综合风险。

## Debug 层

仅用于算法调试：

- mask；
- bbox；
- source_area；
- score_grid；
- threshold contour。

## 接口字段建议

每个天气系统建议包含：

```json
{
  "feature_type": "shear_line",
  "geometry_role": "axis",
  "primary": true,
  "supporting_role": "trigger",
  "confidence": 0.72,
  "salience_score": 0.81,
  "evidence": []
}
```

其中 `supporting_role` 可取：

- `synoptic_control`：副高、槽脊、低涡；
- `trigger`：锋面、切变线、辐合轴；
- `moisture_supply`：低空急流、水汽输送带；
- `upper_support`：高空急流、PV 异常、高空辐散；
- `risk_output`：各类风险区。
