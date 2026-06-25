from __future__ import annotations

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

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


def _coordinate_edges(values: np.ndarray) -> np.ndarray:
    coords = np.asarray(values, dtype=float)
    if coords.ndim != 1:
        raise ValueError("lat/lon must be 1D arrays")
    if coords.size == 0:
        raise ValueError("coordinate array must not be empty")
    if coords.size == 1:
        return np.array([coords[0] - 0.05, coords[0] + 0.05], dtype=float)
    midpoints = (coords[:-1] + coords[1:]) / 2.0
    edges = np.empty(coords.size + 1, dtype=float)
    edges[1:-1] = midpoints
    edges[0] = coords[0] - (midpoints[0] - coords[0])
    edges[-1] = coords[-1] + (coords[-1] - midpoints[-1])
    return edges


def _jsonable_coordinates(value):
    if isinstance(value, tuple):
        return [_jsonable_coordinates(item) for item in value]
    if isinstance(value, list):
        return [_jsonable_coordinates(item) for item in value]
    if isinstance(value, float):
        return float(value)
    return value


def _component_polygon_geometry(ys: np.ndarray, xs: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> dict:
    lat_edges = _coordinate_edges(lat)
    lon_edges = _coordinate_edges(lon)
    cells = []
    for y, x in zip(ys, xs):
        lon_left, lon_right = lon_edges[int(x)], lon_edges[int(x) + 1]
        lat_bottom, lat_top = lat_edges[int(y)], lat_edges[int(y) + 1]
        cells.append(
            box(
                min(lon_left, lon_right),
                min(lat_bottom, lat_top),
                max(lon_left, lon_right),
                max(lat_bottom, lat_top),
            )
        )
    geom = unary_union(cells)
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        geom = geom.buffer(0)
    geojson = mapping(geom)
    return {
        "type": geojson["type"],
        "coordinates": _jsonable_coordinates(geojson["coordinates"]),
    }


def geometry_bounds(geometry: dict) -> list[float]:
    """Return [min_lon, min_lat, max_lon, max_lat] for a GeoJSON geometry."""
    try:
        geom = shape(geometry)
        if geom.is_empty:
            return [0.0, 0.0, 0.0, 0.0]
        minx, miny, maxx, maxy = geom.bounds
        return [float(minx), float(miny), float(maxx), float(maxy)]
    except Exception:
        coords = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
        xs: list[float] = []
        ys: list[float] = []

        def walk(value):
            if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
                xs.append(float(value[0]))
                ys.append(float(value[1]))
                return
            if isinstance(value, (list, tuple)):
                for child in value:
                    walk(child)

        walk(coords)
        if not xs or not ys:
            return [0.0, 0.0, 0.0, 0.0]
        return [float(np.nanmin(xs)), float(np.nanmin(ys)), float(np.nanmax(xs)), float(np.nanmax(ys))]


def _geometry_reference_lat(geometry: dict, fallback: float = 25.0) -> float:
    bbox = geometry_bounds(geometry)
    lat = (bbox[1] + bbox[3]) / 2.0
    if not np.isfinite(lat):
        return fallback
    return float(np.clip(lat, -75.0, 75.0))


def smooth_polygon_geometry(
    geometry: dict,
    *,
    reference_lat: float | None = None,
    smooth_km: float = 80.0,
    simplify_km: float = 25.0,
    min_area_ratio: float = 0.65,
) -> dict:
    """Smooth a grid-cell polygon boundary in local-km coordinates.

    Mask-derived polygons are naturally stair-stepped because each grid cell is
    unioned as a rectangle. For display systems such as the 500hPa subtropical
    high, this helper applies a conservative rounded buffer and topology-
    preserving simplification in a local equirectangular km plane, then converts
    the result back to lon/lat GeoJSON. The operation is intended for map
    visualization and keeps the original component statistics unchanged.
    """
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return geometry
    smooth_km = max(float(smooth_km or 0.0), 0.0)
    simplify_km = max(float(simplify_km or 0.0), 0.0)
    if smooth_km <= 0.0 and simplify_km <= 0.0:
        return geometry

    try:
        geom = shape(geometry)
        if geom.is_empty:
            return geometry
        ref_lat = _geometry_reference_lat(geometry) if reference_lat is None else float(reference_lat)
        x_scale = 111.32 * max(float(np.cos(np.deg2rad(ref_lat))), 0.2)
        y_scale = 111.32

        def to_km(x, y, z=None):
            return (np.asarray(x, dtype=float) * x_scale, np.asarray(y, dtype=float) * y_scale)

        def to_degree(x, y, z=None):
            return (np.asarray(x, dtype=float) / x_scale, np.asarray(y, dtype=float) / y_scale)

        projected = transform(to_km, geom)
        if projected.is_empty:
            return geometry

        candidate = projected
        if smooth_km > 0.0:
            # Round short grid-cell corners without intentionally changing the
            # synoptic-scale 5880-gpm envelope.
            candidate = candidate.buffer(smooth_km, join_style=1).buffer(-smooth_km, join_style=1)
        if simplify_km > 0.0:
            candidate = candidate.simplify(simplify_km, preserve_topology=True)
        candidate = candidate.buffer(0)

        original_area = max(float(projected.area), 1e-6)
        if candidate.is_empty or float(candidate.area) < original_area * float(min_area_ratio):
            candidate = projected.simplify(max(simplify_km, 1.0), preserve_topology=True).buffer(0)
        if candidate.is_empty:
            return geometry

        restored = transform(to_degree, candidate)
        geojson = mapping(restored)
        return {"type": geojson["type"], "coordinates": _jsonable_coordinates(geojson["coordinates"])}
    except Exception:
        return geometry


def mask_to_bbox_features(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray, *, min_points: int = 5):
    """Convert connected mask regions to shape-preserving polygon features.

    The function name is kept for compatibility with older callers. Returned
    metadata still includes a bbox, but geometry now follows the connected grid-cell
    footprint instead of using the bbox as the polygon itself.
    """
    from scipy import ndimage

    mask = np.asarray(mask).astype(bool)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    labels, count = ndimage.label(mask)
    features = []
    for label_id in range(1, count + 1):
        ys, xs = np.where(labels == label_id)
        if ys.size < min_points:
            continue
        geom = _component_polygon_geometry(ys, xs, lat, lon)
        if geom["type"] == "Polygon":
            xs_geom = [point[0] for ring in geom["coordinates"] for point in ring]
            ys_geom = [point[1] for ring in geom["coordinates"] for point in ring]
        else:
            xs_geom = [point[0] for polygon in geom["coordinates"] for ring in polygon for point in ring]
            ys_geom = [point[1] for polygon in geom["coordinates"] for ring in polygon for point in ring]
        lon_min, lon_max = float(np.nanmin(xs_geom)), float(np.nanmax(xs_geom))
        lat_min, lat_max = float(np.nanmin(ys_geom)), float(np.nanmax(ys_geom))
        features.append({
            "geometry": geom,
            "indices": (ys, xs),
            "point_count": int(ys.size),
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "centroid": [float(np.nanmean(lon[xs])), float(np.nanmean(lat[ys]))],
        })
    return features


def component_axis_line(item: dict, lat: np.ndarray, lon: np.ndarray, *, max_points: int = 48) -> dict:
    """Return a centerline following a connected component's dominant axis."""
    ys, xs = item["indices"]
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    coords = np.column_stack([lon[xs], lat[ys]]).astype(float)
    finite = np.isfinite(coords).all(axis=1)
    coords = coords[finite]
    if coords.shape[0] == 0:
        lon_min, lat_min, lon_max, lat_max = item["bbox"]
        lat_c = (lat_min + lat_max) / 2.0
        line = [[lon_min, lat_c], [lon_max, lat_c]]
        return {"type": "line", "coordinates": line, "bbox": item["bbox"]}
    if coords.shape[0] == 1:
        lon_c, lat_c = coords[0]
        line = [[float(lon_c - 0.05), float(lat_c)], [float(lon_c + 0.05), float(lat_c)]]
        return {"type": "line", "coordinates": line, "bbox": item["bbox"]}

    centered = coords - np.nanmean(coords, axis=0)
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        axis = vh[0]
    except np.linalg.LinAlgError:
        axis = np.array([1.0, 0.0])
    projection = centered @ axis

    projection_min = float(np.nanmin(projection))
    projection_max = float(np.nanmax(projection))
    if np.isclose(projection_min, projection_max):
        line_coords = coords[np.argsort(projection)]
    else:
        bin_count = min(max_points, max(4, int(np.ceil(np.sqrt(coords.shape[0]) * 2))))
        bins = np.linspace(projection_min, projection_max, bin_count + 1)
        line_parts = []
        for left, right in zip(bins[:-1], bins[1:]):
            if np.isclose(left, right):
                continue
            if right == bins[-1]:
                mask = (projection >= left) & (projection <= right)
            else:
                mask = (projection >= left) & (projection < right)
            if np.any(mask):
                line_parts.append(np.nanmean(coords[mask], axis=0))
        line_coords = np.asarray(line_parts, dtype=float)

    cleaned: list[list[float]] = []
    for lon_value, lat_value in line_coords:
        point = [float(lon_value), float(lat_value)]
        if cleaned and np.allclose(cleaned[-1], point):
            continue
        cleaned.append(point)

    if len(cleaned) < 2:
        lon_min, lat_min, lon_max, lat_max = item["bbox"]
        if abs(lon_max - lon_min) >= abs(lat_max - lat_min):
            lat_c = float(item["centroid"][1])
            cleaned = [[lon_min, lat_c], [lon_max, lat_c]]
        else:
            lon_c = float(item["centroid"][0])
            cleaned = [[lon_c, lat_min], [lon_c, lat_max]]

    lon_span = abs(item["bbox"][2] - item["bbox"][0])
    lat_span = abs(item["bbox"][3] - item["bbox"][1])
    if lon_span >= lat_span and cleaned[0][0] > cleaned[-1][0]:
        cleaned.reverse()
    elif lat_span > lon_span and cleaned[0][1] > cleaned[-1][1]:
        cleaned.reverse()

    return {"type": "line", "coordinates": cleaned, "bbox": item["bbox"]}
