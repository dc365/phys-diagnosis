# 新天气系统算法治理接入说明

本次把新增天气系统参数接入统一的算法治理与阈值矩阵接口。管理页面继续使用原有接口：

```text
GET /api/v1/admin/algorithms/catalog
GET /api/v1/admin/algorithms/threshold-matrix
GET /api/v1/admin/algorithms/rule-explanations
PUT /api/v1/admin/algorithms/threshold-matrix
```

## 已纳入治理的算法

- 850/700/500hPa 切变线与锋区切变线
- 500/700/850hPa 低涡和冷涡
- 200/300hPa 高空急流与急流出口区
- 300hPa PV 异常与干侵入
- 地面锋区、露点锋和干线候选

低层辐合轴和高空辐散轴复用原低层辐合、高空辐散阈值，因此不重复建立一套参数。

## 实现结构

### weather_diag/diagnosis/weather_system_governance.py

提供：

- 新天气系统目录项；
- 默认阈值条目；
- 阈值范围与整数/布尔参数校验；
- 规则说明；
- 阈值矩阵合并；
- 管理页面参数到 `thresholds` 配置的运行时映射。

扩展参数保存在：

```text
data/admin/weather_system_threshold_matrix.json
```

对外仍合并成一个 `nafp-default` 阈值矩阵，不增加新的管理入口。

### backend/app/services/algorithm_rules.py

管理接口返回时，把基础矩阵和新增天气系统参数合并；保存时自动拆分基础参数和扩展参数，并校验未知条目。

保存成功后会清空 NAFP situation 缓存，确保下一次诊断立即使用新参数，而不是继续返回旧缓存结果。

### weather_diag/config.py

`load_thresholds()` 先读取 `configs/thresholds.yaml`，再叠加管理页面保存的新天气系统参数。因此以下算法会直接使用页面调整后的值：

- `detect_shear_lines`
- `detect_cold_vortex`
- `detect_upper_jet`
- `detect_jet_exit_regions`
- `detect_pv_anomaly`
- `detect_surface_boundaries`

## 小量级物理量的页面表示

相对涡度和散度常为 `10^-5 s^-1` 量级。为避免管理页面的小数输入和四位显示把 `0.00001` 显示为零，矩阵中使用缩放单位：

```text
1.0 代表 1.0 × 10^-5 s^-1
0.4 代表 0.4 × 10^-5 s^-1
```

运行时映射会自动乘以 `1e-5`。

## 校验规则

- 百分位参数限制在 0–100；
- 占比和方向一致性限制在 0–1；
- 开关参数只允许 0 或 1；
- 格点数和对象数必须为整数；
- 涡度、散度、长度、面积等参数不能小于业务允许下限；
- 未知 `entry_id` 会返回 40005。

## 测试

新增：

```text
tests/test_weather_system_governance.py
```

覆盖目录、阈值矩阵、规则说明、保存后运行时参数生效、`10^-5/s` 缩放转换，以及整数参数非法值拒绝。
