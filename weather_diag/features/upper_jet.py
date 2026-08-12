from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.features.transport_objects import ranked_transport_components
from weather_diag.io.geojson import line_feature, polygon_feature
from weather_diag.diagnostics.grid import mask_to_bbox_features


def _finite_percentile(values: np.ndarray, percentile: float, default: float = 0.0) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return default
    return float(np.nanpercentile(valid, percentile))


def _nan_smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    if sigma <= 0:
        return arr.copy()
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weight = finite.astype(float)
    smooth = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weight, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smooth, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def detect_upper_jet(
    u: np.ndarray,
    v: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    level: int = 200,
    divergence_field: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("upper_jet", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    speed = np.hypot(_nan_smooth(u, sigma), _nan_smooth(v, sigma))
    wind_min = float(cfg.get("wind_speed_min_ms", 30.0))
    p = float(cfg.get("wind_speed_percentile", 85.0))
    threshold = max(wind_min, _finite_percentile(speed, p, wind_min))
    mask = speed >= threshold
    min_pts = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 8))
    min_coherence = float(cfg.get("min_direction_coherence", 0.60))
    components = ranked_transport_components(
        mask,
        lat,
        lon,
        speed,
        min_points=min_pts,
        max_objects=max_objects,
        u=u,
        v=v,
        min_direction_coherence=min_coherence,
        length_cap_km=float(cfg.get("rank_length_cap_km", 2500.0)),
        mean_weight=0.35,
        max_weight=0.30,
        length_weight=0.20,
        coherence_weight=0.15,
    )
    features = []
    for component in components:
        item = component["item"]
        ys, xs = item["indices"]
        div_support = None
        if divergence_field is not None:
            div_values = np.asarray(divergence_field, dtype=float)[ys, xs]
            div_support = float(np.nanmean(div_values)) if div_values.size else None
        props = {
            "id": f"upper_jet_{level}_{component['rank']:03d}",
            "feature_type": "upper_jet",
            "title": f"{level}hPa 高空急流轴",
            "level": f"{level}hPa",
            "rank": component["rank"],
            "axis_length_km": round(component.get("axis_length_km", 0.0), 1),
            "axis_method": component.get("axis_method"),
            "rank_score": component.get("rank_score"),
            "point_count": component["point_count"],
            "max_wind_ms": round(component["max_value"], 2),
            "mean_wind_ms": round(component["mean_value"], 2),
            "wind_threshold_ms": round(threshold, 2),
            "mean_divergence_support": div_support,
            "direction_coherence": None if component["direction_coherence"] is None else round(component["direction_coherence"], 3),
            "confidence": round(min(0.9, 0.58 + (component["max_value"] - threshold) / max(threshold, 1.0) * 0.20), 2),
            "evidence": [
                f"{level}hPa 风速超过 {threshold:.1f} m/s 或区域高值分位",
                "高空强风带呈连续轴线结构",
                "可与高空辐散区叠加判断急流出口区抽吸作用" if divergence_field is not None else "未提供高空散度，暂不诊断急流出口区",
            ],
        }
        features.append(line_feature(component["line"]["coordinates"], props))
    return features


def detect_jet_exit_regions(
    upper_jet_features: list[dict],
    divergence_field: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    level: int = 200,
) -> list[dict]:
    cfg = thresholds.get("upper_jet", {})
    p = float(cfg.get("exit_divergence_percentile", 88.0))
    divergence_min = float(cfg.get("exit_divergence_min", 8.0e-6))
    min_pts = int(cfg.get("exit_min_area_grid_points", 8))
    max_objects = int(cfg.get("exit_max_objects", 6))
    div = np.asarray(divergence_field, dtype=float)
    threshold = max(divergence_min, _finite_percentile(div, p, divergence_min))
    mask = div >= threshold
    items = mask_to_bbox_features(mask, lat, lon, min_points=min_pts)
    ranked = []
    for item in items:
        ys, xs = item["indices"]
        ranked.append({"item": item, "mean_div": float(np.nanmean(div[ys, xs])), "max_div": float(np.nanmax(div[ys, xs]))})
    ranked.sort(key=lambda item: (item["max_div"], item["mean_div"], item["item"].get("point_count", 0)), reverse=True)
    if max_objects > 0:
        ranked = ranked[:max_objects]
    features = []
    for rank, item in enumerate(ranked, start=1):
        source = item["item"]
        features.append(
            polygon_feature(
                source["geometry"],
                {
                    "id": f"upper_jet_exit_{level}_{rank:03d}",
                    "feature_type": "upper_jet_exit_region",
                    "title": f"{level}hPa 急流出口辐散区",
                    "level": f"{level}hPa",
                    "rank": rank,
                    "point_count": source["point_count"],
                    "bbox": source["bbox"],
                    "centroid": source["centroid"],
                    "mean_divergence": item["mean_div"],
                    "max_divergence": item["max_div"],
                    "divergence_threshold": threshold,
                    "nearby_upper_jet_count": len(upper_jet_features),
                    "confidence": round(min(0.88, 0.56 + item["max_div"] / max(divergence_min, 1.0e-8) * 0.08), 2),
                    "evidence": [
                        "高空散度达到急流出口区候选阈值",
                        "需结合高空急流轴上下游位置判断左/右出口区性质",
                    ],
                },
            )
        )
    return features
