from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.diagnostics.grid import derivatives_lonlat
from weather_diag.io.geojson import point_feature


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


def _finite_percentile(values: np.ndarray, percentile: float, default: float = 0.0) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return default
    return float(np.nanpercentile(valid, percentile))


def _dagpm_to_input_scale(height: np.ndarray) -> tuple[float, str]:
    valid = np.asarray(height, dtype=float)
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return 1.0, "dagpm"
    median_abs = float(np.nanmedian(np.abs(valid)))
    if median_abs > 20000.0:
        return 98.0665, "m2 s-2"
    if median_abs < 1000.0:
        return 1.0, "dagpm"
    return 10.0, "gpm"


def _grid_area_km2(mask: np.ndarray, lat, lon) -> float:
    ys, _ = np.where(mask)
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    if ys.size == 0 or lat_arr.size < 2 or lon_arr.size < 2:
        return float(ys.size)
    dlat = abs(float(np.nanmedian(np.diff(lat_arr))))
    dlon = abs(float(np.nanmedian(np.diff(lon_arr))))
    return float(np.nansum(dlat * 111.32 * dlon * 111.32 * np.maximum(np.cos(np.deg2rad(lat_arr[ys])), 0.2)))


def _relative_vorticity(u: np.ndarray, v: np.ndarray, lat, lon) -> np.ndarray:
    _dudx, dudy = derivatives_lonlat(u, lat, lon)
    dvdx, _dvdy = derivatives_lonlat(v, lat, lon)
    return dvdx - dudy


def _local_minima(field: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(field, dtype=float)
    filt = ndimage.minimum_filter(arr, size=size, mode="nearest")
    return np.where((arr == filt) & np.isfinite(arr))


def detect_cold_vortex(
    height: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    u: np.ndarray | None = None,
    v: np.ndarray | None = None,
    temperature: np.ndarray | None = None,
    level: int = 500,
) -> list[dict]:
    """Detect mid-level vortex/cold-vortex candidates.

    This is a conservative point-object detector intended to complement the
    trough-line algorithm. It looks for a smoothed geopotential-height minimum
    supported by positive relative vorticity and, when available, a cold-core
    temperature anomaly.
    """
    cfg = thresholds.get("vortex", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.2))
    min_distance_grid = int(cfg.get("min_distance_grid", 8))
    max_objects = int(cfg.get("max_objects", 8))
    height_scale, height_unit = _dagpm_to_input_scale(height)
    min_prominence = float(cfg.get("min_height_prominence", 2.0)) * height_scale
    min_area_km2 = float(cfg.get("min_closed_area_km2", 40000.0))
    vort_min = float(cfg.get("vorticity_min", 1.0e-5))

    z = _nan_smooth(height, sigma)
    anom = z - np.nanmean(z, axis=1, keepdims=True)
    vort = _relative_vorticity(u, v, lat, lon) if u is not None and v is not None else np.zeros_like(z)
    vort_s = _nan_smooth(vort, sigma)
    temp_anom = None
    if temperature is not None:
        t_s = _nan_smooth(temperature, sigma)
        temp_anom = t_s - np.nanmean(t_s, axis=1, keepdims=True)

    ys, xs = _local_minima(z, max(3, min_distance_grid))
    candidates = []
    for y, x in zip(ys, xs):
        y = int(y)
        x = int(x)
        y0 = max(0, y - min_distance_grid)
        y1 = min(z.shape[0], y + min_distance_grid + 1)
        x0 = max(0, x - min_distance_grid)
        x1 = min(z.shape[1], x + min_distance_grid + 1)
        local = z[y0:y1, x0:x1]
        if local.size == 0 or not np.isfinite(local).any():
            continue
        prominence = float(np.nanmean(local) - z[y, x])
        if prominence < min_prominence:
            continue
        threshold = z[y, x] + max(min_prominence, float(cfg.get("closed_height_interval", 2.0)) * height_scale)
        component_mask = z <= threshold
        labels, _ = ndimage.label(component_mask)
        label_id = int(labels[y, x])
        if label_id == 0:
            continue
        component = labels == label_id
        area_km2 = _grid_area_km2(component, lat, lon)
        if area_km2 < min_area_km2:
            continue
        vort_value = float(vort_s[y, x]) if np.isfinite(vort_s[y, x]) else 0.0
        if u is not None and v is not None and vort_value < vort_min:
            continue
        cold_score = None
        if temp_anom is not None:
            cold_score = float(temp_anom[y, x])
        confidence = 0.52 + min(prominence / max(min_prominence * 3.0, 1.0), 1.0) * 0.20
        if vort_value >= vort_min:
            confidence += 0.12
        if cold_score is not None and cold_score < 0:
            confidence += 0.08
        candidates.append(
            {
                "y": y,
                "x": x,
                "height": float(height[y, x]),
                "height_anomaly": float(anom[y, x]),
                "prominence": prominence,
                "vorticity": vort_value,
                "cold_core_anomaly": cold_score,
                "closed_area_km2": area_km2,
                "confidence": float(np.clip(confidence, 0.35, 0.92)),
            }
        )
    candidates.sort(key=lambda item: (item["confidence"], item["prominence"], item["closed_area_km2"]), reverse=True)
    if max_objects > 0:
        candidates = candidates[:max_objects]

    features = []
    for rank, item in enumerate(candidates, start=1):
        feature_type = "cold_vortex" if item.get("cold_core_anomaly") is not None and item.get("cold_core_anomaly", 0.0) < 0 else "mid_level_vortex"
        title = f"{level}hPa 冷涡候选" if feature_type == "cold_vortex" else f"{level}hPa 低涡候选"
        props = {
            "id": f"{feature_type}_{level}_{rank:03d}",
            "feature_type": feature_type,
            "title": title,
            "level": f"{level}hPa",
            "rank": rank,
            "height": round(item["height"], 2),
            "height_unit": height_unit,
            "height_anomaly": round(item["height_anomaly"], 2),
            "height_prominence": round(item["prominence"], 2),
            "relative_vorticity": item["vorticity"],
            "cold_core_anomaly": item["cold_core_anomaly"],
            "closed_area_km2": round(item["closed_area_km2"], 1),
            "confidence": round(item["confidence"], 2),
            "evidence": [
                f"位势高度场存在天气尺度闭合低值中心，阈值已按 {height_unit} 换算",
                "相对涡度为正并支撑气旋性环流" if u is not None and v is not None else "未提供风场，未做相对涡度约束",
                "温度距平偏冷，支持冷涡性质" if item.get("cold_core_anomaly") is not None and item.get("cold_core_anomaly") < 0 else "未确认冷心结构",
            ],
        }
        features.append(point_feature(float(np.asarray(lon)[item["x"]]), float(np.asarray(lat)[item["y"]]), props))
    return features
