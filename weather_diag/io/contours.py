from __future__ import annotations

from math import ceil, floor
from typing import Any, Iterable

import numpy as np


EDGE_PAIRS = {
    0: (0, 1),
    1: (1, 2),
    2: (3, 2),
    3: (0, 3),
}

CASE_SEGMENTS = {
    0: (),
    1: ((3, 0),),
    2: ((0, 1),),
    3: ((3, 1),),
    4: ((1, 2),),
    5: ((3, 2), (0, 1)),
    6: ((0, 2),),
    7: ((3, 2),),
    8: ((2, 3),),
    9: ((0, 2),),
    10: ((0, 3), (1, 2)),
    11: ((1, 2),),
    12: ((1, 3),),
    13: ((0, 1),),
    14: ((3, 0),),
    15: (),
}


def _format_value(value: float, unit: str) -> str:
    text = f"{float(value):.2f}"
    return f"{text} {unit}" if unit else text


def _levels_from_interval(valid: np.ndarray, interval: float) -> list[float]:
    if interval <= 0:
        raise ValueError("contour interval must be positive")
    start = ceil(float(valid.min()) / interval) * interval
    end = floor(float(valid.max()) / interval) * interval
    levels: list[float] = []
    value = start
    # Keep dynamic contour generation bounded for map interactivity.
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


def _edge_point(edge: int, corners: list[tuple[float, float]], values: list[float], level: float) -> list[float] | None:
    left, right = EDGE_PAIRS[edge]
    v1 = values[left]
    v2 = values[right]
    if not np.isfinite(v1) or not np.isfinite(v2) or np.isclose(v1, v2):
        return None
    if not ((v1 < level <= v2) or (v2 < level <= v1)):
        return None
    ratio = (level - v1) / (v2 - v1)
    lon1, lat1 = corners[left]
    lon2, lat2 = corners[right]
    return [
        float(lon1 + ratio * (lon2 - lon1)),
        float(lat1 + ratio * (lat2 - lat1)),
    ]


def _cell_segments(corners: list[tuple[float, float]], values: list[float], level: float) -> list[list[list[float]]]:
    if any(not np.isfinite(value) for value in values):
        return []
    case = 0
    for index, value in enumerate(values):
        if value >= level:
            case |= 1 << index
    segments: list[list[list[float]]] = []
    for edge_a, edge_b in CASE_SEGMENTS[case]:
        point_a = _edge_point(edge_a, corners, values, level)
        point_b = _edge_point(edge_b, corners, values, level)
        if point_a is None or point_b is None or np.allclose(point_a, point_b):
            continue
        segments.append([point_a, point_b])
    return segments


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
) -> dict[str, Any]:
    arr = np.asarray(data, dtype=float)
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    if arr.shape != (lat_values.size, lon_values.size):
        raise ValueError("data shape must match lat/lon coordinate lengths")
    if lat_values.size < 2 or lon_values.size < 2:
        raise ValueError("contours require at least two latitudes and two longitudes")

    valid = arr[np.isfinite(arr)]
    contour_levels = _normalize_levels(valid, levels, interval) if valid.size else []
    features: list[dict[str, Any]] = []
    for level in contour_levels:
        for i in range(lat_values.size - 1):
            for j in range(lon_values.size - 1):
                corners = [
                    (float(lon_values[j]), float(lat_values[i])),
                    (float(lon_values[j + 1]), float(lat_values[i])),
                    (float(lon_values[j + 1]), float(lat_values[i + 1])),
                    (float(lon_values[j]), float(lat_values[i + 1])),
                ]
                values = [
                    float(arr[i, j]),
                    float(arr[i, j + 1]),
                    float(arr[i + 1, j + 1]),
                    float(arr[i + 1, j]),
                ]
                for segment in _cell_segments(corners, values, float(level)):
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": segment,
                        },
                        "properties": {
                            "layer_id": layer_id,
                            "title": title,
                            "unit": unit,
                            "value": float(level),
                            "value_text": _format_value(float(level), unit),
                            "feature_type": "contour",
                        },
                    })
                    if len(features) >= max_segments:
                        break
                if len(features) >= max_segments:
                    break
            if len(features) >= max_segments:
                break
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
        },
        "features": features,
    }
