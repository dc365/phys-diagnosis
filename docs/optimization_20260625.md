# 2026-06-25 优化说明：副高边界平滑与天气系统算法文档

## 变更目标

本次针对 MapLibre 中副高 588 区边界呈格点台阶状、折线感明显的问题进行优化，同时补齐 docs 中各类天气系统的业务定义和算法说明。

## 代码变更

### 1. 副高 588 区边界平滑

新增通用工具：

- `weather_diag.diagnostics.grid.geometry_bounds`
- `weather_diag.diagnostics.grid.smooth_polygon_geometry`

`smooth_polygon_geometry` 会将 lon/lat Polygon 转换到局地公里坐标，对格点 mask union 生成的台阶边界做保守圆角化和平滑简化，再转换回 lon/lat GeoJSON。该方法只改变展示几何，不改变 mask 连通区统计。

涉及文件：

- `weather_diag/diagnostics/grid.py`
- `weather_diag/features/subtropical_high.py`
- `weather_diag/diagnosis/nafp_situation.py`
- `configs/thresholds.yaml`

新增配置：

```yaml
subtropical_high:
  smooth_boundary: true
  boundary_smooth_km: 90
  boundary_simplify_km: 30
```

### 2. NAFP 综合形势副高输出同步平滑

`diagnose_nafp_situation` 中 `subtropical_high` 的 `geometry` 也启用同样的平滑逻辑。输出中增加：

- `boundary_smoothed`
- `boundary_smooth_km`
- `boundary_simplify_km`
- `geometry.source_bbox`

其中 `source_bbox` 仅用于调试，不建议前端作为面渲染。

### 3. 文档补充

新增：

- `docs/weather_systems.md`

更新：

- `docs/algorithms.md`
- `docs/optimization_20260624.md`

`docs/weather_systems.md` 逐类说明了高低压、副高、槽脊、低压辐合、高压辐散、低层辐合、高空辐散、水汽辐合、低空急流、水汽输送带、锋面候选和风险区的定义、输入要素、算法步骤和输出几何。

## 前端注意事项

- 副高仍是 Polygon / MultiPolygon 图层。
- 只使用接口返回的 `geometry.coordinates` 绘制面。
- 不要根据 `bbox` 或 `source_bbox` 生成展示面。
- 副高属性中 `boundary_smoothed=true` 表示已经做过展示边界平滑。

## 验证

已执行：

```bash
find backend weather_diag scripts docs -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 python -m py_compile

pytest -q \
  tests/test_subtropical_high_features.py \
  tests/test_front_features.py \
  tests/test_transport_features.py \
  tests/test_convergence_features.py \
  tests/test_pressure_features.py \
  tests/test_risk_features.py
```

结果：

```text
20 passed
```

`tests/test_nafp_situation.py` 依赖本地 NAFP 样例数据目录 `data/NAFP/NAFP_ECTHIN_NC/.../26061720.024`，当前 zip 中未包含完整样例数据，因此未作为本次通过依据。
