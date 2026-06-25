# NAFP 综合形势接口接入待办

本次已提交天气系统 feature 层算法和配置，但为了降低一次性改动风险，部分新增算法暂未全部接入 `weather_diag/diagnosis/nafp_situation.py` 的主返回列表。

建议下一步按以下顺序接入：

1. `shear_line_850`：优先接入，因为它能直接区分锋面和切变线。
2. `low_level_convergence_axis`：替代默认展示中的大面积低层辐合面。
3. `cold_vortex_500`：和槽线、冷涡强对流风险联动。
4. `upper_jet_200/300` 与 `upper_jet_exit_region`：作为强降水和强对流的高空动力支撑。
5. `pv_anomaly_300`：作为辅助支撑层，默认不主显。
6. `surface_front_candidate` / `dryline_candidate`：作为地面触发边界，默认不主显。

接入时建议同步更新：

- `PRIMARY_SYSTEM_LIMITS`
- `SYSTEM_DISPLAY_PRIORITY`
- `DYNAMIC_CONFIDENCE_SYSTEM_TYPES`
- 后台阈值矩阵 `algorithm_rules.py`
- 前端 MapLibre 图层分组和图例
