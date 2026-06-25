# 天气系统算法优化提交说明

本次提交围绕天气系统算法做了增补和精简，重点从“候选面”转向“可解释的主系统对象”。

## 已完成

1. 副高算法
   - 500hPa 副高 588 区支持 588 dagpm、5880 gpm 和 ECMWF geopotential 自动识别。
   - 新增 `height_unit`、`threshold_source`、`contour_value`、`area_km2`。

2. 锋面算法
   - 已支持冷锋、暖锋、静止锋、混合锋面候选。
   - 分类依据为锋面法向风和温度平流。

3. 切变线算法
   - 新增 `weather_diag/features/shear_line.py`。
   - 可识别 850/700/500hPa 风场切变线。
   - 温度梯度强时标记为 `front_with_shear`，避免和普通锋面割裂。

4. 低涡 / 冷涡算法
   - 新增 `weather_diag/features/vortex.py`。
   - 支持高度场闭合低值、正涡度、冷心结构共同识别。

5. 高空急流和出口区
   - 新增 `weather_diag/features/upper_jet.py`。
   - 支持高空急流轴和急流出口辐散区候选。

6. PV 异常 / 干侵入
   - 新增 `weather_diag/features/pv_anomaly.py`。
   - 作为强对流、冰雹、雷暴大风和斜压系统发展的支撑诊断。

7. 地面边界候选
   - 新增 `weather_diag/features/surface_boundary.py`。
   - 支持地面锋区、露点锋、干线候选。

8. 辐合 / 辐散轴线
   - `convergence.py` 保留原 Polygon 面对象。
   - 新增低层辐合轴和高空辐散轴 LineString 输出函数。

9. 低空急流 / 水汽输送带排序
   - 改为强度、长度封顶和风向一致性综合排序。
   - 流线追踪增加转角限制和小缺口容忍。

## 新增测试

- `tests/test_shear_line_features.py`
- `tests/test_weather_system_optimization.py`

## 配置文件

- `configs/thresholds.yaml` 已加入切变线、低涡/冷涡、高空急流、锋面分类参数。
- `configs/weather_system_experimental.yaml` 包含 PV 异常和地面边界等实验参数。

## 后续仍建议继续做

1. 把新增 feature 算法接入 `weather_diag/diagnosis/nafp_situation.py` 的综合形势接口。
2. 在 MapLibre 前端按“主天气系统 / 支撑诊断 / 风险区 / Debug”分组展示。
3. 用 `test_datas/NAFP_ECTHIN_NC` 建人工标注验证集，校准阈值。
4. 将后台阈值矩阵同步增加切变线、低涡、高空急流、PV 异常和地面边界条目。
