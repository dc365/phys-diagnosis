from __future__ import annotations

import numpy as np
from scipy import interpolate

from weather_diag.diagnostics.grid import component_axis_line, mask_to_bbox_features


def direction_coherence(
    u: np.ndarray | None,
    v: np.ndarray | None,
    ys: np.ndarray,
    xs: np.ndarray,
) -> float | None:
    if u is None or v is None:
        return None
    u_values = np.asarray(u, dtype=float)[ys, xs]
    v_values = np.asarray(v, dtype=float)[ys, xs]
    speed = np.hypot(u_values, v_values)
    valid = np.isfinite(speed) & (speed > 1e-6)
    if not np.any(valid):
        return 0.0
    unit_u = u_values[valid] / speed[valid]
    unit_v = v_values[valid] / speed[valid]
    return float(np.hypot(np.nanmean(unit_u), np.nanmean(unit_v)))


def _lon_km_per_degree(lat_value: float) -> float:
    return 111.32 * max(np.cos(np.deg2rad(float(lat_value))), 0.2)


def axis_length_degrees(coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    return float(
        np.sum(
            np.hypot(
                np.diff([coord[0] for coord in coords]),
                np.diff([coord[1] for coord in coords]),
            )
        )
    )


def axis_length_km(coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        mean_lat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * _lon_km_per_degree(mean_lat)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _clean_line(coords: list[list[float]]) -> list[list[float]]:
    cleaned: list[list[float]] = []
    for lon_value, lat_value in coords:
        if not np.isfinite([lon_value, lat_value]).all():
            continue
        point = [float(lon_value), float(lat_value)]
        if cleaned and np.allclose(cleaned[-1], point, atol=1e-7):
            continue
        cleaned.append(point)
    return cleaned


def _line_bbox(coords: list[list[float]]) -> list[float]:
    arr = np.asarray(coords, dtype=float)
    return [
        float(np.nanmin(arr[:, 0])),
        float(np.nanmin(arr[:, 1])),
        float(np.nanmax(arr[:, 0])),
        float(np.nanmax(arr[:, 1])),
    ]


def _smooth_line(coords: list[list[float]], count: int = 40, smooth_factor: float = 0.15) -> list[list[float]]:
    coords = _clean_line(coords)
    if len(coords) < 3:
        return coords
    arr = np.asarray(coords, dtype=float)
    seg = np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1]))
    if not np.isfinite(seg).any() or float(np.nansum(seg)) <= 1e-8:
        return coords
    count = max(2, min(count, max(8, len(coords) * 3)))
    try:
        median_step = float(np.nanmedian(seg))
        spline, _ = interpolate.splprep(
            [arr[:, 0], arr[:, 1]],
            s=float(smooth_factor * len(coords) * median_step**2),
            k=min(3, len(coords) - 1),
        )
        out = interpolate.splev(np.linspace(0.0, 1.0, count), spline)
        return _clean_line(np.column_stack(out).tolist())
    except (ValueError, TypeError, RuntimeError):
        distance = np.concatenate([[0.0], np.cumsum(seg)])
        target = np.linspace(0.0, float(distance[-1]), count)
        out = np.column_stack([
            np.interp(target, distance, arr[:, 0]),
            np.interp(target, distance, arr[:, 1]),
        ])
        return _clean_line(out.tolist())


def _trace_one_direction(
    seed_y: int,
    seed_x: int,
    mask: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    *,
    sign: float,
    max_steps: int,
) -> list[tuple[int, int]]:
    y = float(seed_y)
    x = float(seed_x)
    path: list[tuple[int, int]] = []
    visited: set[tuple[int, int]] = set()
    dy_grid = float(np.nanmedian(np.abs(np.diff(lat)))) if len(lat) > 1 else 1.0
    dx_grid = float(np.nanmedian(np.abs(np.diff(lon)))) if len(lon) > 1 else 1.0
    for _ in range(max_steps):
        iy = int(round(y))
        ix = int(round(x))
        if iy < 0 or iy >= mask.shape[0] or ix < 0 or ix >= mask.shape[1] or not mask[iy, ix]:
            break
        if (iy, ix) in visited:
            break
        visited.add((iy, ix))
        path.append((iy, ix))
        uu = float(u[iy, ix])
        vv = float(v[iy, ix])
        speed = float(np.hypot(uu, vv))
        if not np.isfinite(speed) or speed <= 1.0e-6:
            break
        km_per_lon = _lon_km_per_degree(float(lat[iy]))
        # Convert physical vector to fractional grid-index vector, then normalize to one grid step.
        dx = (uu / km_per_lon) / max(dx_grid, 1.0e-6)
        dy = (vv / 111.32) / max(dy_grid, 1.0e-6)
        norm = float(np.hypot(dx, dy))
        if not np.isfinite(norm) or norm <= 1.0e-9:
            break
        x += sign * dx / norm
        y += sign * dy / norm
    return path


def _stream_axis_line(
    item: dict,
    lat,
    lon,
    value_field: np.ndarray,
    u: np.ndarray | None,
    v: np.ndarray | None,
    *,
    min_points: int,
) -> dict | None:
    if u is None or v is None:
        return None
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    ys, xs = item["indices"]
    if ys.size < max(2, min_points):
        return None
    mask = np.zeros_like(np.asarray(value_field, dtype=float), dtype=bool)
    mask[ys, xs] = True
    values = np.asarray(value_field, dtype=float)[ys, xs]
    if not np.isfinite(values).any():
        return None
    seed_i = int(np.nanargmax(values))
    seed_y = int(ys[seed_i])
    seed_x = int(xs[seed_i])
    max_steps = int(max(12, min(mask.size, ys.size * 2)))
    backward = _trace_one_direction(seed_y, seed_x, mask, lat_arr, lon_arr, np.asarray(u, dtype=float), np.asarray(v, dtype=float), sign=-1.0, max_steps=max_steps)
    forward = _trace_one_direction(seed_y, seed_x, mask, lat_arr, lon_arr, np.asarray(u, dtype=float), np.asarray(v, dtype=float), sign=1.0, max_steps=max_steps)
    nodes = list(reversed(backward[1:])) + forward
    if len(nodes) < max(3, min_points // 3):
        return None
    coords = [[float(lon_arr[x]), float(lat_arr[y])] for y, x in nodes]
    coords = _smooth_line(coords, count=min(64, max(16, len(coords) * 3)), smooth_factor=0.10)
    if len(coords) < 2:
        return None
    return {"type": "line", "coordinates": coords, "bbox": _line_bbox(coords), "method": "streamline_axis"}


def ranked_transport_components(
    mask: np.ndarray,
    lat,
    lon,
    value_field: np.ndarray,
    *,
    min_points: int,
    max_objects: int,
    u: np.ndarray | None = None,
    v: np.ndarray | None = None,
    min_direction_coherence: float = 0.0,
) -> list[dict]:
    components = []
    for item in mask_to_bbox_features(mask, lat, lon, min_points=min_points):
        ys, xs = item["indices"]
        coherence = direction_coherence(u, v, ys, xs)
        if coherence is not None and coherence < min_direction_coherence:
            continue
        line = _stream_axis_line(item, lat, lon, value_field, u, v, min_points=min_points)
        if line is None:
            line = component_axis_line(item, lat, lon)
            line["method"] = "component_pca_axis"
        values = np.asarray(value_field, dtype=float)[ys, xs]
        coords = line["coordinates"]
        components.append(
            {
                "item": item,
                "line": line,
                "direction_coherence": coherence,
                "axis_length": axis_length_degrees(coords),
                "axis_length_km": axis_length_km(coords),
                "axis_method": line.get("method", "component_axis"),
                "max_value": float(np.nanmax(values)),
                "mean_value": float(np.nanmean(values)),
                "point_count": int(item["point_count"]),
            }
        )

    components.sort(
        key=lambda component: (
            component["axis_length_km"],
            component["mean_value"],
            component["max_value"],
            component["point_count"],
        ),
        reverse=True,
    )
    if max_objects > 0:
        components = components[:max_objects]
    for rank, component in enumerate(components, start=1):
        component["rank"] = rank
    return components
