from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def _as_2d_lat(lat: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    lat = np.asarray(lat)
    if lat.ndim == 1:
        return np.repeat(lat[:, None], shape[1], axis=1)
    return lat


def derivatives_lonlat(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return df/dx, df/dy on a regular or quasi-regular lat/lon grid.

    field must be 2D with shape (lat, lon). Coordinates can be ascending or descending.
    Units: field units per meter.
    """
    arr = np.asarray(field, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    if arr.ndim != 2:
        raise ValueError("derivatives_lonlat expects a 2D field")
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("lat/lon must be 1D arrays in this MVP")

    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)

    # np.gradient supports non-uniform coordinates and preserves sign for descending coords.
    dfdlat_rad = np.gradient(arr, lat_rad, axis=0, edge_order=1)
    dfdlon_rad = np.gradient(arr, lon_rad, axis=1, edge_order=1)

    coslat = np.cos(lat_rad)
    coslat = np.where(np.abs(coslat) < 1e-6, np.nan, coslat)

    dfdy = dfdlat_rad / EARTH_RADIUS_M
    dfdx = dfdlon_rad / (EARTH_RADIUS_M * coslat[:, None])
    return dfdx, dfdy


def normalize01(field: np.ndarray, p_low: float = 5, p_high: float = 95) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros_like(arr, dtype=float)
    lo, hi = np.nanpercentile(valid, [p_low, p_high])
    if not np.isfinite(hi - lo) or abs(hi - lo) < 1e-12:
        return np.zeros_like(arr, dtype=float)
    out = (arr - lo) / (hi - lo)
    return np.clip(out, 0.0, 1.0)


def mask_to_bbox_features(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray, *, min_points: int = 5):
    """Convert connected mask regions to simple bbox polygons.

    This is intentionally simple for the MVP. It gives usable GeoJSON features without
    requiring heavy contour polygonization. Future versions should replace this with
    contour/MVT polygon extraction.
    """
    from scipy import ndimage

    mask = np.asarray(mask).astype(bool)
    labels, count = ndimage.label(mask)
    features = []
    for label_id in range(1, count + 1):
        ys, xs = np.where(labels == label_id)
        if ys.size < min_points:
            continue
        lat_min, lat_max = float(np.nanmin(lat[ys])), float(np.nanmax(lat[ys]))
        lon_min, lon_max = float(np.nanmin(lon[xs])), float(np.nanmax(lon[xs]))
        # Ensure bbox has nonzero area.
        if lat_min == lat_max:
            lat_min -= 0.05
            lat_max += 0.05
        if lon_min == lon_max:
            lon_min -= 0.05
            lon_max += 0.05
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max],
                [lon_min, lat_max], [lon_min, lat_min]
            ]]
        }
        features.append({
            "geometry": geom,
            "indices": (ys, xs),
            "point_count": int(ys.size),
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "centroid": [float(np.nanmean(lon[xs])), float(np.nanmean(lat[ys]))],
        })
    return features
