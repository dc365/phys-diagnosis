# 站点实况探空多层要素、天气系统与风险诊断

本次在探空站预处理基础上，把实况探空从“500hPa 单层天气图”扩展为类似数值预报诊断的多层物理量、天气系统和风险产品。

## 多层客观分析要素

在清洗后的探空 CSV 上，对以下标准层做 Barnes 客观分析：

```text
850 / 700 / 500 / 300 / 200 hPa
```

每层尽量输出：

- 温度 `t{level}`；
- 露点 `td{level}`；
- 相对湿度 `rh{level}`；
- 比湿 `q{level}`；
- u/v 风分量；
- 风速 `wind{level}_speed`；
- 散度 `div{level}`；
- 相对涡度 `vort{level}`；
- 水汽通量 `moisture_flux{level}`，主要用于 850hPa。

额外派生：

- `lapse_rate_700_500`：700–500hPa 温度递减率；
- `shear_850_500`：850–500hPa 垂直风切变。

这些字段会进入 `/api/v1/sounding/situation` 的 `analysis_fields`，并可通过 `/api/v1/sounding/layers/{layer_id}` 输出格点和等值线。

## 新增探空天气系统

基于多层客观分析场，新增类似数值预报诊断的天气系统：

- `low_level_jet`：850hPa 低空急流；
- `moisture_transport`：850hPa 水汽输送带；
- `low_level_convergence`：850hPa 低层辐合区；
- `upper_divergence`：200/300hPa 高空辐散区；
- `upper_jet`：200/300hPa 高空急流；
- `cold_vortex` / `mid_level_vortex`：500hPa 冷涡或低涡候选；
- `front_candidate`：850hPa 锋面候选。

原有 500hPa H/L/W/C、槽线、脊线、500hPa 切变线继续保留。

## 新增探空风险网格

新增基于探空客观场的风险评分网格：

```text
risk_persistent_heavy_rain_score
risk_short_duration_heavy_rain_score
risk_thunderstorm_gale_score
risk_hail_score
risk_rotating_storm_score
risk_severe_convection_composite_score
```

风险评分是“环境潜势”而不是预警结论。它不使用模式降水，因此强降水相关风险需要结合数值预报、雷达和实况订正。

## 阈值矩阵统一

探空天气系统算法直接调用 `load_thresholds()`，和数值预报天气系统共用同一套阈值配置。探空风险网格也读取 `risk_scoring.common` 中的 CAPE、PW、q850、RH、深层风切变、递减率、T500 等阈值，不再单独建立探空专用阈值矩阵。

## 站点风险增强

站点风险在原 CAPE/PW/CIN/LCL 基础上增加了：

- 持续性强降水；
- 雷暴大风；
- 冰雹。

由于站点单廓线缺少完整触发系统、SRH、实况雨强等关键因子，评分默认做上限封顶，并输出 `missing_critical_factors`。

## 新增 API

```text
GET /api/v1/sounding/layers
GET /api/v1/sounding/layers/{layer_id}/metadata
GET /api/v1/sounding/layers/{layer_id}/grid
GET /api/v1/sounding/layers/{layer_id}/contours
```

`/layers` 会返回当前探空时次可用的所有图层，包括多层物理量、派生量和风险评分。

## Map 动态图层接入

地图页 `/map` 会在 `map.js` 之后加载 `frontend/sounding-map-extension.js`。切换到“实况”后，前端会请求：

```text
/api/v1/sounding/layers?csv_path=...
```

前端现在只把这个接口真实返回的图层放入右侧要素面板；如果当前探空时次没有某层或某派生量，就不会再显示空图层。切回数值预报时，会恢复数值预报图层目录。

实况天气系统复选框也会隐藏不适用于探空的系统，只保留当前探空诊断能返回的高低中心、槽脊、切变线、低空急流、水汽输送、低层辐合、高空辐散、高空急流、冷涡、锋面候选和风险点。

## 注意事项

- 探空站空间密度有限，低层辐合、涡度、散度等导数字段只适合作为环境诊断参考；
- 850hPa 水汽通量由比湿和风速估算，单位为 `g/kg*m/s`，与数值预报积分水汽通量不同；
- 风险网格不等价于模式风险，需要与数值预报、雷达和实况降水结合使用。