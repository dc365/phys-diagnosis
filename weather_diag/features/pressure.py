from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.io.geojson import point_feature


EARTH_KM_PER_DEGREE = 111.32


def _grid_spacing_km(lat: np.ndarray, lon: np.ndarray) -> tuple[float, float]:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    dlat = float(np.nanmedian(np.abs(np.diff(lat_arr)))) if lat_arr.size > 1 else 1.0
    dlon = float(np.nanmedian(np.abs(np.diff(lon_arr)))) if lon_arr.size > 1 else 1.0
    mean_lat = float(np.nanmean(lat_arr)) if lat_arr.size else 35.0
    dy = dlat * EARTH_KM_PER_DEGREE
    dx = dlon * EARTH_KM_PER_DEGREE * max(np.cos(np.deg2rad(mean_lat)), 0.2)
    return max(dx, 1.0e-6), max(dy, 1.0e-6)


def _grid_count_from_km(value_km: float | None, lat: np.ndarray, lon: np.ndarray, *, default: int, diameter: bool = False) -> int:
    if value_km is None or not np.isfinite(value_km) or value_km <= 0:
        return int(max(1, default))
    dx, dy = _grid_spacing_km(lat, lon)
    radius = max(1, int(round(float(value_km) / min(dx, dy))))
    return radius * 2 + 1 if diameter else radius


def _component_area_km2(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> float:
    ys, _xs = np.where(mask)
    if ys.size == 0:
        return 0.0
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    if lat_arr.size < 2 or lon_arr.size < 2:
        return float(ys.size)
    dlat = abs(float(np.nanmedian(np.diff(lat_arr))))
    dlon = abs(float(np.nanmedian(np.diff(lon_arr))))
    row_area = dlat * EARTH_KM_PER_DEGREE * dlon * EARTH_KM_PER_DEGREE * np.maximum(np.cos(np.deg2rad(lat_arr[ys])), 0.2)
    return float(np.nansum(row_area))


def _local_extrema(field: np.ndarray, mode: str, size: int):
    arr = np.asarray(field, dtype=float)
    if mode == "max":
        filt = ndimage.maximum_filter(arr, size=size, mode="nearest")
        return np.where((arr == filt) & np.isfinite(arr))
    filt = ndimage.minimum_filter(arr, size=size, mode="nearest")
    return np.where((arr == filt) & np.isfinite(arr))


def _touches_grid_edge(mask: np.ndarray) -> bool:
    return bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any())


def _inside_edge_margin(y: int, x: int, shape: tuple[int, int], margin: int) -> bool:
    return margin <= y < shape[0] - margin and margin <= x < shape[1] - margin


def _closed_contour_stats(
    arr: np.ndarray,
    y: int,
    x: int,
    *,
    mode: str,
    interval_hpa: float,
    max_steps: int,
    lat: np.ndarray,
    lon: np.ndarray,
) -> dict:
    center_value = float(arr[y, x])
    structure = np.ones((3, 3), dtype=bool)
    closed_levels = []
    closed_areas: list[tuple[int, float]] = []

    for step in range(1, max_steps + 1):
        level = center_value - step * interval_hpa if mode == "max" else center_value + step * interval_hpa
        if mode == "max":
            if level <= float(np.nanmin(arr)):
                break
            mask = arr >= level
        else:
            if level >= float(np.nanmax(arr)):
                break
            mask = arr <= level
        labels, _ = ndimage.label(mask, structure=structure)
        label_id = int(labels[y, x])
        if label_id == 0:
            break
        component = labels == label_id
        if _touches_grid_edge(component):
            break
        closed_levels.append(float(level))
        closed_areas.append((int(component.sum()), _component_area_km2(component, lat, lon)))

    if not closed_levels:
        return {
            "closed_contour_count": 0,
            "outer_closed_contour_hpa": None,
            "pressure_difference_hpa": 0.0,
            "closed_area_grid_points": 0,
            "closed_area_km2": 0.0,
        }
    outer_level = closed_levels[-1]
    pressure_difference = center_value - outer_level if mode == "max" else outer_level - center_value
    return {
        "closed_contour_count": len(closed_levels),
        "outer_closed_contour_hpa": round(float(outer_level), 2),
        "pressure_difference_hpa": round(float(pressure_difference), 2),
        "closed_area_grid_points": closed_areas[-1][0],
        "closed_area_km2": round(float(closed_areas[-1][1]), 1),
    }


def detect_high_low(mslp: np.ndarray, lat: np.ndarray, lon: np.ndarray, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("pressure_system", {})
    size = _grid_count_from_km(
        float(cfg["min_distance_km"]) if "min_distance_km" in cfg else None,
        lat,
        lon,
        default=int(cfg.get("min_distance_grid", 6)),
        diameter=True,
    )
    max_centers = int(cfg.get("max_centers", 20))
    prominence = float(cfg.get("min_prominence_hpa", 1.5))
    min_closed_area_km2 = float(cfg.get("min_closed_area_km2", 0.0))
    interval_hpa = max(0.1, float(cfg.get("contour_interval_hpa", 1.0)))
    min_closed_contours = max(1, int(cfg.get("min_closed_contours", 2)))
    max_closed_contours = max(min_closed_contours, int(cfg.get("max_closed_contours", 8)))
    edge_margin = max(
        0,
        _grid_count_from_km(
            float(cfg["edge_margin_km"]) if "edge_margin_km" in cfg else None,
            lat,
            lon,
            default=int(cfg.get("edge_margin_grid", max(1, size // 2))),
            diameter=False,
        ),
    )
    smoothing_sigma = max(0.0, float(cfg.get("smoothing_sigma_grid", 1.0)))
    features = []
    arr = np.asarray(mslp, dtype=float)
    smooth = ndimage.gaussian_filter(arr, sigma=smoothing_sigma, mode="nearest") if smoothing_sigma > 0 else arr

    for mode, ftype, label in [("max", "high", "H"), ("min", "low", "L")]:
        ys, xs = _local_extrema(smooth, mode, size=size)
        candidates = []
        for y, x in zip(ys, xs):
            if not _inside_edge_margin(int(y), int(x), arr.shape, edge_margin):
                continue
            y0, y1 = max(0, y - size), min(arr.shape[0], y + size + 1)
            x0, x1 = max(0, x - size), min(arr.shape[1], x + size + 1)
            local = smooth[y0:y1, x0:x1]
            val = float(arr[y, x])
            smooth_val = float(smooth[y, x])
            if mode == "max":
                prom = smooth_val - float(np.nanmean(local))
            else:
                prom = float(np.nanmean(local)) - smooth_val
            closed = _closed_contour_stats(
                smooth,
                int(y),
                int(x),
                mode=mode,
                interval_hpa=interval_hpa,
                max_steps=max_closed_contours,
                lat=lat,
                lon=lon,
            )
            if (
                prom >= prominence
                and closed["closed_contour_count"] >= min_closed_contours
                and float(closed.get("closed_area_km2") or 0.0) >= min_closed_area_km2
            ):
                candidates.append((closed["closed_contour_count"], closed["pressure_difference_hpa"], prom, int(y), int(x), val, closed))
        candidates.sort(reverse=True, key=lambda item: (item[0], item[1], item[2]))
        for rank, (closed_count, pressure_difference, prom, y, x, val, closed) in enumerate(candidates[:max_centers], start=1):
            confidence = float(min(0.98, 0.50 + closed_count * 0.06 + pressure_difference / max(1.0, prominence) * 0.05))
            props = {
                "id": f"{ftype}_{rank:03d}",
                "feature_type": ftype,
                "label": label,
                "level": "mslp",
                "value": round(float(val), 2),
                "unit": "hPa",
                "confidence": round(confidence, 2),
                "closed_contour_count": int(closed["closed_contour_count"]),
                "outer_closed_contour_hpa": closed["outer_closed_contour_hpa"],
                "pressure_difference_hpa": closed["pressure_difference_hpa"],
                "closed_area_grid_points": closed["closed_area_grid_points"],
                "closed_area_km2": closed["closed_area_km2"],
                "min_distance_grid_used": size,
                "edge_margin_grid_used": edge_margin,
                "evidence": [
                    "局地气压极值明显且不贴近资料边界",
                    f"中心值相对周边差异约 {prom:.1f} hPa",
                    f"存在 {closed['closed_contour_count']} 圈闭合等压线，最外圈约 {closed['outer_closed_contour_hpa']:.2f} hPa",
                    f"中心到最外闭合等压线差值约 {closed['pressure_difference_hpa']:.1f} hPa",
                    f"闭合系统面积约 {closed['closed_area_km2']:.0f} km²",
                ],
            }
            features.append(point_feature(float(lon[x]), float(lat[y]), props))
    return features
