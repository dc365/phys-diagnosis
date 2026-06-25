# 锋面候选与冷/暖/静止锋细分算法

## 1. “锋面候选”指什么

项目中的 `front_candidate` 不是最终人工天气图意义上的锋面符号，而是客观算法从 EC/NAFP 格点场中识别出的“锋区候选轴线”。它表示：850hPa 附近存在明显水平温度梯度，并且至少得到一部分动力或水汽证据支持，例如锋生函数、风场形变、低层辐合、温度平流或相对湿度配合。

因此，`front_candidate` 的业务含义应理解为：

- 这里可能存在冷暖空气交汇带；
- 该区域有形成锋面或锋区天气的条件；
- 还需要通过风场法向分量、温度平流、低压中心位置、地面图和时序演变来进一步判定冷锋、暖锋、静止锋或锢囚锋。

第一版不建议直接把所有 `front_candidate` 都画成冷锋或暖锋，否则容易在弱梯度区、地形温度梯度区或模式噪声区产生误判。

## 2. 细分类型

当前优化版把锋面候选进一步细分为：

| 字段值 | 中文名 | 判据含义 |
|---|---|---|
| `cold_front` | 冷锋候选 | 低层风在温度梯度法向上主要由冷侧吹向暖侧，同时冷平流占优。 |
| `warm_front` | 暖锋候选 | 低层风在温度梯度法向上主要由暖侧吹向冷侧，同时暖平流占优。 |
| `stationary_front` | 静止锋候选 | 温度梯度明显，但锋面法向风较弱或冷暖侧推进均不占优。 |
| `mixed_front` | 混合锋面候选 | 同一连通锋区内冷锋、暖锋或静止锋信号混合，暂不强制分类。 |
| `front_candidate` | 未分类锋面候选 | 缺少 850hPa 风场或证据不足，只保留候选属性。 |

暂不自动输出 `occluded_front`。锢囚锋需要低压中心、冷暖锋闭合结构、低层温度脊/湿舌包卷和时间演变共同判断，单时次 850hPa 温度梯度不够稳定。

## 3. 关键物理量

### 3.1 温度梯度

```text
∇T = (∂T/∂x, ∂T/∂y)
|∇T| = sqrt((∂T/∂x)^2 + (∂T/∂y)^2)
```

`∇T` 指向暖空气一侧，所以它也定义了锋面法向方向：从冷侧指向暖侧。

### 3.2 法向风分量

```text
n = ∇T / |∇T|
Vn = V850 · n
```

解释：

- `Vn > 0`：风从冷侧指向暖侧，倾向冷锋推进；
- `Vn < 0`：风从暖侧指向冷侧，倾向暖锋推进或暖空气爬升；
- `|Vn|` 很小：锋面趋于准静止。

### 3.3 温度平流

```text
temperature_advection = - V850 · ∇T
```

解释：

- 正值：暖平流，支持暖锋候选；
- 负值：冷平流，支持冷锋候选。

如果 EC 产品里有 `ttadv/850`，算法优先使用产品温度平流；否则用 `uv850` 和 `tt850` 计算。

## 4. 识别流程

1. 读取 `tt850`，计算水平温度梯度。
2. 如果有 `uv850`，计算锋生函数、风场形变、锋面法向风和温度平流。
3. 如果有 `div850`，把负散度作为低层辐合支撑。
4. 如果有 `ttadv850`，把平流绝对值作为锋区强度支撑，并保留符号用于分类。
5. 如果有 `rh850`，作为锋区水汽配合弱支撑。
6. 综合评分筛选锋区 mask：温度梯度和综合评分必须同时超过阈值；有风场时还需至少满足一个动力支撑项。
7. 从 mask 中提取连通区，并转成 LineString 轴线。
8. 对每条轴线对应的源连通区统计 `Vn` 和温度平流符号，判定冷锋、暖锋、静止锋或混合锋。

## 5. 输出字段

`detect_front_candidates(...)` 输出的 LineString properties 增加：

```json
{
  "front_type": "cold_front",
  "front_type_label": "冷锋候选",
  "front_motion": "cold_air_advancing",
  "front_motion_label": "冷空气向暖侧推进",
  "front_type_confidence": 0.86,
  "cross_front_wind_mean_ms": 4.2,
  "cross_front_wind_abs_mean_ms": 4.5,
  "cold_front_ratio": 0.82,
  "warm_front_ratio": 0.04,
  "stationary_front_ratio": 0.12,
  "temperature_advection_mean": -0.00008,
  "temperature_advection_source": "computed_from_uv850_t850",
  "classification_reason": "850hPa 风在温度梯度法向上主要由冷侧指向暖侧，并伴随冷平流或冷侧推进信号。"
}
```

## 6. 推荐配置

```yaml
front_candidate:
  level_hpa: 850
  temp_gradient_percentile: 80
  score_percentile: 82
  dynamic_support_percentile: 70
  min_support_components: 1
  min_area_grid_points: 10
  max_objects: 12
  output_geometry: axis
  cross_front_wind_min_ms: 1.0
  stationary_cross_front_max_ms: 0.8
  front_type_consistency_min: 0.55
  front_type_mixed_gap: 0.15
```

## 7. 业务注意事项

冷锋、暖锋的自动分类是“候选分类”，不是最终人工天气图结论。更稳的业务版本应继续叠加：

- 地面或海平面低压中心位置；
- 地面风切变和露点梯度；
- 925/850hPa 温度和湿度梯度一致性；
- 前后两个时效的锋面位移；
- 雷达、降水和实况温度露点订正。
