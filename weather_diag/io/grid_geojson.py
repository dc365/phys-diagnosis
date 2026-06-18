from __future__ import annotations

from typing import Any

import numpy as np


def coordinate_edges(values: np.ndarray) -> np.ndarray:
    coords = np.asarray(values, dtype=float)
    if coords.ndim != 1 or coords.size == 0:
        raise ValueError("coordinate values must be a non-empty 1D array")
    if coords.size == 1:
        return np.array([coords[0] - 0.5, coords[0] + 0.5], dtype=float)

    mids = (coords[:-1] + coords[1:]) / 2.0
    first = coords[0] - (mids[0] - coords[0])
    last = coords[-1] + (coords[-1] - mids[-1])
    return np.concatenate([[first], mids, [last]]).astype(float)


def grid_to_geojson(
    layer_id: str,
    title: str,
    unit: str,
    data: np.ndarray,
    *,
    lat: np.ndarray,
    lon: np.ndarray,
    max_cells: int = 12000,
) -> dict[str, Any]:
    arr = np.asarray(data, dtype=float)
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    if arr.shape != (lat_values.size, lon_values.size):
        raise ValueError("data shape must match lat/lon coordinate lengths")

    total_cells = arr.size
    stride = max(1, int(np.ceil(np.sqrt(total_cells / max_cells)))) if max_cells > 0 else 1
    sampled = arr[::stride, ::stride]
    sampled_lat = lat_values[::stride]
    sampled_lon = lon_values[::stride]
    lat_edges = coordinate_edges(sampled_lat)
    lon_edges = coordinate_edges(sampled_lon)

    valid = sampled[np.isfinite(sampled)]
    features: list[dict[str, Any]] = []
    for i, row in enumerate(sampled):
        for j, value in enumerate(row):
            if not np.isfinite(value):
                continue
            west = float(min(lon_edges[j], lon_edges[j + 1]))
            east = float(max(lon_edges[j], lon_edges[j + 1]))
            south = float(min(lat_edges[i], lat_edges[i + 1]))
            north = float(max(lat_edges[i], lat_edges[i + 1]))
            numeric_value = float(value)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]],
                },
                "properties": {
                    "layer_id": layer_id,
                    "title": title,
                    "unit": unit,
                    "value": numeric_value,
                    "value_text": f"{numeric_value:.2f}",
                    "row": int(i * stride),
                    "col": int(j * stride),
                },
            })

    return {
        "type": "FeatureCollection",
        "properties": {
            "layer_id": layer_id,
            "title": title,
            "unit": unit,
            "min": float(valid.min()) if valid.size else None,
            "max": float(valid.max()) if valid.size else None,
            "count": len(features),
            "stride": stride,
        },
        "features": features,
    }
