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

    return {
        "center": _point(lat, lon, center_y, center_x, float(z500[center_y, center_x])),
        "ridge_point": _point(lat, lon, ridge_y, ridge_x, float(z500[ridge_y, ridge_x])),
        "north_boundary_lat": round(float(np.nanmax(lat[ys])), 3),
        "south_boundary_lat": round(float(np.nanmin(lat[ys])), 3),
        "west_boundary_lon": round(float(np.nanmin(lon[xs])), 3),
        "east_boundary_lon": round(float(np.nanmax(lon[xs])), 3),
        "area_grid_points": int(ys.size),
        "max_height": round(float(np.nanmax(values)), 3),
        "mean_height": round(float(np.nanmean(values)), 3),
        "threshold_height": round(float(contour), 3),
        "axis_orientation": orientation,
        "lon_span": round(lon_span, 3),
        "lat_span": round(lat_span, 3),
    }


def detect_subtropical_high(z500: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("subtropical_high", {})
    contour = float(cfg.get("contour_gpm", 5880))
    min_pts = int(cfg.get("min_area_grid_points", 20))
    smooth_boundary = bool(cfg.get("smooth_boundary", True))
    boundary_smooth_km = float(cfg.get("boundary_smooth_km", 90.0))
    boundary_simplify_km = float(cfg.get("boundary_simplify_km", 30.0))
    mask = np.asarray(z500) >= contour
    out = []
    for index, item in enumerate(mask_to_bbox_features(mask, lat, lon, min_points=min_pts), start=1):
        metrics = _metrics(item, np.asarray(z500, dtype=float), np.asarray(lat, dtype=float), np.asarray(lon, dtype=float), contour)
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
            "title": "副热带高压 5880gpm 区域",
            "confidence": round(min(0.9, 0.72 + max(0.0, metrics["mean_height"] - contour) / max(contour, 1.0) * 4.0), 2),
            "point_count": item["point_count"],
            "centroid": item["centroid"],
            "bbox": display_bbox,
            "source_bbox": item["bbox"],
            "level": "500hPa",
            "contour_gpm": contour,
            "boundary_smoothed": smooth_boundary,
            "boundary_smooth_km": boundary_smooth_km if smooth_boundary else 0.0,
            "boundary_simplify_km": boundary_simplify_km if smooth_boundary else 0.0,
            "evidence": [
                f"500hPa 位势高度达到或超过 {contour:.0f} gpm",
                f"西伸脊点位于 {metrics['ridge_point']['lon']:.1f}E/{metrics['ridge_point']['lat']:.1f}N",
                f"北界约 {metrics['north_boundary_lat']:.1f}N，面积 {metrics['area_grid_points']} 个格点",
            ],
            **metrics,
        }
        out.append(polygon_feature(geometry, props))
    return out
