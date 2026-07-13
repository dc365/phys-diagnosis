from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from scipy import ndimage

from weather_diag.features.trough_ridge import (
    _haversine_length_km,
    _lonlat_to_xy_km,
    _polyline_mean_distance_km,
    _remove_lonlat_close_points,
    _smooth_xy_spline,
    _xy_km_to_lonlat,
)


@dataclass(frozen=True)
class SoundingPathConfig:
    """Station-only H500 path extraction settings.

    The values are deliberately synoptic-scale.  They are not geographic line
    coordinates and do not prescribe where a trough must exist; they only bound
    the operational analysis domain and continuity of automatically detected
    paths.
    """

    analysis_lon_min: float = 60.0
    analysis_lon_max: float = 150.0
    analysis_lat_min: float = 15.0
    analysis_lat_max: float = 55.0

    trough_lon_min: float = 75.0
    trough_lon_max: float = 140.0
    trough_lat_min: float = 28.0
    trough_lat_max: float = 55.0
    trough_max_paths: int = 5
    trough_output_points: int = 28
    trough_min_length_km: float = 330.0
    trough_min_lat_span_deg: float = 3.0
    trough_duplicate_distance_km: float = 175.0

    closed_low_lon_min: float = 100.0
    closed_low_lon_max: float = 134.0
    closed_low_lat_min: float = 34.0
    closed_low_lat_max: float = 50.0
    closed_low_max_centers: int = 1
    closed_low_branch_max_rows: int = 15

    south_china_lon_min: float = 104.0
    south_china_lon_max: float = 115.0
    south_china_lat_min: float = 13.0
    south_china_lat_max: float = 30.0
    shear_output_points: int = 24
    shear_min_length_km: float = 500.0
    shear_min_lat_span_deg: float = 6.0


@dataclass
class _Path:
    coordinates: np.ndarray
    score: float
    candidate_source: str
    metrics: dict[str, float]
    center: tuple[float, float] | None = None


def _nan_gaussian(field: np.ndarray, sigma_yx: tuple[float, float]) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.full_like(arr, np.nan, dtype=float)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma_yx, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma_yx, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def _normalise(
    values: np.ndarray,
    mask: np.ndarray,
    *,
    lower_percentile: float,
    upper_percentile: float,
) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    sample = arr[np.asarray(mask, dtype=bool) & np.isfinite(arr)]
    if sample.size < 8:
        return np.zeros_like(arr, dtype=float)
    lower, upper = np.nanpercentile(sample, [lower_percentile, upper_percentile])
    if not np.isfinite(upper - lower) or upper - lower <= 1.0e-12:
        # Sparse fields such as row-wise valley depth contain mostly exact zeros.
        # In that case an all-sample percentile can collapse to 0/0 even though
        # coherent positive minima exist.  Scale against the lower tail of the
        # positive population so weak but continuous trough shoulders remain
        # available to the path tracker.
        positive = sample[sample > max(float(lower), 0.0) + 1.0e-12]
        if positive.size < 3:
            return np.zeros_like(arr, dtype=float)
        lower = 0.0
        upper = float(np.nanpercentile(positive, 15.0))
        if not np.isfinite(upper) or upper <= 1.0e-12:
            return np.zeros_like(arr, dtype=float)
    return np.clip((arr - lower) / (upper - lower), 0.0, 2.0)


def _prepare_fields(
    z500: np.ndarray,
    u500: np.ndarray,
    v500: np.ndarray,
    lat: Iterable[float],
    lon: Iterable[float],
    support_distance_km: np.ndarray | None,
    support_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lat_arr = np.asarray(list(lat), dtype=float)
    lon_arr = np.asarray(list(lon), dtype=float)
    z = np.asarray(z500, dtype=float)
    u = np.asarray(u500, dtype=float)
    v = np.asarray(v500, dtype=float)
    expected = (lat_arr.size, lon_arr.size)
    if z.shape != expected or u.shape != expected or v.shape != expected:
        raise ValueError("z500/u500/v500 must match the lat/lon grid")

    if support_distance_km is None:
        support = np.zeros(expected, dtype=float)
    else:
        support = np.asarray(support_distance_km, dtype=float)
        if support.shape != expected:
            raise ValueError("support_distance_km must match the height grid")

    if support_mask is None:
        valid_support = np.isfinite(z)
    else:
        valid_support = np.asarray(support_mask, dtype=bool)
        if valid_support.shape != expected:
            raise ValueError("support_mask must match the height grid")

    if lat_arr.size > 1 and lat_arr[0] > lat_arr[-1]:
        lat_arr = lat_arr[::-1]
        z, u, v, support, valid_support = (
            value[::-1, :] for value in (z, u, v, support, valid_support)
        )
    if lon_arr.size > 1 and lon_arr[0] > lon_arr[-1]:
        lon_arr = lon_arr[::-1]
        z, u, v, support, valid_support = (
            value[:, ::-1] for value in (z, u, v, support, valid_support)
        )
    return z, u, v, lat_arr, lon_arr, support, valid_support


def _dynamic_fields(
    z: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
) -> dict[str, np.ndarray]:
    u_smooth = _nan_gaussian(u, (0.9, 0.9))
    v_smooth = _nan_gaussian(v, (0.9, 0.9))
    cos_lat = np.maximum(np.cos(np.deg2rad(lat))[:, None], 0.20)
    dx = 111_320.0 * cos_lat
    dy = 111_320.0
    dudx = np.gradient(u_smooth, lon, axis=1, edge_order=1) / dx
    dvdx = np.gradient(v_smooth, lon, axis=1, edge_order=1) / dx
    dudy = np.gradient(u_smooth, lat, axis=0, edge_order=1) / dy
    dvdy = np.gradient(v_smooth, lat, axis=0, edge_order=1) / dy
    vorticity = dvdx - dudy
    convergence = -(dudx + dvdy)
    deformation = np.hypot(dudx - dvdy, dvdx + dudy)

    speed = np.hypot(u_smooth, v_smooth)
    unit_u = u_smooth / np.maximum(speed, 0.5)
    unit_v = v_smooth / np.maximum(speed, 0.5)
    direction_gradient = (
        np.hypot(
            np.gradient(unit_u, axis=1, edge_order=1),
            np.gradient(unit_v, axis=1, edge_order=1),
        )
        + 0.5
        * np.hypot(
            np.gradient(unit_u, axis=0, edge_order=1),
            np.gradient(unit_v, axis=0, edge_order=1),
        )
    )
    return {
        "vorticity": vorticity,
        "convergence": convergence,
        "deformation": deformation,
        "direction_gradient": direction_gradient,
    }


def _support_weight(distance_km: np.ndarray, mask: np.ndarray) -> np.ndarray:
    distance = np.asarray(distance_km, dtype=float)
    finite = np.isfinite(distance)
    if not finite.any() or float(np.nanmax(np.abs(distance[finite]))) <= 1.0e-9:
        weight = np.ones_like(distance, dtype=float)
    else:
        weight = np.clip((850.0 - distance) / 650.0, 0.0, 1.0)
    return np.where(mask, weight, 0.0)


def _height_score_fields(
    z: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    support_distance_km: np.ndarray,
    support_mask: np.ndarray,
    cfg: SoundingPathConfig,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    smooth = _nan_gaussian(z, (1.0, 1.0))
    background = _nan_gaussian(z, (4.0, 6.0))
    negative_anomaly = np.maximum(background - smooth, 0.0)

    # A roughly 550 km zonal shoulder on a 1-degree sounding grid captures
    # synoptic trough depth without collapsing to a single station increment.
    grid_step_deg = max(float(np.nanmedian(np.abs(np.diff(lon)))), 0.25)
    radius = max(3, min(7, int(round(5.0 / grid_step_deg))))
    depth = np.zeros_like(smooth, dtype=float)
    for x_index in range(radius, lon.size - radius):
        left = np.nanmean(smooth[:, x_index - radius : x_index], axis=1)
        right = np.nanmean(smooth[:, x_index + 1 : x_index + radius + 1], axis=1)
        depth[:, x_index] = np.maximum(np.minimum(left, right) - smooth[:, x_index], 0.0)

    first_derivative = np.gradient(smooth, lon, axis=1, edge_order=1)
    curvature = np.maximum(
        np.gradient(first_derivative, lon, axis=1, edge_order=1),
        0.0,
    )
    dynamics = _dynamic_fields(smooth, u, v, lat, lon)

    domain = (
        (lat[:, None] >= cfg.trough_lat_min)
        & (lat[:, None] <= cfg.trough_lat_max)
        & (lon[None, :] >= cfg.trough_lon_min)
        & (lon[None, :] <= cfg.trough_lon_max)
        & support_mask
        & np.isfinite(smooth)
    )
    depth_n = _normalise(depth, domain, lower_percentile=45.0, upper_percentile=90.0)
    curvature_n = _normalise(curvature, domain, lower_percentile=50.0, upper_percentile=92.0)
    anomaly_n = _normalise(negative_anomaly, domain, lower_percentile=55.0, upper_percentile=94.0)
    vorticity_n = _normalise(
        np.maximum(dynamics["vorticity"], 0.0),
        domain,
        lower_percentile=55.0,
        upper_percentile=94.0,
    )
    deformation_n = _normalise(
        dynamics["deformation"],
        domain,
        lower_percentile=55.0,
        upper_percentile=94.0,
    )
    support = _support_weight(support_distance_km, support_mask)

    height_evidence = 0.42 * depth_n + 0.25 * curvature_n + 0.33 * anomaly_n
    dynamic_evidence = 0.72 * vorticity_n + 0.28 * deformation_n
    score = (0.72 * height_evidence + 0.28 * dynamic_evidence) * (0.55 + 0.45 * support)
    score = np.where(domain, score, 0.0)
    return score, {
        "z": smooth,
        "depth": depth,
        "depth_n": depth_n,
        "curvature_n": curvature_n,
        "anomaly_n": anomaly_n,
        "vorticity_n": vorticity_n,
        "deformation_n": deformation_n,
        "height_evidence": height_evidence,
        "dynamic_evidence": dynamic_evidence,
        "support": support,
        **dynamics,
    }


def _smooth_coordinates(coordinates: np.ndarray, output_points: int) -> np.ndarray:
    coords = np.asarray(coordinates, dtype=float)
    finite = np.isfinite(coords).all(axis=1)
    coords = coords[finite]
    if coords.shape[0] < 2:
        return coords
    lat0 = float(np.nanmedian(coords[:, 1]))
    xy = _lonlat_to_xy_km(coords[:, 0], coords[:, 1], lat0)
    smoothed_xy = _smooth_xy_spline(
        xy,
        count=max(int(output_points), coords.shape[0]),
        smooth_factor=0.55,
    )
    smoothed = _xy_km_to_lonlat(smoothed_xy, lat0)
    smoothed[:, 0] = np.clip(
        smoothed[:, 0],
        float(np.nanmin(coords[:, 0]) - 0.7),
        float(np.nanmax(coords[:, 0]) + 0.7),
    )
    smoothed[:, 1] = np.clip(
        smoothed[:, 1],
        float(np.nanmin(coords[:, 1])),
        float(np.nanmax(coords[:, 1])),
    )
    return _remove_lonlat_close_points(smoothed, min_step_km=30.0)


def _line_grid_values(
    coordinates: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    field: np.ndarray,
) -> np.ndarray:
    if coordinates.shape[0] == 0:
        return np.array([], dtype=float)
    y_index = np.abs(lat[:, None] - coordinates[:, 1][None, :]).argmin(axis=0)
    x_index = np.abs(lon[:, None] - coordinates[:, 0][None, :]).argmin(axis=0)
    return np.asarray(field, dtype=float)[y_index, x_index]


def _line_support_metrics(
    coordinates: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    support_distance_km: np.ndarray,
) -> tuple[float | None, float | None]:
    values = _line_grid_values(coordinates, lat, lon, support_distance_km)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None, None
    return float(np.nanmean(values)), float(np.nanpercentile(values, 90))


def _closed_low_branches(
    score: np.ndarray,
    fields: dict[str, np.ndarray],
    lat: np.ndarray,
    lon: np.ndarray,
    cfg: SoundingPathConfig,
) -> list[_Path]:
    center_score = 0.55 * fields["anomaly_n"] + 0.45 * fields["vorticity_n"]
    domain = (
        (lat[:, None] >= cfg.closed_low_lat_min)
        & (lat[:, None] <= cfg.closed_low_lat_max)
        & (lon[None, :] >= cfg.closed_low_lon_min)
        & (lon[None, :] <= cfg.closed_low_lon_max)
        & (fields["support"] > 0.18)
    )
    local = center_score == ndimage.maximum_filter(center_score, size=(5, 7), mode="nearest")
    candidates = center_score[domain & np.isfinite(center_score)]
    if candidates.size == 0:
        return []
    threshold = max(0.82, float(np.nanpercentile(candidates, 82.0)))
    ys, xs = np.where(local & domain & (center_score >= threshold))
    order = np.argsort(center_score[ys, xs])[::-1]

    centers: list[tuple[int, int]] = []
    for item in order:
        y_index, x_index = int(ys[item]), int(xs[item])
        point = np.asarray([[lon[x_index], lat[y_index]]], dtype=float)
        if any(
            _polyline_mean_distance_km(
                point,
                np.asarray([[lon[old_x], lat[old_y]]], dtype=float),
            )
            < 700.0
            for old_y, old_x in centers
        ):
            continue
        centers.append((y_index, x_index))
        if len(centers) >= cfg.closed_low_max_centers:
            break

    def trace(start_y: int, start_x: int, direction: int) -> list[tuple[int, int]]:
        output = [(start_y, start_x)]
        current_x = start_x
        previous_x: int | None = None
        weak_rows = 0
        for step in range(1, cfg.closed_low_branch_max_rows + 1):
            y_index = start_y + direction * step
            if y_index < 0 or y_index >= lat.size or not cfg.trough_lat_min <= lat[y_index] <= cfg.trough_lat_max:
                break
            candidate_x = np.where(
                (lon >= lon[current_x] - 3.5)
                & (lon <= lon[current_x] + 3.5)
                & (lon >= cfg.trough_lon_min)
                & (lon <= cfg.trough_lon_max)
            )[0]
            best: tuple[float, int, float] | None = None
            for x_index in candidate_x:
                local_score = float(score[y_index, x_index])
                jump = abs(float(lon[x_index] - lon[current_x]))
                curvature_penalty = 0.0
                if previous_x is not None:
                    predicted = float(2.0 * lon[current_x] - lon[previous_x])
                    curvature_penalty = abs(float(lon[x_index] - predicted))
                east_jump = max(0.0, float(lon[x_index] - lon[current_x]) - (1.0 if direction > 0 else 1.5))
                value = local_score - 0.08 * jump**2 - 0.05 * curvature_penalty**2 - 0.08 * east_jump**2
                if best is None or value > best[0]:
                    best = (value, int(x_index), local_score)
            if best is None:
                break
            _, x_index, local_score = best
            weak_rows = weak_rows + 1 if local_score < 0.20 else 0
            if weak_rows >= 3:
                break
            previous_x, current_x = current_x, x_index
            output.append((y_index, current_x))
        return output

    paths: list[_Path] = []
    for center_y, center_x in centers:
        center_lon = float(lon[center_x])
        center_lat = float(lat[center_y])
        for source, direction in [
            ("closed_low_south_branch", -1),
            ("closed_low_north_branch", 1),
        ]:
            # A high-latitude centre is usually itself the northern end of a
            # single trough.  Emitting a second north branch there created a
            # false Russia-border line in the 24 June cycles.  Lower-latitude
            # closed lows retain both branches, which is required for the
            # separate Northeast/Far-East axes on 25 June.
            if source == "closed_low_north_branch" and center_lat > 43.0:
                continue
            indices = trace(center_y, center_x, direction)
            if direction < 0:
                indices = list(reversed(indices))
            if len(indices) < 4:
                continue
            coordinates = np.asarray([[lon[x], lat[y]] for y, x in indices], dtype=float)
            if float(np.ptp(coordinates[:, 1])) < cfg.trough_min_lat_span_deg:
                continue
            coordinates = _smooth_coordinates(coordinates, cfg.trough_output_points)
            if coordinates.shape[0] < 2 or _haversine_length_km(coordinates) < cfg.trough_min_length_km:
                continue
            line_score = _line_grid_values(coordinates, lat, lon, score)
            paths.append(
                _Path(
                    coordinates=coordinates,
                    score=float(np.nanmean(line_score)) if line_score.size else 0.0,
                    candidate_source=source,
                    center=(center_lon, center_lat),
                    metrics={
                        "height_evidence_mean": float(
                            np.nanmean(_line_grid_values(coordinates, lat, lon, fields["height_evidence"]))
                        ),
                        "dynamic_evidence_mean": float(
                            np.nanmean(_line_grid_values(coordinates, lat, lon, fields["dynamic_evidence"]))
                        ),
                        "center_score": float(center_score[center_y, center_x]),
                    },
                )
            )
    return paths


def _path_distance(first: _Path, second: _Path) -> float:
    return 0.5 * (
        _polyline_mean_distance_km(first.coordinates, second.coordinates)
        + _polyline_mean_distance_km(second.coordinates, first.coordinates)
    )


def _dynamic_height_paths(
    score: np.ndarray,
    fields: dict[str, np.ndarray],
    lat: np.ndarray,
    lon: np.ndarray,
    cfg: SoundingPathConfig,
) -> list[_Path]:
    y_values = np.where((lat >= cfg.trough_lat_min) & (lat <= cfg.trough_lat_max))[0]
    # Scores are quantile-normalised independently for every cycle, therefore a
    # stable normalized threshold is more robust than re-taking a percentile of
    # the already normalized field.  A second, lower threshold is used only when
    # splitting a path so shallow but coherent portions are not discarded.
    node_threshold = 0.28
    weak_threshold = 0.30
    reward_floor = 0.34

    nodes: list[dict[str, Any]] = []
    nodes_by_y: dict[int, list[int]] = {}
    for y_index in y_values:
        row = score[y_index]
        evidence = (
            (fields["depth_n"][y_index] > 0.10)
            | (fields["vorticity_n"][y_index] > 0.22)
            | (fields["anomaly_n"][y_index] > 0.22)
        )
        local = row == ndimage.maximum_filter1d(row, size=5, mode="nearest")
        x_values = np.where(
            local
            & evidence
            & (row >= node_threshold)
            & (lon >= cfg.trough_lon_min)
            & (lon <= cfg.trough_lon_max)
        )[0]
        if x_values.size:
            x_values = x_values[np.argsort(row[x_values])[::-1][:7]]
        for x_index in x_values:
            index = len(nodes)
            nodes.append(
                {
                    "y": int(y_index),
                    "x": int(x_index),
                    "score": float(row[x_index]),
                    "dp": float(row[x_index] - reward_floor),
                    "previous": None,
                    "length": 1,
                }
            )
            nodes_by_y.setdefault(int(y_index), []).append(index)

    for y_index in y_values:
        for node_index in nodes_by_y.get(int(y_index), []):
            node = nodes[node_index]
            for gap in (1, 2):
                for previous_index in nodes_by_y.get(int(y_index - gap), []):
                    previous = nodes[previous_index]
                    delta_lon = abs(float(lon[node["x"]] - lon[previous["x"]]))
                    if delta_lon > 3.2 * gap:
                        continue
                    previous_slope = 0.0
                    if previous["previous"] is not None:
                        older = nodes[previous["previous"]]
                        previous_slope = float(lon[previous["x"]] - lon[older["x"]]) / max(
                            previous["y"] - older["y"],
                            1,
                        )
                    slope = float(lon[node["x"]] - lon[previous["x"]]) / gap
                    candidate = (
                        previous["dp"]
                        + (node["score"] - reward_floor)
                        - 0.10 * (delta_lon / max(3.2 * gap, 0.1)) ** 2
                        - 0.05 * (slope - previous_slope) ** 2
                        - 0.10 * (gap - 1)
                    )
                    if candidate > node["dp"]:
                        node["dp"] = candidate
                        node["previous"] = previous_index
                        node["length"] = previous["length"] + 1

    raw_paths: list[_Path] = []
    for index, node in enumerate(nodes):
        if node["length"] < 4:
            continue
        chain: list[dict[str, Any]] = []
        cursor: int | None = index
        seen: set[int] = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            item = nodes[cursor]
            chain.append(item)
            cursor = item["previous"]
        chain.reverse()

        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        weak = 0
        for item in chain:
            if current and (
                item["y"] - current[-1]["y"] > 1
                or abs(float(lon[item["x"]] - lon[current[-1]["x"]])) > 3.8
            ):
                segments.append(current)
                current = []
                weak = 0
            weak = weak + 1 if item["score"] < weak_threshold else 0
            if weak >= 2 and current:
                segments.append(current[:-1])
                current = []
                weak = 0
            current.append(item)
        if current:
            segments.append(current)

        for segment in segments:
            if len(segment) < 4:
                continue
            y_index = np.asarray([item["y"] for item in segment], dtype=int)
            x_index = np.asarray([item["x"] for item in segment], dtype=int)
            coordinates = np.asarray([[lon[x], lat[y]] for y, x in zip(y_index, x_index)], dtype=float)
            if float(np.ptp(coordinates[:, 1])) < cfg.trough_min_lat_span_deg:
                continue
            metrics = {
                "height_evidence_mean": float(np.nanmean(fields["height_evidence"][y_index, x_index])),
                "dynamic_evidence_mean": float(np.nanmean(fields["dynamic_evidence"][y_index, x_index])),
                "depth_score_mean": float(np.nanmean(fields["depth_n"][y_index, x_index])),
                "vorticity_score_mean": float(np.nanmean(fields["vorticity_n"][y_index, x_index])),
                "anomaly_score_mean": float(np.nanmean(fields["anomaly_n"][y_index, x_index])),
                "support_score_mean": float(np.nanmean(fields["support"][y_index, x_index])),
            }
            if (
                metrics["support_score_mean"] < 0.16
                or metrics["height_evidence_mean"] < 0.16
                or (
                    metrics["depth_score_mean"] < 0.07
                    and metrics["vorticity_score_mean"] < 0.24
                )
            ):
                continue
            coordinates = _smooth_coordinates(coordinates, cfg.trough_output_points)
            if coordinates.shape[0] < 2:
                continue
            length_km = _haversine_length_km(coordinates)
            if length_km < cfg.trough_min_length_km:
                continue
            rank = float(
                np.nansum([item["score"] - reward_floor * 0.72 for item in segment])
                + 0.08 * len(segment)
            )
            raw_paths.append(
                _Path(
                    coordinates=coordinates,
                    score=rank,
                    candidate_source="dynamic_height_valley",
                    metrics=metrics,
                )
            )

    raw_paths.sort(key=lambda item: (item.score, _haversine_length_km(item.coordinates)), reverse=True)
    kept: list[_Path] = []
    for path in raw_paths:
        mean_lon = float(np.nanmean(path.coordinates[:, 0]))
        if mean_lon <= cfg.trough_lon_min + 1.5 or mean_lon >= cfg.trough_lon_max - 1.5:
            continue
        if any(_path_distance(path, old) < cfg.trough_duplicate_distance_km for old in kept):
            continue
        kept.append(path)
        if len(kept) >= cfg.trough_max_paths:
            break
    return kept


def _directed_path_distance_km(first: np.ndarray, second: np.ndarray) -> float:
    """Mean nearest distance from every point in *first* to *second*."""
    if first.shape[0] == 0 or second.shape[0] == 0:
        return float("inf")
    return float(_polyline_mean_distance_km(first, second))


def _merge_dynamic_corridors(paths: list[_Path], cfg: SoundingPathConfig) -> list[_Path]:
    """Join adjacent latitude segments and remove contained sub-segments."""
    filtered = []
    for path in paths:
        mean_lon = float(np.nanmean(path.coordinates[:, 0]))
        if mean_lon < 82.0 or mean_lon > 132.0:
            continue
        filtered.append(path)

    # Prefer a path that covers a larger latitude span when another path is
    # mostly contained in the same corridor.  Symmetric distance is unsuitable
    # here because it penalises the longer, more complete axis.
    filtered.sort(key=lambda item: float(np.ptp(item.coordinates[:, 1])), reverse=True)
    unique: list[_Path] = []
    for path in filtered:
        if any(
            _directed_path_distance_km(path.coordinates, old.coordinates) < 150.0
            for old in unique
        ):
            continue
        unique.append(path)

    changed = True
    while changed:
        changed = False
        best_pair: tuple[int, int, float] | None = None
        for first_index, first in enumerate(unique):
            for second_index in range(first_index + 1, len(unique)):
                second = unique[second_index]
                first_min, first_max = np.nanmin(first.coordinates[:, 1]), np.nanmax(first.coordinates[:, 1])
                second_min, second_max = np.nanmin(second.coordinates[:, 1]), np.nanmax(second.coordinates[:, 1])
                lat_gap = max(0.0, max(first_min, second_min) - min(first_max, second_max))
                mean_lon_gap = abs(
                    float(np.nanmean(first.coordinates[:, 0]) - np.nanmean(second.coordinates[:, 0]))
                )
                endpoint_distance = min(
                    _haversine_length_km(np.asarray([first.coordinates[0], second.coordinates[-1]])),
                    _haversine_length_km(np.asarray([first.coordinates[-1], second.coordinates[0]])),
                    _haversine_length_km(np.asarray([first.coordinates[0], second.coordinates[0]])),
                    _haversine_length_km(np.asarray([first.coordinates[-1], second.coordinates[-1]])),
                )
                if lat_gap <= 2.5 and mean_lon_gap <= 4.5 and endpoint_distance <= 520.0:
                    score = lat_gap * 100.0 + endpoint_distance
                    if best_pair is None or score < best_pair[2]:
                        best_pair = (first_index, second_index, score)
        if best_pair is None:
            break
        first_index, second_index, _ = best_pair
        first = unique[first_index]
        second = unique[second_index]
        source = np.vstack([first.coordinates, second.coordinates])
        source = source[np.argsort(source[:, 1])]
        _, indices = np.unique(np.round(source[:, 1], 5), return_index=True)
        source = source[np.sort(indices)]
        coordinates = _smooth_coordinates(source, cfg.trough_output_points)
        weight_first = max(float(np.ptp(first.coordinates[:, 1])), 1.0)
        weight_second = max(float(np.ptp(second.coordinates[:, 1])), 1.0)
        metrics = {
            key: (
                first.metrics.get(key, 0.0) * weight_first
                + second.metrics.get(key, 0.0) * weight_second
            )
            / (weight_first + weight_second)
            for key in set(first.metrics) | set(second.metrics)
        }
        merged = _Path(
            coordinates=coordinates,
            score=first.score + second.score,
            candidate_source="dynamic_height_valley",
            metrics=metrics,
        )
        unique = [item for index, item in enumerate(unique) if index not in {first_index, second_index}]
        unique.append(merged)
        unique.sort(key=lambda item: (float(np.ptp(item.coordinates[:, 1])), item.score), reverse=True)
        changed = True
    return unique


def _extend_dynamic_path(
    path: _Path,
    score: np.ndarray,
    fields: dict[str, np.ndarray],
    lat: np.ndarray,
    lon: np.ndarray,
    cfg: SoundingPathConfig,
) -> _Path:
    """Continue a coherent height valley through a few weaker latitude rows."""
    source = np.asarray(path.coordinates, dtype=float)
    source = source[np.argsort(source[:, 1])]
    indices = [
        (
            int(np.argmin(np.abs(lat - latitude))),
            int(np.argmin(np.abs(lon - longitude))),
        )
        for longitude, latitude in source
    ]
    # Keep one grid point per latitude row.
    by_y: dict[int, tuple[int, int]] = {y: (y, x) for y, x in indices}
    ordered = [by_y[y] for y in sorted(by_y)]

    def extend(start_y: int, start_x: int, direction: int) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        current_x = start_x
        previous_x: int | None = None
        weak = 0
        y_index = start_y + direction
        while 0 <= y_index < lat.size and cfg.trough_lat_min <= lat[y_index] <= cfg.trough_lat_max:
            candidates = np.where(
                (lon >= lon[current_x] - 3.3)
                & (lon <= lon[current_x] + 3.3)
                & (lon >= cfg.trough_lon_min)
                & (lon <= cfg.trough_lon_max)
            )[0]
            best: tuple[float, int, float] | None = None
            for x_index in candidates:
                local_score = float(score[y_index, x_index])
                height = float(fields["height_evidence"][y_index, x_index])
                if local_score < 0.10 and height < 0.12:
                    continue
                jump = abs(float(lon[x_index] - lon[current_x]))
                trend = 0.0
                if previous_x is not None:
                    predicted = float(2.0 * lon[current_x] - lon[previous_x])
                    trend = abs(float(lon[x_index] - predicted))
                value = local_score + 0.12 * height - 0.08 * jump**2 - 0.04 * trend**2
                if best is None or value > best[0]:
                    best = (value, int(x_index), local_score)
            if best is None:
                break
            _, x_index, local_score = best
            weak = weak + 1 if local_score < 0.18 else 0
            if weak >= 3:
                break
            previous_x, current_x = current_x, x_index
            points.append((y_index, current_x))
            y_index += direction
        return points

    south = extend(*ordered[0], -1)
    north = extend(*ordered[-1], 1)
    combined = [*reversed(south), *ordered, *north]
    coordinates = np.asarray([[lon[x], lat[y]] for y, x in combined], dtype=float)
    coordinates = _smooth_coordinates(coordinates, cfg.trough_output_points)
    if coordinates.shape[0] < 2:
        return path
    path.coordinates = coordinates
    return path


def _deduplicate_paths(
    closed_low: list[_Path],
    dynamic: list[_Path],
    cfg: SoundingPathConfig,
) -> list[_Path]:
    output = list(closed_low)
    dynamic_added = 0
    for path in dynamic:
        if any(_path_distance(path, old) < 250.0 for old in closed_low):
            continue
        if any(_path_distance(path, old) < cfg.trough_duplicate_distance_km for old in output):
            continue
        output.append(path)
        dynamic_added += 1
        if dynamic_added >= max(1, cfg.trough_max_paths - len(closed_low)):
            break
    output.sort(
        key=lambda item: (
            1 if item.candidate_source.startswith("closed_low_") else 0,
            item.score,
        ),
        reverse=True,
    )
    return output[: cfg.trough_max_paths]


def _trough_system(
    path: _Path,
    rank: int,
    confidence: float,
    lat: np.ndarray,
    lon: np.ndarray,
    support_distance_km: np.ndarray,
    cfg: SoundingPathConfig,
) -> dict[str, Any]:
    support_mean, support_p90 = _line_support_metrics(
        path.coordinates,
        lat,
        lon,
        support_distance_km,
    )
    branch_label = {
        "closed_low_south_branch": "闭合低涡南侧槽支",
        "closed_low_north_branch": "闭合低涡北侧槽支",
        "dynamic_height_valley": "多路径高度谷槽轴",
    }.get(path.candidate_source, "500hPa 槽线")
    metrics = {key: round(float(value), 4) for key, value in path.metrics.items() if np.isfinite(value)}
    return {
        "id": f"sounding-trough-v4-{rank:03d}",
        "type": "trough_candidate",
        "feature_type": "trough_candidate",
        "name": branch_label,
        "label": "槽线",
        "level": "500hPa",
        "confidence": round(min(0.92, max(0.55, float(confidence) + min(path.score, 1.0) * 0.04)), 2),
        "method": "sounding_multitrack_axis_v4",
        "method_detail": "station_height_valley_dynamic_programming",
        "candidate_source": path.candidate_source,
        "analysis_domain": {
            "lon_min": float(cfg.analysis_lon_min),
            "lon_max": float(cfg.analysis_lon_max),
            "lat_min": float(cfg.analysis_lat_min),
            "lat_max": float(cfg.analysis_lat_max),
        },
        "axis_length_km": round(float(_haversine_length_km(path.coordinates)), 1),
        "support_mean_distance_km": round(support_mean, 1) if support_mean is not None else None,
        "support_p90_distance_km": round(support_p90, 1) if support_p90 is not None else None,
        "closed_low_center": (
            [round(float(path.center[0]), 2), round(float(path.center[1]), 2)]
            if path.center is not None
            else None
        ),
        "path_metrics": metrics,
        "geometry": {
            "type": "line",
            "coordinates": [[float(x), float(y)] for x, y in path.coordinates],
        },
        "evidence": [
            "槽轴由同一时次探空站客观分析的500hPa高度谷自动追踪",
            "逐纬度允许多个候选并用动态规划保持轴线连续，避免大连通区PCA桥接",
            "闭合低涡附近允许南北分支分别输出，避免东北只保留一条槽线",
            "正涡度和形变仅作为高度槽的辅助证据，切变线仍独立输出",
        ],
    }


def detect_sounding_multitrack_troughs(
    z500: np.ndarray,
    u500: np.ndarray,
    v500: np.ndarray,
    lat: Iterable[float],
    lon: Iterable[float],
    *,
    support_distance_km: np.ndarray | None = None,
    support_mask: np.ndarray | None = None,
    confidence: float = 0.72,
    config: SoundingPathConfig | None = None,
) -> list[dict[str, Any]]:
    """Detect multiple station-derived 500hPa trough axes.

    A dominant closed low may yield independent north and south branches. Other
    troughs are found with a multi-candidate dynamic-programming tracker. The
    routine intentionally does not diagnose tropical cyclones and does not emit
    low-latitude shear lines.
    """

    cfg = config or SoundingPathConfig()
    z, u, v, lat_arr, lon_arr, support, valid_support = _prepare_fields(
        z500,
        u500,
        v500,
        lat,
        lon,
        support_distance_km,
        support_mask,
    )
    score, fields = _height_score_fields(
        z,
        u,
        v,
        lat_arr,
        lon_arr,
        support,
        valid_support,
        cfg,
    )
    closed_low = _closed_low_branches(score, fields, lat_arr, lon_arr, cfg)
    dynamic = _dynamic_height_paths(score, fields, lat_arr, lon_arr, cfg)
    dynamic = _merge_dynamic_corridors(dynamic, cfg)
    dynamic = [
        _extend_dynamic_path(path, score, fields, lat_arr, lon_arr, cfg)
        for path in dynamic
    ]
    paths = _deduplicate_paths(closed_low, dynamic, cfg)
    return [
        _trough_system(path, rank, confidence, lat_arr, lon_arr, support, cfg)
        for rank, path in enumerate(paths, start=1)
    ]


def _south_china_shear_path(
    z: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    support_distance_km: np.ndarray,
    support_mask: np.ndarray,
    cfg: SoundingPathConfig,
) -> tuple[np.ndarray | None, dict[str, float]]:
    z_smooth = _nan_gaussian(z, (1.0, 1.0))
    dynamics = _dynamic_fields(z_smooth, u, v, lat, lon)
    domain = (
        (lat[:, None] >= cfg.south_china_lat_min)
        & (lat[:, None] <= cfg.south_china_lat_max)
        & (lon[None, :] >= cfg.south_china_lon_min - 4.0)
        & (lon[None, :] <= cfg.south_china_lon_max + 2.0)
        & support_mask
        & np.isfinite(z_smooth)
    )
    deformation_n = _normalise(
        dynamics["deformation"],
        domain,
        lower_percentile=45.0,
        upper_percentile=90.0,
    )
    direction_n = _normalise(
        dynamics["direction_gradient"],
        domain,
        lower_percentile=45.0,
        upper_percentile=90.0,
    )
    convergence_n = _normalise(
        np.maximum(dynamics["convergence"], 0.0),
        domain,
        lower_percentile=45.0,
        upper_percentile=90.0,
    )
    vorticity_n = _normalise(
        np.maximum(dynamics["vorticity"], 0.0),
        domain,
        lower_percentile=45.0,
        upper_percentile=90.0,
    )
    boundary = np.maximum(
        np.exp(-((z_smooth - 5880.0) / 35.0) ** 2),
        0.65 * np.exp(-((z_smooth - 5840.0) / 35.0) ** 2),
    )
    support = _support_weight(support_distance_km, support_mask)
    score = (
        0.42 * deformation_n
        + 0.25 * direction_n
        + 0.12 * convergence_n
        + 0.08 * vorticity_n
        + 0.13 * boundary
    ) * (0.60 + 0.40 * support)
    score = np.where(domain, score, 0.0)

    y_values = np.where((lat >= cfg.south_china_lat_min) & (lat <= cfg.south_china_lat_max))[0]
    nodes: list[dict[str, Any]] = []
    nodes_by_y: dict[int, list[int]] = {}
    for y_index in y_values:
        row = score[y_index]
        local = row == ndimage.maximum_filter1d(row, size=5, mode="nearest")
        x_values = np.where(
            local
            & (row > 0.18)
            & (lon >= cfg.south_china_lon_min)
            & (lon <= cfg.south_china_lon_max)
        )[0]
        if x_values.size:
            x_values = x_values[np.argsort(row[x_values])[::-1][:5]]
        for x_index in x_values:
            index = len(nodes)
            nodes.append(
                {
                    "y": int(y_index),
                    "x": int(x_index),
                    "score": float(row[x_index]),
                    "dp": float(row[x_index] - 0.22),
                    "previous": None,
                    "length": 1,
                }
            )
            nodes_by_y.setdefault(int(y_index), []).append(index)

    for y_index in y_values:
        for node_index in nodes_by_y.get(int(y_index), []):
            node = nodes[node_index]
            for gap in (1, 2, 3):
                for previous_index in nodes_by_y.get(int(y_index - gap), []):
                    previous = nodes[previous_index]
                    delta_lon = abs(float(lon[node["x"]] - lon[previous["x"]]))
                    if delta_lon > 2.2 * gap:
                        continue
                    value = (
                        previous["dp"]
                        + (node["score"] - 0.22)
                        - 0.12 * (delta_lon / max(2.2 * gap, 0.1)) ** 2
                        - 0.08 * (gap - 1)
                    )
                    if value > node["dp"]:
                        node["dp"] = value
                        node["previous"] = previous_index
                        node["length"] = previous["length"] + 1

    for end_index in sorted(range(len(nodes)), key=lambda item: nodes[item]["dp"], reverse=True):
        if nodes[end_index]["length"] < 6:
            continue
        chain: list[dict[str, Any]] = []
        cursor: int | None = end_index
        while cursor is not None:
            item = nodes[cursor]
            chain.append(item)
            cursor = item["previous"]
        chain.reverse()

        segments: list[list[dict[str, Any]]] = [[]]
        for item in chain:
            if segments[-1] and (
                item["y"] - segments[-1][-1]["y"] > 2
                or abs(float(lon[item["x"]] - lon[segments[-1][-1]["x"]])) > 3.0
            ):
                segments.append([])
            segments[-1].append(item)
        segment = max(segments, key=len)
        if len(segment) < 6:
            continue
        coordinates = np.asarray([[lon[item["x"]], lat[item["y"]]] for item in segment], dtype=float)
        if float(np.ptp(coordinates[:, 1])) < cfg.shear_min_lat_span_deg:
            continue
        y_index = np.asarray([item["y"] for item in segment], dtype=int)
        x_index = np.asarray([item["x"] for item in segment], dtype=int)
        mean_score = float(np.nanmean(score[y_index, x_index]))
        deformation_mean = float(np.nanmean(deformation_n[y_index, x_index]))
        boundary_max = float(np.nanmax(boundary[y_index, x_index]))
        if mean_score < 0.31 or deformation_mean < 0.28 or boundary_max < 0.32:
            continue
        coordinates = _smooth_coordinates(coordinates, cfg.shear_output_points)
        if coordinates.shape[0] < 2 or _haversine_length_km(coordinates) < cfg.shear_min_length_km:
            continue
        return coordinates, {
            "score_mean": mean_score,
            "deformation_score_mean": deformation_mean,
            "direction_gradient_score_mean": float(np.nanmean(direction_n[y_index, x_index])),
            "convergence_score_mean": float(np.nanmean(convergence_n[y_index, x_index])),
            "vorticity_score_mean": float(np.nanmean(vorticity_n[y_index, x_index])),
            "height_boundary_support_max": boundary_max,
        }
    return None, {}


def detect_south_china_shear_system(
    z500: np.ndarray,
    u500: np.ndarray,
    v500: np.ndarray,
    lat: Iterable[float],
    lon: Iterable[float],
    *,
    support_distance_km: np.ndarray | None = None,
    support_mask: np.ndarray | None = None,
    confidence: float = 0.70,
    config: SoundingPathConfig | None = None,
) -> dict[str, Any] | None:
    """Detect a South-China/Hainan shear axis without promoting it to a trough."""

    cfg = config or SoundingPathConfig()
    z, u, v, lat_arr, lon_arr, support, valid_support = _prepare_fields(
        z500,
        u500,
        v500,
        lat,
        lon,
        support_distance_km,
        support_mask,
    )
    coordinates, metrics = _south_china_shear_path(
        z,
        u,
        v,
        lat_arr,
        lon_arr,
        support,
        valid_support,
        cfg,
    )
    if coordinates is None:
        return None
    support_mean, support_p90 = _line_support_metrics(coordinates, lat_arr, lon_arr, support)
    return {
        "id": "sounding-shear-south-china-v4-001",
        "type": "shear_line",
        "feature_type": "shear_line",
        "name": "华南—海南500hPa切变线",
        "label": "切变线",
        "level": "500hPa",
        "confidence": round(min(0.90, max(0.58, float(confidence) + 0.05)), 2),
        "method": "sounding_shear_track_v4",
        "method_detail": "deformation_direction_gradient_588_boundary_dp",
        "candidate_source": "south_china_588_deformation_track",
        "analysis_domain": {
            "lon_min": float(cfg.analysis_lon_min),
            "lon_max": float(cfg.analysis_lon_max),
            "lat_min": float(cfg.analysis_lat_min),
            "lat_max": float(cfg.analysis_lat_max),
        },
        "axis_length_km": round(float(_haversine_length_km(coordinates)), 1),
        "support_mean_distance_km": round(support_mean, 1) if support_mean is not None else None,
        "support_p90_distance_km": round(support_p90, 1) if support_p90 is not None else None,
        "path_metrics": {key: round(float(value), 4) for key, value in metrics.items()},
        "geometry": {
            "type": "line",
            "coordinates": [[float(x), float(y)] for x, y in coordinates],
        },
        "evidence": [
            "轴线由500hPa风向转折、形变、弱辐合和正涡度联合追踪",
            "588/584dagpm边界邻近度仅用于约束天气尺度位置，不把切变线强制解释为高度槽",
            "华南—海南资料不足时可不输出，不使用固定坐标绘制",
            "切变线与槽线保持独立feature_type和Map显示开关",
        ],
    }


def merge_shear_systems(
    systems: list[dict[str, Any]],
    supplement: dict[str, Any] | None,
    *,
    duplicate_distance_km: float = 180.0,
) -> list[dict[str, Any]]:
    """Prefer the regional continuous shear track over a nearby noisy fragment."""

    if supplement is None:
        return list(systems)
    supplement_coords = np.asarray(
        (supplement.get("geometry") or {}).get("coordinates") or [],
        dtype=float,
    )
    output: list[dict[str, Any]] = []
    for system in systems:
        coordinates = np.asarray(
            (system.get("geometry") or {}).get("coordinates") or [],
            dtype=float,
        )
        if coordinates.ndim == 2 and coordinates.shape[0] >= 2 and supplement_coords.shape[0] >= 2:
            distance = 0.5 * (
                _polyline_mean_distance_km(coordinates, supplement_coords)
                + _polyline_mean_distance_km(supplement_coords, coordinates)
            )
            if distance < duplicate_distance_km:
                continue
        output.append(system)
    return [*output, supplement]
