from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.diagnostics.divergence import divergence
from weather_diag.diagnostics.grid import component_axis_line, mask_to_bbox_features
from weather_diag.io.geojson import line_feature, polygon_feature


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
    ys, _xs = item["indices"]
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    if ys.size == 0 or lat_arr.size < 2 or lon_arr.size < 2:
        return float(item.get("point_count", 0))
    dlat = abs(float(np.nanmedian(np.diff(lat_arr))))
    dlon = abs(float(np.nanmedian(np.diff(lon_arr))))
    row_area = dlat * 111.32 * dlon * 111.32 * np.maximum(np.cos(np.deg2rad(lat_arr[ys])), 0.2)
    return float(np.nansum(row_area))


def _line_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        mean_lat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * 111.32 * max(np.cos(np.deg2rad(mean_lat)), 0.2)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


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


def _divergence_mask(div_field: np.ndarray, thresholds: dict, *, kind: str, u=None, v=None, lat=None, lon=None):
    cfg = thresholds.get("convergence" if kind == "convergence" else "upper_divergence", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    smoothed = smooth_field(div_field, sigma)
    if kind == "convergence":
        absolute = float(cfg.get("divergence_max", -1.0e-5))
        percentile_threshold = _finite_percentile(smoothed, float(cfg.get("divergence_percentile", 10)))
        threshold = min(percentile_threshold, absolute) if np.isfinite(percentile_threshold) else absolute
        mask = (smoothed <= threshold) & (smoothed <= absolute)
        if u is not None and v is not None:
            vector_div = smooth_field(divergence(u, v, lat, lon), sigma)
            mask &= vector_div <= absolute * 0.25
    else:
        absolute = float(cfg.get("divergence_min", 1.0e-5))
        percentile_threshold = _finite_percentile(smoothed, float(cfg.get("divergence_percentile", 90)))
        threshold = max(percentile_threshold, absolute) if np.isfinite(percentile_threshold) else absolute
        mask = (smoothed >= threshold) & (smoothed >= absolute)
        if u is not None and v is not None:
            vector_div = smooth_field(divergence(u, v, lat, lon), sigma)
            mask &= vector_div >= absolute * 0.25
    mask = _morphology(mask, cfg)
    return cfg, smoothed, mask, threshold, percentile_threshold, absolute


def detect_low_level_convergence(
    div850: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
) -> list[dict]:
    cfg, smoothed, mask, threshold, percentile_threshold, divergence_max = _divergence_mask(
        div850,
        thresholds,
        kind="convergence",
        u=u850,
        v=v850,
        lat=lat,
        lon=lon,
    )
    min_pts = int(cfg.get("min_area_grid_points", 12))
    max_objects = int(cfg.get("max_objects", 12))
    min_area_km2 = float(cfg.get("min_area_km2", 0.0))
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
        percentile_threshold=percentile_threshold,
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
    cfg, smoothed, mask, threshold, percentile_threshold, divergence_min = _divergence_mask(
        div_upper,
        thresholds,
        kind="divergence",
        u=u_upper,
        v=v_upper,
        lat=lat,
        lon=lon,
    )
    min_pts = int(cfg.get("min_area_grid_points", 12))
    max_objects = int(cfg.get("max_objects", 12))
    min_area_km2 = float(cfg.get("min_area_km2", 0.0))
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
        percentile_threshold=percentile_threshold,
        absolute_threshold=divergence_min,
        evidence=[
            f"{level}hPa 散度经平滑后大于 {divergence_min:.1e} s^-1，满足绝对辐散强度约束",
            "同时结合区域分位阈值、面积和辐散强度过滤弱场误报",
        ],
    )


def _axis_features_from_divergence_mask(
    mask: np.ndarray,
    smoothed: np.ndarray,
    lat,
    lon,
    *,
    feature_type: str,
    title: str,
    level: str,
    descending: bool,
    min_points: int,
    max_objects: int,
) -> list[dict]:
    items = ranked_mask_items(
        mask,
        lat,
        lon,
        min_points=min_points,
        max_objects=max_objects,
        primary_value=smoothed,
        descending=descending,
    )
    features = []
    for item in items:
        line = component_axis_line(item, lat, lon, max_points=64)
        coords = line.get("coordinates") or []
        if len(coords) < 2:
            continue
        ys, xs = item["indices"]
        strength = smoothed[ys, xs] if descending else -smoothed[ys, xs]
        features.append(
            line_feature(
                coords,
                {
                    "id": f"{feature_type}_{item['rank']:03d}",
                    "feature_type": feature_type,
                    "title": title,
                    "level": level,
                    "rank": item["rank"],
                    "geometry_role": "axis",
                    "source_area_bbox": item.get("bbox"),
                    "source_area_point_count": item.get("point_count"),
                    "axis_length_km": round(_line_length_km(coords), 1),
                    "mean_strength": float(np.nanmean(strength)),
                    "max_strength": float(np.nanmax(strength)),
                    "confidence": 0.64,
                    "evidence": ["由辐合/辐散区连通对象进一步抽取 LineString 主轴", "业务图可默认显示轴线，debug 图层再显示面区域"],
                },
            )
        )
    return features


def detect_low_level_convergence_axes(
    div850: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
) -> list[dict]:
    cfg, smoothed, mask, _threshold, _percentile_threshold, _absolute = _divergence_mask(
        div850,
        thresholds,
        kind="convergence",
        u=u850,
        v=v850,
        lat=lat,
        lon=lon,
    )
    return _axis_features_from_divergence_mask(
        mask,
        smoothed,
        lat,
        lon,
        feature_type="low_level_convergence_axis",
        title="850hPa 低层辐合轴",
        level="850hPa",
        descending=False,
        min_points=int(cfg.get("min_area_grid_points", 12)),
        max_objects=int(cfg.get("max_objects", 12)),
    )


def detect_upper_divergence_axes(
    div_upper: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    level: int,
    *,
    u_upper: np.ndarray | None = None,
    v_upper: np.ndarray | None = None,
) -> list[dict]:
    cfg, smoothed, mask, _threshold, _percentile_threshold, _absolute = _divergence_mask(
        div_upper,
        thresholds,
        kind="divergence",
        u=u_upper,
        v=v_upper,
        lat=lat,
        lon=lon,
    )
    return _axis_features_from_divergence_mask(
        mask,
        smoothed,
        lat,
        lon,
        feature_type="upper_divergence_axis",
        title=f"{level}hPa 高空辐散轴",
        level=f"{level}hPa",
        descending=True,
        min_points=int(cfg.get("min_area_grid_points", 12)),
        max_objects=int(cfg.get("max_objects", 12)),
    )
