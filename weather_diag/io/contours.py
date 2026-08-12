from __future__ import annotations

from math import ceil, floor
from typing import Any, Iterable

import matplotlib
import numpy as np
from scipy import ndimage

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt


def _format_value(value: float, unit: str) -> str:
    text = f"{float(value):.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    if str(unit).strip() in {"0-1", "risk_score"}:
        return text
    return f"{text} {unit}" if unit else text


def _levels_from_interval(valid: np.ndarray, interval: float) -> list[float]:
    if interval <= 0:
        raise ValueError("contour interval must be positive")
    start = ceil(float(valid.min()) / interval) * interval
    end = floor(float(valid.max()) / interval) * interval
    levels: list[float] = []
    value = start
    while value <= end and len(levels) < 80:
        levels.append(float(round(value, 10)))
        value += interval
    return levels


def _normalize_levels(valid: np.ndarray, levels: Iterable[float] | None, interval: float | None) -> list[float]:
    if levels is not None:
        return sorted({float(level) for level in levels if np.isfinite(float(level))})
    if interval is not None:
        return _levels_from_interval(valid, float(interval))
    if valid.size == 0:
        return []
    if np.isclose(float(valid.min()), float(valid.max())):
        return [float(valid.min())]
    return [float(value) for value in np.linspace(float(valid.min()), float(valid.max()), 9)[1:-1]]


def _smooth_nan_grid(field: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return np.asarray(field, dtype=float)
    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return arr
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=float(sigma), mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=float(sigma), mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def _matplotlib_contour_segments(lon: np.ndarray, lat: np.ndarray, data: np.ndarray, levels: list[float]) -> list[tuple[float, list[list[float]]]]:
    if not levels:
        return []
    fig, ax = plt.subplots()
    try:
        contour_set = ax.contour(lon, lat, np.ma.masked_invalid(data), levels=levels)
        segments: list[tuple[float, list[list[float]]]] = []
        for level, level_segments in zip(contour_set.levels, contour_set.allsegs):
            for segment in level_segments:
                if len(segment) < 2:
                    continue
                coordinates = [[float(x), float(y)] for x, y in segment]
                segments.append((float(level), coordinates))
        return segments
    finally:
        plt.close(fig)


def _line_length_km(coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        mean_lat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * 111.32 * max(np.cos(np.deg2rad(mean_lat)), 0.2)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _chaikin(coords: list[list[float]], iterations: int = 1) -> list[list[float]]:
    out = [[float(x), float(y)] for x, y in coords]
    for _ in range(max(0, int(iterations))):
        if len(out) < 3:
            return out
        closed = np.allclose(out[0], out[-1], atol=1.0e-9, rtol=0.0)
        next_coords = [out[0]]
        pairs = list(zip(out[:-1], out[1:]))
        for p0, p1 in pairs:
            q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]
            r = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]
            next_coords.extend([q, r])
        if closed:
            next_coords[-1] = next_coords[0]
        else:
            next_coords.append(out[-1])
        out = next_coords
    return out


def _rdp(coords: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(coords) < 3 or tolerance <= 0:
        return coords
    arr = np.asarray(coords, dtype=float)
    start = arr[0]
    end = arr[-1]
    vec = end - start
    denom = float(np.dot(vec, vec))
    if denom <= 1.0e-12:
        distances = np.hypot(*(arr - start).T)
    else:
        t = np.clip(((arr - start) @ vec) / denom, 0.0, 1.0)
        proj = start + t[:, None] * vec
        distances = np.hypot(*(arr - proj).T)
    idx = int(np.nanargmax(distances))
    max_dist = float(distances[idx])
    if max_dist <= tolerance:
        return [coords[0], coords[-1]]
    return _rdp(coords[: idx + 1], tolerance)[:-1] + _rdp(coords[idx:], tolerance)


def _style_props(layer_id: str, unit: str, level: float) -> dict[str, Any]:
    layer = str(layer_id)
    if layer.startswith("z") or unit == "dagpm":
        return {"line_color": "#3155d4", "line_width": 1.6, "line_dash": [], "label_color": "#3155d4"}
    if layer.startswith("t") or unit in {"degC", "℃"}:
        return {
            "line_color": "#d9480f",
            "line_width": 1.4,
            "line_dash": [4, 3] if float(level) < 0 else [],
            "label_color": "#d9480f",
        }
    return {}


def contours_to_geojson(
    layer_id: str,
    title: str,
    unit: str,
    data: np.ndarray,
    *,
    lat: np.ndarray,
    lon: np.ndarray,
    levels: Iterable[float] | None = None,
    interval: float | None = None,
    max_segments: int = 12000,
    min_length_km: float = 0.0,
    smooth: bool = False,
    smooth_iterations: int = 1,
    data_smoothing_sigma: float = 0.0,
    simplify_tolerance_deg: float = 0.0,
) -> dict[str, Any]:
    arr = np.asarray(data, dtype=float)
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    if arr.shape != (lat_values.size, lon_values.size):
        raise ValueError("data shape must match lat/lon coordinate lengths")
    if lat_values.size < 2 or lon_values.size < 2:
        raise ValueError("contours require at least two latitudes and two longitudes")

    if data_smoothing_sigma > 0:
        arr = _smooth_nan_grid(arr, data_smoothing_sigma)

    valid = arr[np.isfinite(arr)]
    contour_levels = _normalize_levels(valid, levels, interval) if valid.size else []
    features: list[dict[str, Any]] = []
    for level, coordinates in _matplotlib_contour_segments(lon_values, lat_values, arr, contour_levels):
        length_km = _line_length_km(coordinates)
        if length_km < float(min_length_km):
            continue
        if smooth:
            coordinates = _chaikin(coordinates, iterations=smooth_iterations)
        if simplify_tolerance_deg > 0:
            coordinates = _rdp(coordinates, simplify_tolerance_deg)
        props = {
            "layer_id": layer_id,
            "title": title,
            "unit": unit,
            "value": float(level),
            "value_text": _format_value(float(level), unit),
            "feature_type": "contour",
            "length_km": round(float(length_km), 1),
            **_style_props(layer_id, unit, float(level)),
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": props,
        })
        if len(features) >= max_segments:
            break

    return {
        "type": "FeatureCollection",
        "properties": {
            "layer_id": layer_id,
            "title": title,
            "unit": unit,
            "levels": contour_levels,
            "min": float(valid.min()) if valid.size else None,
            "max": float(valid.max()) if valid.size else None,
            "count": len(features),
            "min_length_km": float(min_length_km),
            "smooth": bool(smooth),
            "smooth_iterations": int(smooth_iterations),
            "data_smoothing_sigma": float(data_smoothing_sigma),
            "simplify_tolerance_deg": float(simplify_tolerance_deg),
        },
        "features": features,
    }
