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


def ranked_mask_items(
    mask: np.ndarray,
    lat,
    lon,
    *,
    min_points: int,
    max_objects: int,
    primary_value: np.ndarray,
    descending: bool,
) -> list[dict]:
    items = mask_to_bbox_features(mask, lat, lon, min_points=min_points)

    def sort_key(item: dict) -> tuple[float, float]:
        ys, xs = item["indices"]
        mean_value = float(np.nanmean(primary_value[ys, xs]))
        strength = mean_value if descending else -mean_value
        return float(item["point_count"]), strength

    items.sort(key=sort_key, reverse=True)
    if max_objects > 0:
        items = items[:max_objects]
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return items


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
    )
    for item in items:
        ys, xs = item["indices"]
        mean_smoothed = float(np.nanmean(smoothed[ys, xs]))
        mean_raw = float(np.nanmean(div_field[ys, xs]))
        max_strength = float(np.nanmax(smoothed[ys, xs]) if descending else np.nanmax(-smoothed[ys, xs]))
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
            "max_strength": max_strength,
            "confidence": 0.68,
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
    smoothed = smooth_field(div850, sigma)
    if "divergence_percentile" in cfg:
        threshold = _finite_percentile(smoothed, float(cfg["divergence_percentile"]))
    else:
        threshold = float(cfg.get("divergence_max", -1.0e-5))
    mask = smoothed <= threshold
    if u850 is not None and v850 is not None:
        vector_div = smooth_field(divergence(u850, v850, lat, lon), sigma)
        mask &= vector_div <= 0
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
        evidence=[
            "850hPa 散度经平滑后仍为低值，表示低层辐合",
            "仅保留面积和辐合强度排序靠前的主要对象",
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
    smoothed = smooth_field(div_upper, sigma)
    if "divergence_percentile" in cfg:
        threshold = _finite_percentile(smoothed, float(cfg["divergence_percentile"]))
    else:
        threshold = float(cfg.get("divergence_min", 1.0e-5))
    mask = smoothed >= threshold
    if u_upper is not None and v_upper is not None:
        vector_div = smooth_field(divergence(u_upper, v_upper, lat, lon), sigma)
        mask &= vector_div >= 0
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
        evidence=[
            f"{level}hPa 散度经平滑后仍为高值，表示高空辐散",
            "仅保留面积和辐散强度排序靠前的主要对象",
        ],
    )
