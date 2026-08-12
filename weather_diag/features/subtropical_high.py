from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import geometry_bounds, mask_to_bbox_features, smooth_polygon_geometry
from weather_diag.io.geojson import polygon_feature


def _point(lat, lon, y: int, x: int, value: float) -> dict:
    return {
        "lon": round(float(lon[int(x)]), 3),
        "lat": round(float(lat[int(y)]), 3),
        "value": round(float(value), 3),
    }


def _auto_subtropical_high_contour(z500: np.ndarray, cfg: dict) -> tuple[float, str, str]:
    """Return the 588 contour in the units used by the input height field.

    NAFP/EC products may expose 500 hPa geopotential height as gpm (around
    5880), dagpm (around 588), or ECMWF geopotential (around 5.7e4 m2/s2).  The
    display object should not silently disappear because the threshold unit is
    inconsistent with the input array, so the default is automatic unless
    `auto_unit` is set to false.
    """
    arr = np.asarray(z500, dtype=float)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return float(cfg.get("contour_gpm", 5880.0)), "gpm", "configured_gpm"

    auto_unit = bool(cfg.get("auto_unit", True))
    if not auto_unit:
        contour = float(cfg.get("contour_gpm", 5880.0))
        return contour, str(cfg.get("height_unit", "gpm")), "configured"

    median_abs = float(np.nanmedian(np.abs(valid)))
    if median_abs > 20000.0:
        return 5880.0 * 9.80665, "m2 s-2", "auto_geopotential"
    if median_abs < 1000.0:
        return 588.0, "dagpm", "auto_dagpm"
    return 5880.0, "gpm", "auto_gpm"


def _component_area_km2(ys: np.ndarray, lat, lon) -> float:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    if ys.size == 0 or lat_arr.size < 2 or lon_arr.size < 2:
        return float(ys.size)
    dlat = abs(float(np.nanmedian(np.diff(lat_arr))))
    dlon = abs(float(np.nanmedian(np.diff(lon_arr))))
    row_area = dlat * 111.32 * dlon * 111.32 * np.maximum(np.cos(np.deg2rad(lat_arr[ys])), 0.2)
    return float(np.nansum(row_area))


def _metrics(item: dict, z500: np.ndarray, lat, lon, contour: float) -> dict:
    ys, xs = item["indices"]
    values = z500[ys, xs]
    max_pos = int(np.nanargmax(values))
    center_y = int(ys[max_pos])
    center_x = int(xs[max_pos])

    west_lon = float(np.nanmin(lon[xs]))
    west_candidates = np.where(np.isclose(lon[xs], west_lon))[0]
    west_choice = int(west_candidates[int(np.nanargmax(values[west_candidates]))]) if west_candidates.size else max_pos
    ridge_y = int(ys[west_choice])
    ridge_x = int(xs[west_choice])

    lon_span = float(np.nanmax(lon[xs]) - np.nanmin(lon[xs]))
    lat_span = float(np.nanmax(lat[ys]) - np.nanmin(lat[ys]))
    if lon_span >= lat_span * 1.4:
        orientation = "zonal"
    elif lat_span >= lon_span * 1.4:
        orientation = "meridional"
    else:
        orientation = "compact"

    strong_core_5920 = int(np.sum(values >= contour + 40.0))
    strong_core_5940 = int(np.sum(values >= contour + 60.0))

    return {
        "center": _point(lat, lon, center_y, center_x, float(z500[center_y, center_x])),
        "ridge_point": _point(lat, lon, ridge_y, ridge_x, float(z500[ridge_y, ridge_x])),
        "north_boundary_lat": round(float(np.nanmax(lat[ys])), 3),
        "south_boundary_lat": round(float(np.nanmin(lat[ys])), 3),
        "west_boundary_lon": round(float(np.nanmin(lon[xs])), 3),
        "east_boundary_lon": round(float(np.nanmax(lon[xs])), 3),
        "area_grid_points": int(ys.size),
        "area_km2": round(_component_area_km2(ys, lat, lon), 1),
        "max_height": round(float(np.nanmax(values)), 3),
        "mean_height": round(float(np.nanmean(values)), 3),
        "threshold_height": round(float(contour), 3),
        "axis_orientation": orientation,
        "lon_span": round(lon_span, 3),
        "lat_span": round(lat_span, 3),
        "strong_core_5920_like_points": strong_core_5920,
        "strong_core_5940_like_points": strong_core_5940,
    }


def detect_subtropical_high(z500: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("subtropical_high", {})
    z_arr = np.asarray(z500, dtype=float)
    contour, height_unit, threshold_source = _auto_subtropical_high_contour(z_arr, cfg)
    min_pts = int(cfg.get("min_area_grid_points", 20))
    smooth_boundary = bool(cfg.get("smooth_boundary", True))
    boundary_smooth_km = float(cfg.get("boundary_smooth_km", 90.0))
    boundary_simplify_km = float(cfg.get("boundary_simplify_km", 30.0))
    mask = z_arr >= contour
    out = []
    for index, item in enumerate(mask_to_bbox_features(mask, lat, lon, min_points=min_pts), start=1):
        metrics = _metrics(item, z_arr, np.asarray(lat, dtype=float), np.asarray(lon, dtype=float), contour)
        geometry = item["geometry"]
        if smooth_boundary:
            geometry = smooth_polygon_geometry(
                geometry,
                reference_lat=float(item["centroid"][1]),
                smooth_km=boundary_smooth_km,
                simplify_km=boundary_simplify_km,
            )
        display_bbox = geometry_bounds(geometry)
        props = {
            "id": f"subtropical_high_{index:03d}",
            "feature_type": "subtropical_high",
            "title": f"副热带高压 588 区 ({height_unit})",
            "confidence": round(min(0.9, 0.72 + max(0.0, metrics["mean_height"] - contour) / max(abs(contour), 1.0) * 4.0), 2),
            "point_count": item["point_count"],
            "centroid": item["centroid"],
            "bbox": display_bbox,
            "source_bbox": item["bbox"],
            "level": "500hPa",
            "contour_gpm": 5880.0 if height_unit != "dagpm" else 588.0,
            "contour_value": contour,
            "height_unit": height_unit,
            "threshold_source": threshold_source,
            "boundary_smoothed": smooth_boundary,
            "boundary_smooth_km": boundary_smooth_km if smooth_boundary else 0.0,
            "boundary_simplify_km": boundary_simplify_km if smooth_boundary else 0.0,
            "evidence": [
                f"500hPa 位势高度达到或超过 {contour:.0f} {height_unit}",
                f"西伸脊点位于 {metrics['ridge_point']['lon']:.1f}E/{metrics['ridge_point']['lat']:.1f}N",
                f"北界约 {metrics['north_boundary_lat']:.1f}N，面积约 {metrics['area_km2']:.0f} km²",
                f"高度阈值来源：{threshold_source}",
            ],
            **metrics,
        }
        out.append(polygon_feature(geometry, props))
    return out
