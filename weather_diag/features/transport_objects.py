from __future__ import annotations

import numpy as np

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
        line = component_axis_line(item, lat, lon)
        values = np.asarray(value_field, dtype=float)[ys, xs]
        components.append(
            {
                "item": item,
                "line": line,
                "direction_coherence": coherence,
                "axis_length": axis_length_degrees(line["coordinates"]),
                "max_value": float(np.nanmax(values)),
                "mean_value": float(np.nanmean(values)),
                "point_count": int(item["point_count"]),
            }
        )

    components.sort(
        key=lambda component: (
            component["point_count"],
            component["mean_value"],
            component["max_value"],
            component["axis_length"],
        ),
        reverse=True,
    )
    if max_objects > 0:
        components = components[:max_objects]
    for rank, component in enumerate(components, start=1):
        component["rank"] = rank
    return components
