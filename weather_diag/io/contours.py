from __future__ import annotations

from math import ceil, floor
from typing import Any, Iterable

import matplotlib
import numpy as np

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


def _matplotlib_contour_segments(
    lon: np.ndarray,
    lat: np.ndarray,
    data: np.ndarray,
    levels: list[float],
) -> list[tuple[float, list[list[float]]]]:
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
    for level, coordinates in _matplotlib_contour_segments(lon_values, lat_values, arr, contour_levels):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
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
