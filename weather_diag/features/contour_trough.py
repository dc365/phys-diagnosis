from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

import matplotlib
import numpy as np
from scipy import ndimage

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from weather_diag.io.geojson import line_feature

from .trough_ridge import (
    EARTH_KM_PER_DEG,
    _grid_spacing_km,
    _haversine_length_km,
    _maybe_geopotential_to_height,
    _nan_gaussian,
    _polyline_mean_distance_km,
    _prepare_lat_lon_field,
    _remove_lonlat_close_points,
    _smooth_xy_spline,
    _xy_km_to_lonlat,
    _lonlat_to_xy_km,
)


@dataclass(frozen=True)
class ContourSeededTroughConfig:
    analysis_lat_min: float = 13.0
    analysis_lat_max: float = 55.0
    analysis_lon_min: float = 60.0
    analysis_lon_max: float = 150.0
    smooth_radius_km: float = 150.0
    contour_interval_dagpm: float = 4.0
    contour_tip_window_km: float = 520.0
    contour_tip_resample_km: float = 90.0
    contour_tip_min_depth_deg: float = 0.65
    contour_cluster_radius_km: float = 1050.0
    contour_cluster_max_lon_deg: float = 5.5
    contour_cluster_max_lat_deg: float = 10.0
    contour_seed_min_levels: int = 2
    contour_seed_otsu_bins: int = 24
    trace_valley_window_km: float = 320.0
    trace_search_radius_deg: float = 4.0
    trace_max_lon_step_deg: float = 2.4
    trace_max_gap_rows: int = 2
    trace_min_points: int = 5
    trace_min_lat_span_deg: float = 4.0
    min_length_km: float = 320.0
    max_lines: int = 8
    output_points: int = 28
    spline_smooth_factor: float = 0.7
    duplicate_distance_km: float = 240.0
    max_sinuosity: float = 2.8
    low_lat_zonal_filter_max_lat: float = 30.0
    low_lat_zonal_max_aspect_ratio: float = 1.5
    base_confidence: float = 0.72


def _cfg_from_thresholds(thresholds: dict | None) -> ContourSeededTroughConfig:
    raw = (thresholds or {}).get("contour_trough", thresholds or {})
    defaults = ContourSeededTroughConfig()
    values = {
        name: raw[name]
        for name in defaults.__dataclass_fields__  # type: ignore[attr-defined]
        if name in raw
    }
    return ContourSeededTroughConfig(**values)


def _distance_km(first: np.ndarray, second: np.ndarray) -> float:
    return _haversine_length_km(np.asarray([first, second], dtype=float))


def _resample_line(coords: np.ndarray, spacing_km: float) -> np.ndarray:
    arr = np.asarray(coords, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2:
        return arr
    lat0 = float(np.nanmedian(arr[:, 1]))
    xy = _lonlat_to_xy_km(arr[:, 0], arr[:, 1], lat0)
    segment = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    distance = np.concatenate([[0.0], np.cumsum(segment)])
    total = float(distance[-1])
    if total <= 1.0e-6:
        return arr[:1]
    count = max(2, int(np.ceil(total / max(spacing_km, 20.0))) + 1)
    target = np.linspace(0.0, total, count)
    sampled = np.column_stack(
        [
            np.interp(target, distance, xy[:, 0]),
            np.interp(target, distance, xy[:, 1]),
        ]
    )
    return _xy_km_to_lonlat(sampled, lat0)


def _contour_interval(field: np.ndarray, cfg: ContourSeededTroughConfig) -> float:
    valid = field[np.isfinite(field)]
    if valid.size == 0:
        return 40.0
    multiplier = 10.0 if float(np.nanmedian(np.abs(valid))) > 1000.0 else 1.0
    return float(cfg.contour_interval_dagpm * multiplier)


def _contours(
    field: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    cfg: ContourSeededTroughConfig,
) -> tuple[list[tuple[float, np.ndarray]], float]:
    valid = field[np.isfinite(field)]
    interval = _contour_interval(field, cfg)
    if valid.size == 0:
        return [], interval
    start = ceil(float(np.nanmin(valid)) / interval) * interval
    end = floor(float(np.nanmax(valid)) / interval) * interval
    levels = []
    value = start
    while value <= end and len(levels) < 80:
        levels.append(float(value))
        value += interval
    if not levels:
        return [], interval

    figure, axis = plt.subplots()
    try:
        contour_set = axis.contour(
            lon,
            lat,
            np.ma.masked_invalid(field),
            levels=levels,
        )
        output: list[tuple[float, np.ndarray]] = []
        for level, segments in zip(contour_set.levels, contour_set.allsegs):
            for segment in segments:
                if len(segment) >= 5:
                    output.append((float(level), np.asarray(segment, dtype=float)))
        return output, interval
    finally:
        plt.close(figure)


def _segment_tips(
    level: float,
    coords: np.ndarray,
    cfg: ContourSeededTroughConfig,
) -> list[dict]:
    line = _resample_line(coords, cfg.contour_tip_resample_km)
    steps = max(
        2,
        int(round(cfg.contour_tip_window_km / max(cfg.contour_tip_resample_km, 20.0))),
    )
    if line.shape[0] < 2 * steps + 1:
        return []

    candidates: list[dict] = []
    for index in range(steps, line.shape[0] - steps):
        window = line[index - steps : index + steps + 1]
        tip = line[index]
        if tip[1] > float(np.nanmin(window[:, 1])) + 0.12:
            continue
        left_lat = float(np.nanmean(line[index - steps : index, 1]))
        right_lat = float(np.nanmean(line[index + 1 : index + steps + 1, 1]))
        depth = min(left_lat - tip[1], right_lat - tip[1])
        if depth < cfg.contour_tip_min_depth_deg:
            continue
        path_length = _haversine_length_km(window)
        chord = _distance_km(window[0], window[-1])
        bend = max(0.0, 1.0 - chord / max(path_length, 1.0))
        symmetry = 1.0 - min(
            1.0,
            abs(left_lat - right_lat) / max(depth * 2.0, 0.2),
        )
        score = (
            depth
            / cfg.contour_tip_min_depth_deg
            * (0.70 + 1.8 * bend)
            * (0.80 + 0.20 * symmetry)
        )
        candidates.append(
            {
                "level": float(level),
                "lon": float(tip[0]),
                "lat": float(tip[1]),
                "depth_deg": float(depth),
                "score": float(score),
            }
        )

    kept: list[dict] = []
    for item in sorted(candidates, key=lambda candidate: candidate["score"], reverse=True):
        point = np.asarray([item["lon"], item["lat"]], dtype=float)
        if any(
            _distance_km(point, np.asarray([old["lon"], old["lat"]], dtype=float))
            < cfg.contour_tip_window_km * 0.55
            for old in kept
        ):
            continue
        kept.append(item)
    return kept


def _cluster_tips(candidates: list[dict], cfg: ContourSeededTroughConfig) -> list[dict]:
    if not candidates:
        return []
    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first_index, first in enumerate(candidates):
        first_point = np.asarray([first["lon"], first["lat"]], dtype=float)
        for second_index in range(first_index + 1, len(candidates)):
            second = candidates[second_index]
            second_point = np.asarray([second["lon"], second["lat"]], dtype=float)
            if (
                abs(float(first["lon"] - second["lon"]))
                <= cfg.contour_cluster_max_lon_deg
                and abs(float(first["lat"] - second["lat"]))
                <= cfg.contour_cluster_max_lat_deg
                and _distance_km(first_point, second_point)
                <= cfg.contour_cluster_radius_km
            ):
                union(first_index, second_index)

    groups: dict[int, list[dict]] = {}
    for index, item in enumerate(candidates):
        groups.setdefault(find(index), []).append(item)

    clusters: list[dict] = []
    for items in groups.values():
        best_by_level: dict[float, dict] = {}
        for item in items:
            level = round(float(item["level"]), 6)
            if level not in best_by_level or item["score"] > best_by_level[level]["score"]:
                best_by_level[level] = item
        selected = list(best_by_level.values())
        levels = sorted(best_by_level)
        weights = np.asarray([max(item["score"], 0.05) for item in selected])
        selected_lats = np.asarray([item["lat"] for item in selected])
        selected_lons = np.asarray([item["lon"] for item in selected])
        level_count = len(levels)
        mean_score = float(np.mean([item["score"] for item in selected]))
        clusters.append(
            {
                "lon": float(np.average(selected_lons, weights=weights)),
                "lat": float(np.average(selected_lats, weights=weights)),
                "score": (
                    mean_score * (1.0 + 0.38 * max(0, level_count - 1))
                    + 0.15 * float(np.mean([item["depth_deg"] for item in selected]))
                ),
                "level_count": level_count,
                "levels": levels,
                "depth_mean_deg": float(
                    np.mean([item["depth_deg"] for item in selected])
                ),
                "tip_lat_min": float(np.nanmin(selected_lats)),
                "tip_lat_max": float(np.nanmax(selected_lats)),
                "tip_lon_min": float(np.nanmin(selected_lons)),
                "tip_lon_max": float(np.nanmax(selected_lons)),
            }
        )
    return clusters


def _otsu(values: np.ndarray, bins: int) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("inf")
    if arr.size < 3 or np.isclose(float(arr.min()), float(arr.max())):
        return float(arr.min())
    histogram, edges = np.histogram(
        arr,
        bins=min(max(4, int(bins)), max(4, int(arr.size) * 2)),
    )
    centers = (edges[:-1] + edges[1:]) / 2.0
    lower_weight = np.cumsum(histogram)
    upper_weight = histogram.sum() - lower_weight
    lower_mean = np.cumsum(histogram * centers) / np.maximum(lower_weight, 1)
    upper_sum = np.cumsum((histogram * centers)[::-1])[::-1]
    upper_mean = upper_sum / np.maximum(upper_weight, 1)
    between = lower_weight * upper_weight * (lower_mean - upper_mean) ** 2
    between[-1] = 0.0
    return float(centers[int(np.nanargmax(between))])


def _select_seeds(
    clusters: list[dict],
    cfg: ContourSeededTroughConfig,
) -> tuple[list[dict], float]:
    multi_level = [
        cluster
        for cluster in clusters
        if cluster["level_count"] >= cfg.contour_seed_min_levels
    ]
    strong_single = [
        cluster
        for cluster in clusters
        if cluster["level_count"] < cfg.contour_seed_min_levels
        and cluster["depth_mean_deg"] >= 2.0 * cfg.contour_tip_min_depth_deg
    ]
    eligible = [*multi_level, *strong_single]
    if not eligible:
        return [], float("inf")
    threshold = _otsu(
        np.asarray([cluster["score"] for cluster in eligible]),
        cfg.contour_seed_otsu_bins,
    )
    selected = (
        list(multi_level)
        if multi_level
        else [cluster for cluster in strong_single if cluster["score"] >= threshold]
    )
    if not selected:
        selected = [max(eligible, key=lambda cluster: cluster["score"])]

    kept: list[dict] = []
    for item in sorted(
        selected,
        key=lambda cluster: (cluster["level_count"], cluster["score"]),
        reverse=True,
    ):
        point = np.asarray([item["lon"], item["lat"]], dtype=float)
        if any(
            _distance_km(point, np.asarray([old["lon"], old["lat"]], dtype=float))
            < min(cfg.contour_cluster_radius_km * 0.40, 360.0)
            for old in kept
        ):
            continue
        kept.append(item)
    return kept, threshold


def _robust_scale(values: np.ndarray, default: float) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0.0)]
    if arr.size == 0:
        return float(default)
    median = float(np.nanmedian(arr))
    mad = float(np.nanmedian(np.abs(arr - median)))
    return max(float(default), median + 2.5 * 1.4826 * mad)


def _valley_fields(
    field: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    interval: float,
    cfg: ContourSeededTroughConfig,
    vorticity: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, dx_km = _grid_spacing_km(lat, lon)
    radius = max(2, int(round(cfg.trace_valley_window_km / max(dx_km, 1.0))))
    depth = np.zeros_like(field)
    local_minimum = np.zeros_like(field, dtype=bool)

    for x_index in range(radius, lon.size - radius):
        left_values = field[:, x_index - radius : x_index]
        right_values = field[:, x_index + 1 : x_index + radius + 1]
        left_count = np.sum(np.isfinite(left_values), axis=1)
        right_count = np.sum(np.isfinite(right_values), axis=1)
        left = np.full(field.shape[0], np.nan)
        right = np.full(field.shape[0], np.nan)
        np.divide(
            np.nansum(left_values, axis=1),
            left_count,
            out=left,
            where=left_count > 0,
        )
        np.divide(
            np.nansum(right_values, axis=1),
            right_count,
            out=right,
            where=right_count > 0,
        )
        depth[:, x_index] = np.minimum(left, right) - field[:, x_index]
        local_minimum[:, x_index] = (
            (field[:, x_index] <= field[:, x_index - 1])
            & (field[:, x_index] < field[:, x_index + 1])
        )

    first_derivative = np.gradient(field, lon, axis=1, edge_order=1)
    second_derivative = np.gradient(first_derivative, lon, axis=1, edge_order=1)
    positive_depth = np.maximum(depth, 0.0)
    positive_curvature = np.maximum(second_derivative, 0.0)
    signal = (
        0.70
        * np.clip(
            positive_depth
            / _robust_scale(positive_depth, max(interval * 0.02, 0.5)),
            0.0,
            2.0,
        )
        + 0.25
        * np.clip(
            positive_curvature
            / _robust_scale(positive_curvature, 0.1),
            0.0,
            2.0,
        )
    )
    if vorticity is not None:
        positive_vorticity = np.maximum(vorticity, 0.0)
        signal += 0.05 * np.clip(
            positive_vorticity / _robust_scale(positive_vorticity, 1.0e-6),
            0.0,
            2.0,
        )
    return depth, np.where(local_minimum & np.isfinite(field), signal, 0.0), local_minimum


def _seed_start(
    seed: dict,
    lat: np.ndarray,
    lon: np.ndarray,
    signal: np.ndarray,
    local_minimum: np.ndarray,
    cfg: ContourSeededTroughConfig,
) -> tuple[int, int] | None:
    target_y = int(np.argmin(np.abs(lat - seed["lat"])))
    best: tuple[float, int, int] | None = None
    for y_index in range(max(0, target_y - 1), min(lat.size, target_y + 2)):
        for x_index in np.where(local_minimum[y_index])[0]:
            if abs(float(lon[x_index] - seed["lon"])) > cfg.trace_search_radius_deg:
                continue
            penalty = (
                (float(lon[x_index] - seed["lon"]) / cfg.trace_search_radius_deg) ** 2
                + ((float(lat[y_index] - seed["lat"])) / 2.0) ** 2
            )
            score = float(signal[y_index, x_index]) - 0.20 * penalty
            if best is None or score > best[0]:
                best = (score, y_index, int(x_index))
    return None if best is None else (best[1], best[2])


def _trace(
    start_y: int,
    start_x: int,
    direction: int,
    lat: np.ndarray,
    lon: np.ndarray,
    depth: np.ndarray,
    signal: np.ndarray,
    local_minimum: np.ndarray,
    interval: float,
    cfg: ContourSeededTroughConfig,
    bounds: tuple[float, float, float, float],
) -> list[tuple[int, int]]:
    lat_min, lat_max, lon_min, lon_max = bounds
    points: list[tuple[int, int]] = []
    current_x = start_x
    previous_x: int | None = None
    gaps = 0
    min_depth = max(interval * 0.0125, 0.35)
    y_index = start_y + direction

    while 0 <= y_index < lat.size and lat_min <= lat[y_index] <= lat_max:
        max_step = cfg.trace_max_lon_step_deg * (gaps + 1)
        candidates = np.where(
            local_minimum[y_index]
            & (np.abs(lon - lon[current_x]) <= max_step)
            & (lon >= lon_min)
            & (lon <= lon_max)
        )[0]
        best: tuple[float, int] | None = None
        for x_index in candidates:
            if depth[y_index, x_index] < min_depth and signal[y_index, x_index] < 0.15:
                continue
            jump = abs(float(lon[x_index] - lon[current_x])) / max(max_step, 0.1)
            trend = 0.0
            if previous_x is not None:
                predicted = float(lon[current_x] + lon[current_x] - lon[previous_x])
                trend = abs(float(lon[x_index] - predicted)) / max(max_step, 0.1)
            score = float(signal[y_index, x_index]) - 0.22 * jump**2 - 0.10 * trend**2
            if best is None or score > best[0]:
                best = (score, int(x_index))
        if best is None:
            gaps += 1
            if gaps > cfg.trace_max_gap_rows:
                break
            y_index += direction
            continue
        gaps = 0
        previous_x, current_x = current_x, best[1]
        points.append((y_index, current_x))
        y_index += direction
    return points


def _seed_bounds(seed: dict, cfg: ContourSeededTroughConfig) -> tuple[float, float, float, float]:
    lat_span = max(0.0, float(seed["tip_lat_max"] - seed["tip_lat_min"]))
    lat_margin = max(2.5, min(4.0, 0.20 * lat_span + 1.5))
    lon_span = max(0.0, float(seed["tip_lon_max"] - seed["tip_lon_min"]))
    lon_margin = max(3.0, min(5.0, 0.50 * lon_span + 2.0))
    return (
        max(cfg.analysis_lat_min, float(seed["tip_lat_min"]) - lat_margin),
        min(cfg.analysis_lat_max, float(seed["tip_lat_max"]) + lat_margin),
        max(cfg.analysis_lon_min, float(seed["tip_lon_min"]) - lon_margin),
        min(cfg.analysis_lon_max, float(seed["tip_lon_max"]) + lon_margin),
    )


def _trace_seed(
    seed: dict,
    field: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    depth: np.ndarray,
    signal: np.ndarray,
    local_minimum: np.ndarray,
    interval: float,
    cfg: ContourSeededTroughConfig,
) -> dict | None:
    start = _seed_start(seed, lat, lon, signal, local_minimum, cfg)
    if start is None:
        return None
    start_y, start_x = start
    bounds = _seed_bounds(seed, cfg)
    indices = [
        *reversed(
            _trace(
                start_y,
                start_x,
                -1,
                lat,
                lon,
                depth,
                signal,
                local_minimum,
                interval,
                cfg,
                bounds,
            )
        ),
        (start_y, start_x),
        *_trace(
            start_y,
            start_x,
            1,
            lat,
            lon,
            depth,
            signal,
            local_minimum,
            interval,
            cfg,
            bounds,
        ),
    ]
    if len(indices) < cfg.trace_min_points:
        return None

    source = np.asarray([[lon[x], lat[y]] for y, x in indices], dtype=float)
    source = source[np.argsort(source[:, 1])]
    _, unique = np.unique(np.round(source[:, 1], 8), return_index=True)
    source = source[np.sort(unique)]
    lat0 = float(np.nanmedian(source[:, 1]))
    source_xy = _lonlat_to_xy_km(source[:, 0], source[:, 1], lat0)
    final_xy = _smooth_xy_spline(
        source_xy,
        count=max(len(source), cfg.output_points),
        smooth_factor=cfg.spline_smooth_factor,
    )
    coords = _xy_km_to_lonlat(final_xy, lat0)
    coords[:, 0] = np.clip(
        coords[:, 0],
        float(np.nanmin(source[:, 0]) - 0.5),
        float(np.nanmax(source[:, 0]) + 0.5),
    )
    coords[:, 1] = np.clip(
        coords[:, 1],
        float(np.nanmin(source[:, 1])),
        float(np.nanmax(source[:, 1])),
    )
    coords = _remove_lonlat_close_points(coords, min_step_km=35.0)
    if coords.shape[0] < 2:
        return None

    length_km = _haversine_length_km(coords)
    chord_km = _distance_km(coords[0], coords[-1])
    sinuosity = length_km / max(chord_km, 1.0)
    lat_span = float(np.ptp(coords[:, 1]))
    lon_span = float(np.ptp(coords[:, 0]))
    lat_mean = float(np.nanmean(coords[:, 1]))
    if (
        length_km < cfg.min_length_km
        or lat_span < cfg.trace_min_lat_span_deg
        or sinuosity > cfg.max_sinuosity
        or (
            lat_mean < cfg.low_lat_zonal_filter_max_lat
            and lon_span > cfg.low_lat_zonal_max_aspect_ratio * max(lat_span, 0.5)
        )
    ):
        return None

    grid_values = []
    valley_depths = []
    strengths = []
    for longitude, latitude in coords:
        y_index = int(np.argmin(np.abs(lat - latitude)))
        x_index = int(np.argmin(np.abs(lon - longitude)))
        grid_values.append(field[y_index, x_index])
        valley_depths.append(depth[y_index, x_index])
        strengths.append(signal[y_index, x_index])

    return {
        "coordinates": [[float(x), float(y)] for x, y in coords],
        "axis_length_km": float(length_km),
        "sinuosity": float(sinuosity),
        "lat_span": lat_span,
        "lon_span": lon_span,
        "lat_mean": lat_mean,
        "min_z": float(np.nanmin(grid_values)),
        "max_z": float(np.nanmax(grid_values)),
        "valley_depth_mean_gpm": float(np.nanmean(valley_depths)),
        "trace_strength_mean": float(np.nanmean(strengths)),
        "seed": seed,
    }


def _deduplicate(lines: list[dict], cfg: ContourSeededTroughConfig) -> list[dict]:
    kept: list[dict] = []
    for line in sorted(
        lines,
        key=lambda item: (
            item["seed"]["level_count"],
            item["seed"]["score"],
            item["axis_length_km"],
        ),
        reverse=True,
    ):
        coords = np.asarray(line["coordinates"], dtype=float)
        if any(
            _polyline_mean_distance_km(
                coords,
                np.asarray(old["coordinates"], dtype=float),
            )
            < cfg.duplicate_distance_km
            for old in kept
        ):
            continue
        kept.append(line)
    return kept[: cfg.max_lines]


def detect_contour_seeded_troughs(
    z500: np.ndarray,
    lat,
    lon,
    thresholds: dict | None = None,
    vorticity500: np.ndarray | None = None,
) -> list[dict]:
    """Detect height troughs from automatically clustered contour tips.

    Only the supplied height grid is required. The grid may itself be produced
    entirely from sounding stations. Wind shear remains a separate feature layer.
    """

    cfg = _cfg_from_thresholds(thresholds)
    z = _maybe_geopotential_to_height(np.asarray(z500, dtype=float))
    z, lat_arr, lon_arr, vorticity = _prepare_lat_lon_field(
        z,
        lat,
        lon,
        vorticity500,
    )
    dy_km, dx_km = _grid_spacing_km(lat_arr, lon_arr)
    smooth = _nan_gaussian(
        z,
        (
            max(0.5, cfg.smooth_radius_km / dy_km),
            max(0.5, cfg.smooth_radius_km / dx_km),
        ),
    )
    domain = (
        (lat_arr[:, None] >= cfg.analysis_lat_min)
        & (lat_arr[:, None] <= cfg.analysis_lat_max)
        & (lon_arr[None, :] >= cfg.analysis_lon_min)
        & (lon_arr[None, :] <= cfg.analysis_lon_max)
    )
    smooth = np.where(domain, smooth, np.nan)

    contour_segments, interval = _contours(smooth, lat_arr, lon_arr, cfg)
    tips = [
        tip
        for level, coordinates in contour_segments
        for tip in _segment_tips(level, coordinates, cfg)
    ]
    seeds, seed_threshold = _select_seeds(_cluster_tips(tips, cfg), cfg)
    depth, signal, local_minimum = _valley_fields(
        smooth,
        lat_arr,
        lon_arr,
        interval,
        cfg,
        vorticity,
    )
    lines = _deduplicate(
        [
            line
            for seed in seeds
            if (
                line := _trace_seed(
                    seed,
                    smooth,
                    lat_arr,
                    lon_arr,
                    depth,
                    signal,
                    local_minimum,
                    interval,
                    cfg,
                )
            )
            is not None
        ],
        cfg,
    )

    features: list[dict] = []
    for rank, line in enumerate(lines, start=1):
        seed = line["seed"]
        low_latitude = line["lat_mean"] < 30.0
        features.append(
            line_feature(
                line["coordinates"],
                {
                    "id": f"trough_{rank:03d}",
                    "feature_type": "trough",
                    "title": "500hPa 槽线",
                    "level": "500hPa",
                    "confidence": float(
                        min(
                            0.92,
                            cfg.base_confidence
                            + 0.03 * min(seed["level_count"], 4)
                            + 0.04 * min(seed["score"], 1.0),
                        )
                    ),
                    "method": "nmc_style_synoptic_axis_v7",
                    "method_detail": "contour_seeded_valley_axis_v1",
                    "candidate_source": (
                        "meridional_valley_track"
                        if low_latitude
                        else "contour_tip_seed"
                    ),
                    "seed_source": "contour_tip_cluster",
                    "seed_threshold_method": "otsu_between_class_variance",
                    "seed_threshold": float(seed_threshold),
                    "seed_score": float(seed["score"]),
                    "contour_support_count": int(seed["level_count"]),
                    "contour_levels_gpm": [float(value) for value in seed["levels"]],
                    "seed_lon": float(seed["lon"]),
                    "seed_lat": float(seed["lat"]),
                    "axis_length_km": float(line["axis_length_km"]),
                    "sinuosity": float(line["sinuosity"]),
                    "lat_span": float(line["lat_span"]),
                    "lon_span": float(line["lon_span"]),
                    "min_z500_gpm": float(line["min_z"]),
                    "max_z500_gpm": float(line["max_z"]),
                    "valley_depth_mean_gpm": float(line["valley_depth_mean_gpm"]),
                    "trace_strength_mean": float(line["trace_strength_mean"]),
                    "analysis_domain": {
                        "lon_min": float(cfg.analysis_lon_min),
                        "lon_max": float(cfg.analysis_lon_max),
                        "lat_min": float(cfg.analysis_lat_min),
                        "lat_max": float(cfg.analysis_lat_max),
                    },
                    "evidence": [
                        "槽线种子由多条500hPa等高线的向南凹陷自动聚类得到",
                        "种子阈值由Otsu类间方差自动确定，不依赖固定高分位",
                        "轴线沿逐纬度高度低谷追踪，邻近种子分别生成独立轴线",
                        "切变线继续由独立风场算法识别",
                    ],
                },
            )
        )
    return features
