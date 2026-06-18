from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict

import numpy as np


def _count(features, ftype):
    return sum(1 for f in features if f.get("properties", {}).get("feature_type") == ftype)


def _top(features, ftype):
    selected = [f for f in features if f.get("properties", {}).get("feature_type") == ftype]
    if not selected:
        return None
    return max(selected, key=lambda f: f.get("properties", {}).get("confidence", 0))


def _diag_stats(diag_ds) -> Dict[str, Any]:
    stats = {}
    for name in diag_ds.data_vars:
        arr = diag_ds[name].values
        if np.isfinite(arr).any():
            stats[name] = {
                "min": float(np.nanmin(arr)),
                "max": float(np.nanmax(arr)),
                "mean": float(np.nanmean(arr)),
                "unit": diag_ds[name].attrs.get("units", ""),
            }
    return stats


def generate_situation_report(features_geojson: Dict[str, Any], diag_ds, *, forecast_hour: int) -> Dict[str, Any]:
    features = features_geojson.get("features", [])
    counts = Counter(f.get("properties", {}).get("feature_type", "unknown") for f in features)
    stats = _diag_stats(diag_ds)

    paragraphs = []
    paragraphs.append(f"当前为预报时效 +{forecast_hour}h 的自动天气形势诊断结果。")

    # Large-scale pattern.
    has_trough = counts.get("trough", 0) > 0
    has_ridge = counts.get("ridge", 0) > 0
    has_subtropical_high = counts.get("subtropical_high", 0) > 0
    if has_trough or has_ridge or has_subtropical_high:
        parts = []
        if has_trough:
            parts.append(f"识别到 {counts['trough']} 条 500hPa 槽线候选")
        if has_ridge:
            parts.append(f"识别到 {counts['ridge']} 条 500hPa 脊线候选")
        if has_subtropical_high:
            parts.append("存在 500hPa 副热带高压 5880gpm 区域")
        paragraphs.append("大尺度环流方面，" + "，".join(parts) + "。槽线和副高边缘附近可重点关注天气发展条件。")
    else:
        paragraphs.append("大尺度环流方面，当前未识别出明显槽脊或副高 5880gpm 区域，需结合实际等高线进一步判断。")

    # Pressure systems.
    highs = counts.get("high", 0)
    lows = counts.get("low", 0)
    if highs or lows:
        paragraphs.append(f"地面气压场方面，自动识别到高压中心 {highs} 个、低压中心 {lows} 个。低压附近若配合低层辐合和水汽条件，较有利于云雨发展。")

    # Dynamics and moisture.
    dyn = []
    if counts.get("low_level_convergence", 0):
        dyn.append(f"低层辐合区 {counts['low_level_convergence']} 个")
    if counts.get("upper_divergence", 0):
        dyn.append(f"高空辐散区 {counts['upper_divergence']} 个")
    if dyn:
        paragraphs.append("动力条件方面，识别到" + "、".join(dyn) + "。若低层辐合与高空辐散叠加，有利于上升运动增强。")

    if counts.get("low_level_jet", 0) or counts.get("moisture_transport", 0):
        paragraphs.append(f"低层水汽输送方面，识别到低空急流候选 {counts.get('low_level_jet', 0)} 条、水汽输送带候选 {counts.get('moisture_transport', 0)} 条。低空急流出口区和水汽辐合区是强降水潜势的重点关注区域。")

    # Risk.
    if counts.get("heavy_rain_risk", 0):
        paragraphs.append(f"强降水潜势方面，综合水汽输送、水汽辐合、低层辐合、上升运动和热力条件，识别到强降水潜势区 {counts['heavy_rain_risk']} 个。")
    if counts.get("convection_risk", 0):
        paragraphs.append(f"强对流潜势方面，综合 CAPE/CIN、风切变、低层水汽和触发条件，识别到强对流潜势区 {counts['convection_risk']} 个。")
    if not counts.get("heavy_rain_risk", 0) and not counts.get("convection_risk", 0):
        paragraphs.append("风险综合方面，当前自动评分未识别出明显强降水或强对流高潜势区，但仍需结合最新雷达、卫星和自动站实况订正。")

    # Important maxima.
    if "heavy_rain_score" in stats:
        paragraphs.append(f"强降水评分最大值约 {stats['heavy_rain_score']['max']:.2f}；该值为 0–1 归一化评分，只表示潜势强弱，不等同于实况雨量。")
    if "convection_score" in stats:
        paragraphs.append(f"强对流评分最大值约 {stats['convection_score']['max']:.2f}；需结合触发机制和实况回波判断是否真正发生。")

    summary = "".join(paragraphs[:3])
    return {
        "forecast_hour": forecast_hour,
        "summary": summary,
        "detail": "\n".join(paragraphs),
        "feature_counts": dict(counts),
        "diagnostic_stats": stats,
        "disclaimer": "自动诊断为规则算法结果，锋面、槽脊等为候选识别，应结合预报员经验和实况资料订正。",
    }
