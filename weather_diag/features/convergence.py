from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.diagnostics.divergence import divergence
from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.io.geojson import polygon_feature


def smooth_field(field: np.ndarray, sigma: float) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    if sigma <= 0:
        return arr.copy()
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=out, where=weight_sum > 1e-6)
    return out


def _finite_percentile(values: np.ndarray, percentile: float) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return float("nan")
    return float(np.nanpercentile(valid, percentile))


def _morphology(mask: np.ndarray, cfg: dict) -> np.ndarray:
    out = np.asarray(mask, dtype=bool)
    structure = np.ones((3, 3), dtype=bool)
    open_iter = int(cfg.get("morphology_opening_grid", 0))
    close_iter = int(cfg.get("morphology_closing_grid", 0))
    if open_iter > 0:
        out = ndimage.binary_opening(out, structure=structure, iterations=open_iter)
    if close_iter > 0:
        out = ndimage.binary_closing(out, structure=structure, iterations=close_iter)
    return out


def _grid_spacing_km(lat: np.ndarray, lon: np.ndarray) -> tuple[float, float]:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    dy = float(np.nanmedian(np.abs(np.diff(lat_arr)))) * 111.32 if lat_arr.size > 1 else 111.32
    dx_deg = float(np.nanmedian(np.abs(np.diff(lon_arr)))) if lon_arr.size > 1 else 1.0
    lat_ref = float(np.nanmedian(lat_arr)) if lat_arr.size else 0.0
    dx = dx_deg * 111.32 * max(float(np.cos(np.deg2rad(lat_ref))), 0.2)
    return max(dx, 1.0), max(dy, 1.0)


def _component_area_km2(item: dict, lat: np.ndarray, lon: np.ndarray) -> float:
    dx, dy = _grid_spacing_km(lat, lon)
    return float(item.get("point_count", 0)) * dx * dy


def ranked_mask_items(
    mask: np.ndarray,
    lat,
    lon,
    *,
    min_points: int,
    max_objects: int,
    primary_value: np.ndarray,
    descending: bool,
    min_mean_strength: float = 0.0,
    min_max_strength: float = 0.0,
    min_area_km2: float = 0.0,
) -> list[dict]:
    items = mask_to_bbox_features(mask, lat, lon, min_points=min_points)
    filtered = []
    for item in items:
        ys, xs = item["indices"]
        strength_values = primary_value[ys, xs] if descending else -primary_value[ys, xs]
        mean_strength = float(np.nanmean(strength_values)) if strength_values.size else 0.0
        max_strength = float(np.nanmax(strength_values)) if strength_values.size else 0.0
        area_km2 = _component_area_km2(item, np.asarray(lat, dtype=float), np.asarray(lon, dtype=float))
        if mean_strength < min_mean_strength or max_strength < min_max_strength or area_km2 < min_area_km2:
            continue
        item["mean_strength"] = mean_strength
        item["max_strength"] = max_strength
        item["area_km2"] = area_km2
        filtered.append(item)

    def sort_key(item: dict) -> tuple[float, float, float]:
        return float(item.get("max_strength", 0.0)), float(item.get("mean_strength", 0.0)), float(item["point_count"])

    filtered.sort(key=sort_key, reverse=True)
    if max_objects > 0:
        filtered = filtered[:max_objects]
    for rank, item in enumerate(filtered, start=1):
        item["rank"] = rank
    return filtered


def _ranked_divergence_features(
    div_field: np.ndarray,
    lat,
    lon,
    *,
    mask: np.ndarray,
    smoothed: np.ndarray,
    min_points: int,
    max_objects: int,
    descending: bool,
    feature_type: str,
    title: str,
    level: str,
    evidence: list[str],
    min_mean_strength: float = 0.0,
    min_max_strength: float = 0.0,
    min_area_km2: float = 0.0,
    threshold_value: float | None = None,
    percentile_threshold: float | None = None,
    absolute_threshold: float | None = None,
) -> list[dict]:
    features = []
    items = ranked_mask_items(
        mask,
        lat,
        lon,
        min_points=min_points,
        max_objects=max_objects,
        primary_value=smoothed,
        descending=descending,
        min_mean_strength=min_mean_strength,
        min_max_strength=min_max_strength,
        min_area_km2=min_area_km2,
    )
    for item in items:
        ys, xs = item["indices"]
        mean_smoothed = float(np.nanmean(smoothed[ys, xs]))
        mean_raw = float(np.nanmean(div_field[ys, xs]))
        max_strength = float(item.get("max_strength", np.nanmax(smoothed[ys, xs]) if descending else np.nanmax(-smoothed[ys, xs])))
        mean_strength = float(item.get("mean_strength", np.nanmean(smoothed[ys, xs]) if descending else np.nanmean(-smoothed[ys, xs])))
        props = {
            "id": f"{feature_type}_{item['rank']:03d}",
            "feature_type": feature_type,
            "title": title,
            "level": level,
            "rank": item["rank"],
            "point_count": item["point_count"],
            "bbox": item["bbox"],
            "centroid": item["centroid"],
            "mean_value": mean_raw,
            "mean_smoothed_divergence": mean_smoothed,
            "mean_strength": mean_strength,
            "max_strength": max_strength,
            "area_km2": round(float(item.get("area_km2", 0.0)), 1),
            "threshold_value": threshold_value,
            "percentile_threshold": percentile_threshold,
            "absolute_threshold": absolute_threshold,
            "confidence": round(min(0.9, 0.58 + max_strength / max(min_max_strength, 1.0e-6) * 0.12), 2) if min_max_strength > 0 else 0.68,
            "evidence": evidence,
        }
        features.append(polygon_feature(item["geometry"], props))
    return features


def detect_low_level_convergence(
    div850: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("convergence", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    max_objects = int(cfg.get("max_objects", 12))
    min_area_km2 = float(cfg.get("min_area_km2", 0.0))
    divergence_max = float(cfg.get("divergence_max", -1.0e-5))
    smoothed = smooth_field(div850, sigma)
    if "divergence_percentile" in cfg:
        percentile_threshold = _finite_percentile(smoothed, float(cfg["divergence_percentile"]))
        threshold = min(percentile_threshold, divergence_max) if np.isfinite(percentile_threshold) else divergence_max
    else:
        threshold = divergence_max
    mask = (smoothed <= threshold) & (smoothed <= divergence_max)
    if u850 is not None and v850 is not None:
        vector_div = smooth_field(divergence(u850, v850, lat, lon), sigma)
        mask &= vector_div <= divergence_max * 0.25
    mask = _morphology(mask, cfg)
    min_mean_strength = float(cfg.get("min_mean_convergence", cfg.get("convergence_mean_min", 0.0)))
    min_max_strength = float(cfg.get("convergence_min", abs(divergence_max)))
    return _ranked_divergence_features(
        div850,
        lat,
        lon,
        mask=mask,
        smoothed=smoothed,
        min_points=min_pts,
        max_objects=max_objects,
        descending=False,
        feature_type="low_level_convergence",
        title="850hPa 低层辐合区",
        level="850hPa",
        min_mean_strength=min_mean_strength,
        min_max_strength=min_max_strength,
        min_area_km2=min_area_km2,
        threshold_value=threshold,
        percentile_threshold=percentile_threshold if "divergence_percentile" in cfg else None,
        absolute_threshold=divergence_max,
        evidence=[
            f"850hPa 散度经平滑后小于 {divergence_max:.1e} s^-1，满足绝对辐合强度约束",
            "同时结合区域分位阈值、面积和辐合强度过滤弱场误报",
        ],
    )


def detect_upper_divergence(
    div_upper: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    level: int,
    *,
    u_upper: np.ndarray | None = None,
    v_upper: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("upper_divergence", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    max_objects = int(cfg.get("max_objects", 12))
    min_area_km2 = float(cfg.get("min_area_km2", 0.0))
    divergence_min = float(cfg.get("divergence_min", 1.0e-5))
    smoothed = smooth_field(div_upper, sigma)
    if "divergence_percentile" in cfg:
        percentile_threshold = _finite_percentile(smoothed, float(cfg["divergence_percentile"]))
        threshold = max(percentile_threshold, divergence_min) if np.isfinite(percentile_threshold) else divergence_min
    else:
        threshold = divergence_min
    mask = (smoothed >= threshold) & (smoothed >= divergence_min)
    if u_upper is not None and v_upper is not None:
        vector_div = smooth_field(divergence(u_upper, v_upper, lat, lon), sigma)
        mask &= vector_div >= divergence_min * 0.25
    mask = _morphology(mask, cfg)
    min_mean_strength = float(cfg.get("min_mean_divergence", cfg.get("divergence_mean_min", 0.0)))
    min_max_strength = float(cfg.get("divergence_strength_min", divergence_min))
    return _ranked_divergence_features(
        div_upper,
        lat,
        lon,
        mask=mask,
        smoothed=smoothed,
        min_points=min_pts,
        max_objects=max_objects,
        descending=True,
        feature_type="upper_divergence",
        title=f"{level}hPa 高空辐散区",
        level=f"{level}hPa",
        min_mean_strength=min_mean_strength,
        min_max_strength=min_max_strength,
        min_area_km2=min_area_km2,
        threshold_value=threshold,
        percentile_threshold=percentile_threshold if "divergence_percentile" in cfg else None,
        absolute_threshold=divergence_min,
        evidence=[
            f"{level}hPa 散度经平滑后大于 {divergence_min:.1e} s^-1，满足绝对辐散强度约束",
            "同时结合区域分位阈值、面积和辐散强度过滤弱场误报",
        ],
    )
