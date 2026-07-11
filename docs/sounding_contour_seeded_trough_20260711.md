# 探空 500hPa 等高线种子槽线识别

## 目标

本次实现不引入 EC、CMA、GRAPES 等数值格点背景场。输入仍是探空站资料经过客观分析形成的 500hPa 位势高度网格；槽线识别只读取该高度网格，可选的 500hPa 正涡度只作为弱支持项。

切变线继续使用原有独立风场算法和 Map 界面的独立选项，不与高度槽线合并。

## 自动识别流程

```text
探空站资料
  -> 站点质控与 500hPa 垂直插值
  -> 纯站点 Barnes 客观分析 Z500 网格
  -> 4 dagpm 等高线族
  -> 搜索各条等高线向南凹陷的槽尖
  -> 相邻等高线槽尖自动聚类
  -> 多等高线共同支持的种子直接保留
  -> 单层极强种子使用 Otsu 类间方差自动阈值
  -> 从每个种子沿逐纬度高度低谷向南、向北追踪
  -> 独立生成轴线、样条平滑、去重与业务过滤
```

算法不再依赖固定的 `seed_percentile` 来确定高阈值种子。多条相邻等高线共同出现槽尖时，本身即构成高可信种子；只有缺少多层支持时，才使用数据驱动的 Otsu 阈值判断单层强种子。

## 东北多槽处理

每个等高线槽尖聚类分别追踪轴线。追踪过程受到以下约束：

- 种子所覆盖的经纬度走廊；
- 相邻纬度之间的最大经度跳变；
- 高度低谷深度和纬向二阶曲率；
- 轴线最小长度、纬向跨度和弯曲度；
- 轴线间平均距离去重。

因此，东北相邻的两个槽区不会先膨胀成一个大连通区，再由 PCA 拟合成一条斜线。

## 海南及华南低纬槽

低纬槽仍然必须由多条等高线的向南凹陷提供种子，然后沿高度低谷追踪。结果保持 `candidate_source=meridional_valley_track` 以兼容已有接口，同时新增：

- `method_detail=contour_seeded_valley_axis_v1`
- `seed_source=contour_tip_cluster`
- `seed_threshold_method=otsu_between_class_variance`
- `contour_support_count`
- `contour_levels_gpm`
- `seed_lon` / `seed_lat`

这些详细属性目前保留在直接槽线 GeoJSON 中；现有 sounding 系统包装仍兼容原来的 `method` 和 `candidate_source` 字段。

## 启用范围

`weather_diag.features` 在检测到 `trough_ridge.enable_meridional_valley_tracks=true` 时启用新算法。这是当前探空实况分析使用的配置。数值模式/NAFP 路径没有该开关，因此继续使用原有 `trough_ridge` 算法。

可以显式关闭：

```python
{
    "trough_ridge": {
        "enable_meridional_valley_tracks": True,
        "enable_contour_seeded_troughs": False,
    }
}
```

如果等高线提取异常或没有形成有效种子，运行时自动回退到原有槽线算法，避免业务图层为空。

## 测试

新增 `tests/test_contour_seeded_trough.py`，覆盖：

- 东北两个相邻槽区分别输出轴线；
- 无风场输入时仍可识别海南附近高度槽；
- 纯纬向高度场不产生伪槽线；
- 探空配置启用新算法，且输出不混入 `shear_line`。
