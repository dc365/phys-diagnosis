# phys-diagnosis 项目检查与优化建议

本文件记录对当前工程的快速审查结论，重点关注天气系统识别算法、EC NetCDF 数据接入、GIS 输出和气象风险判别。

## 已直接修复

1. `weather_diag/diagnosis/nafp_situation.py`：槽线/脊线候选方法名已升级为 `nmc_style_*`，原置信度判断仍匹配旧的 `curvature_component_axis`，导致曲率支撑的轴线被低估。已改为按 method 字符串是否包含 `curvature` 判断。
2. `configs/thresholds.yaml`：补充 NMC-style 槽/脊轴线参数，增加天气尺度平滑半径、纬度范围、最短线长、弯曲度限制、输出点数等，避免候选区小碎线和格点噪声。
3. `weather_diag/data/nafp.py`、`backend/app/services/data_sources.py`、`configs/data_sources.yaml`：移除本机硬编码 `/Users/dc/...` 数据根目录，默认使用项目内 `data/NAFP/NAFP_ECTHIN_NC`，生产环境可通过 `WEATHER_DIAG_NAFP_ROOT` 或 `NAFP_ROOT` 覆盖。
4. `docs/algorithms.md`：把槽/脊候选说明改为默认输出 LineString，候选区面应只作为 debug 图层。

## 仍建议继续优化

### 1. EC 降水量要区分累计量和时段量

EC 的 `tp` 在很多数据源中是累计降水量。当前风险评分直接把读取到的 precipitation 当作时段降水使用，容易导致 24/48/72 小时之后降水风险虚高。建议在标准化阶段增加：

- `precip_accumulation_type`: `cumulative` / `interval`；
- `precip_window_hours`: 1 / 3 / 6 / 24；
- 若为 cumulative，按相邻 forecast hour 差分得到时段降水。

### 2. 风险评分需要关键因子完整度和硬门槛

现有风险评分能在缺少 SRH、DCAPE、LI、冻结层高度、湿球零度层等因子时给出降级置信度，但某些灾害类型不应仅靠少数替代因子给高分。建议增加：

- `missing_critical_factors`；
- `input_completeness`；
- `score_cap_when_missing_critical`；
- 对冰雹、雷暴大风、超级单体/龙卷设置硬门槛或半硬门槛。

### 3. 辐合/辐散对象不能只用百分位

百分位阈值会在弱天气场中强行选出若干对象。建议同时使用绝对阈值：

- 低层辐合：`divergence <= -1e-5 s^-1` 且位于低百分位；
- 高空辐散：`divergence >= 1e-5 s^-1` 且位于高百分位；
- 面对象输出前做 morphology opening/closing，并过滤小面积和低强度对象。

### 4. 低空急流和水汽输送带轴线建议改为流线追踪

当前对象轴线更接近高值区的几何主轴。对于水汽输送带，业务上更希望轴线沿风/水汽通量方向延伸。建议后续把 PCA 轴线升级为 flux streamline tracing：从高通量种子点出发，沿 `q * wind` 或 moisture flux 矢量双向追踪。

### 5. 高低压中心建议统一物理距离参数

当前部分系统仍用 grid 数表示最小距离或面积。建议统一提供 `min_distance_km`、`min_area_km2`，运行时根据数据分辨率换算为格点，避免 0.25°、0.5°、1° 数据表现不一致。

### 6. 测试数据路径和测试策略

测试中 NAFP 数据依赖外部样例路径。建议：

- 使用环境变量注入真实数据根目录；
- 仓库内放 1-2 个脱敏、小范围、小尺寸 NetCDF fixture；
- 外部大数据测试标记为 integration test，不阻塞单元测试。

## 建议优先级

P0：修复数据根目录、槽线配置、LineString 输出、测试 fixture。

P1：修复 EC 累计降水差分，增加风险因子完整度和 score cap。

P2：辐合/辐散绝对阈值 + 面对象形态学过滤；水汽输送带/低空急流升级为流线追踪。

P3：建立人工标注样本，对槽线、高低压、辐合辐散、风险区进行 ETS/POD/FAR/CSI 和距离误差评估。
