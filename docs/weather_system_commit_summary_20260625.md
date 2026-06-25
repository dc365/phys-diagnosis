# 2026-06-25 天气系统算法提交摘要

本次提交覆盖以下文件：

## 新增算法

- `weather_diag/features/shear_line.py`：850/700/500hPa 切变线与锋区切变线识别。
- `weather_diag/features/vortex.py`：低涡、冷涡候选识别。
- `weather_diag/features/upper_jet.py`：高空急流轴与急流出口辐散区。
- `weather_diag/features/pv_anomaly.py`：高空 PV 异常和干侵入支撑诊断。
- `weather_diag/features/surface_boundary.py`：地面锋区、露点锋和干线候选。

## 优化算法

- `weather_diag/features/subtropical_high.py`：副高 588 / 5880 / ECMWF geopotential 自动单位判别。
- `weather_diag/features/transport_objects.py`：低空急流和水汽输送带排序从长度优先改为强度、长度封顶和风向一致性综合排序。
- `weather_diag/features/low_level_jet.py`：透传新的输送轴排序和流线追踪参数。
- `weather_diag/features/moisture_transport.py`：透传新的输送轴排序和流线追踪参数。
- `weather_diag/features/convergence.py`：新增低层辐合轴和高空辐散轴 LineString 输出函数。

## 配置与测试

- `configs/thresholds.yaml`：新增切变线、低涡/冷涡、高空急流和锋面分类参数。
- `configs/weather_system_experimental.yaml`：新增 PV 异常和地面边界实验参数。
- `tests/test_shear_line_features.py`：新增切变线测试。
- `tests/test_weather_system_optimization.py`：新增副高单位、冷涡和高空急流测试。

## 文档

- `docs/weather_system_optimization_20260625.md`
- `docs/weather_system_layering.md`
- `docs/nafp_integration_todo.md`

## 接入状态

新增 feature 算法已提交到仓库；`nafp_situation.py` 主综合形势接口仍建议按 `docs/nafp_integration_todo.md` 分批接入，避免一次性改动过大导致接口输出和前端图层同时震荡。
