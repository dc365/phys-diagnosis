from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

import numpy as np
from scipy import ndimage
from scipy.interpolate import PchipInterpolator

from weather_diag.features.trough_ridge import _haversine_length_km

GEOMETRY_REFINEMENT_VERSION = "sounding_z500_geometry_v5"


def _nan_gaussian(field: np.ndarray, sigma_yx: tuple[float, float]) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.full_like(arr, np.nan, dtype=float)
    values = ndimage.gaussian_filter(np.where(finite, arr, 0.0), sigma=sigma_yx, mode="nearest")
    weights = ndimage.gaussian_filter(finite.astype(float), sigma=sigma_yx, mode="nearest")
    output = np.full_like(arr, np.nan, dtype=float)
    np.divide(values, weights, out=output, where=weights > 1.0e-6)
    return output


def _line_coordinates(system: dict[str, Any]) -> np.ndarray:
    coordinates = np.asarray((system.get("geometry") or {}).get("coordinates") or [], dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[0] < 2 or coordinates.shape[1] < 2:
        return np.empty((0, 2), dtype=float)
    coordinates = coordinates[:, :2]
    return coordinates[np.isfinite(coordinates).all(axis=1)]


def _remove_close_points(coordinates: np.ndarray, min_step_km: float = 18.0) -> np.ndarray:
    coords = np.asarray(coordinates, dtype=float)
    if coords.shape[0] <= 2:
        return coords
    kept = [coords[0]]
    for point in coords[1:-1]:
        if _haversine_length_km(np.asarray([kept[-1], point], dtype=float)) >= min_step_km:
            kept.append(point)
    kept.append(coords[-1])
    return np.asarray(kept, dtype=float)


def _uniform_xy(coordinates: np.ndarray, count: int) -> tuple[np.ndarray, float, float]:
    coords = np.asarray(coordinates, dtype=float)
    lat0 = float(np.nanmedian(coords[:, 1]))
    x_scale = 111.32 * max(float(np.cos(np.deg2rad(lat0))), 0.20)
    y_scale = 111.32
    xy = np.column_stack([coords[:, 0] * x_scale, coords[:, 1] * y_scale])
    segment = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(segment)])
    total = float(cumulative[-1])
    if not np.isfinite(total) or total <= 1.0e-6:
        return xy, x_scale, y_scale
    target = np.linspace(0.0, total, max(2, int(count)))
    uniform = np.column_stack(
        [
            np.interp(target, cumulative, xy[:, 0]),
            np.interp(target, cumulative, xy[:, 1]),
        ]
    )
    return uniform, x_scale, y_scale


def polyline_roughness(coordinates: np.ndarray) -> float:
    """Dimensionless high-frequency bending score used by regression tests."""
    coords = np.asarray(coordinates, dtype=float)
    if coords.ndim != 2 or coords.shape[0] < 4:
        return 0.0
    xy, _, _ = _uniform_xy(coords, max(12, min(40, coords.shape[0])))
    first = np.diff(xy, axis=0)
    second = np.diff(xy, n=2, axis=0)
    length = float(np.sum(np.linalg.norm(first, axis=1)))
    if length <= 1.0e-9:
        return 0.0
    return float(np.sum(np.linalg.norm(second, axis=1)) / length)


def _smooth_shear_coordinates(coordinates: np.ndarray) -> np.ndarray:
    coords = np.asarray(coordinates, dtype=float)
    coords = coords[np.isfinite(coords).all(axis=1)]
    if coords.shape[0] < 4:
        return coords

    original_length = float(_haversine_length_km(coords))
    count = int(np.clip(round(original_length / 80.0) + 1, 12, 36))
    uniform, x_scale, y_scale = _uniform_xy(coords, count)
    if uniform.shape[0] < 4:
        return coords

    before = float(
        np.sum(np.linalg.norm(np.diff(uniform, n=2, axis=0), axis=1))
        / max(np.sum(np.linalg.norm(np.diff(uniform, axis=0), axis=1)), 1.0e-9)
    )
    if before < 0.085:
        return _remove_close_points(coords)

    median = np.column_stack(
        [
            ndimage.median_filter(uniform[:, 0], size=5, mode="nearest"),
            ndimage.median_filter(uniform[:, 1], size=5, mode="nearest"),
        ]
    )
    candidates: list[tuple[float, np.ndarray]] = []
    for sigma in (1.35, 1.8, 2.3):
        smoothed = np.column_stack(
            [
                ndimage.gaussian_filter1d(median[:, 0], sigma=sigma, mode="nearest"),
                ndimage.gaussian_filter1d(median[:, 1], sigma=sigma, mode="nearest"),
            ]
        )
        t = np.linspace(0.0, 1.0, smoothed.shape[0])
        interior = np.minimum(1.0, np.minimum(t, 1.0 - t) * 6.0)[:, None]
        smoothed = interior * smoothed + (1.0 - interior) * uniform

        displacement = np.linalg.norm(smoothed - uniform, axis=1)
        maximum = float(np.nanmax(displacement)) if displacement.size else 0.0
        if maximum > 140.0:
            smoothed = uniform + (140.0 / maximum) * (smoothed - uniform)

        first = np.diff(smoothed, axis=0)
        second = np.diff(smoothed, n=2, axis=0)
        roughness = float(
            np.sum(np.linalg.norm(second, axis=1))
            / max(np.sum(np.linalg.norm(first, axis=1)), 1.0e-9)
        )
        candidates.append((roughness, smoothed))

    after, best = min(candidates, key=lambda item: item[0])
    if after >= before * 0.92:
        return _remove_close_points(coords)

    output = np.column_stack([best[:, 0] / x_scale, best[:, 1] / y_scale])
    output[:, 0] = np.clip(
        output[:, 0],
        float(np.nanmin(coords[:, 0]) - 0.6),
        float(np.nanmax(coords[:, 0]) + 0.6),
    )
    output[:, 1] = np.clip(
        output[:, 1],
        float(np.nanmin(coords[:, 1]) - 0.4),
        float(np.nanmax(coords[:, 1]) + 0.4),
    )
    return _remove_close_points(output)


def smooth_shear_systems(systems: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Smooth all sounding shear axes after regional/generic de-duplication."""
    output: list[dict[str, Any]] = []
    for item in systems:
        system = deepcopy(item)
        coordinates = _line_coordinates(system)
        if coordinates.shape[0] < 4:
            output.append(system)
            continue
        before = polyline_roughness(coordinates)
        smoothed = _smooth_shear_coordinates(coordinates)
        after = polyline_roughness(smoothed)
        if smoothed.shape[0] >= 2 and after < before * 0.96:
            geometry = dict(system.get("geometry") or {})
            geometry["coordinates"] = [[float(x), float(y)] for x, y in smoothed]
            system["geometry"] = geometry
            system["axis_length_km"] = round(float(_haversine_length_km(smoothed)), 1)
            system["geometry_refinement_version"] = GEOMETRY_REFINEMENT_VERSION
            system["display_smoothing"] = "arc_length_median_gaussian_v5"
            system["smoothing_metrics"] = {
                "roughness_before": round(before, 5),
                "roughness_after": round(after, 5),
            }
            evidence = list(system.get("evidence") or [])
            evidence.append("切变轴按弧长重采样并进行稳健低通平滑，去除逐格点锯齿而保留天气尺度弯曲")
            system["evidence"] = evidence
        output.append(system)
    return output


def _contour_tip_candidates(
    z500: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    support_mask: np.ndarray,
    center_lon: float,
    center_lat: float,
) -> tuple[float, float, list[dict[str, float]]]:
    z = np.asarray(z500, dtype=float)
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    mask = np.asarray(support_mask, dtype=bool)
    if z.shape != (lat_values.size, lon_values.size) or mask.shape != z.shape:
        return float("nan"), 40.0, []

    if lat_values.size > 1 and lat_values[0] > lat_values[-1]:
        lat_values = lat_values[::-1]
        z = z[::-1, :]
        mask = mask[::-1, :]
    if lon_values.size > 1 and lon_values[0] > lon_values[-1]:
        lon_values = lon_values[::-1]
        z = z[:, ::-1]
        mask = mask[:, ::-1]

    smooth = _nan_gaussian(np.where(mask, z, np.nan), (0.75, 0.75))
    finite = smooth[np.isfinite(smooth)]
    if finite.size < 20:
        return float("nan"), 40.0, []
    interval = 4.0 if float(np.nanmedian(np.abs(finite))) < 1000.0 else 40.0
    level_min = np.ceil(float(np.nanmin(finite)) / interval) * interval
    level_max = np.floor(float(np.nanmax(finite)) / interval) * interval
    levels = np.arange(level_min, level_max + interval * 0.25, interval)
    if levels.size == 0:
        return float("nan"), interval, []

    y_index = int(np.argmin(np.abs(lat_values - center_lat)))
    x_index = int(np.argmin(np.abs(lon_values - center_lon)))
    center_height = float(smooth[y_index, x_index])

    try:
        from matplotlib.figure import Figure

        figure = Figure(figsize=(2.0, 2.0))
        axis = figure.subplots()
        contour_set = axis.contour(
            lon_values,
            lat_values,
            np.ma.masked_invalid(smooth),
            levels=levels,
        )
    except Exception:
        return center_height, interval, []

    tips: list[dict[str, float]] = []
    cos_lat = max(float(np.cos(np.deg2rad(center_lat))), 0.20)
    try:
        for level, segments in zip(contour_set.levels, contour_set.allsegs):
            best: tuple[float, float, float, float] | None = None
            for segment in segments:
                coordinates = np.asarray(segment, dtype=float)
                if coordinates.ndim != 2 or coordinates.shape[0] < 9:
                    continue
                distance = np.hypot(
                    (coordinates[:, 0] - center_lon) * cos_lat,
                    coordinates[:, 1] - center_lat,
                )
                if float(np.nanmin(distance)) > 18.0:
                    continue
                inside = (
                    (coordinates[:, 0] >= center_lon - 18.0)
                    & (coordinates[:, 0] <= center_lon + 18.0)
                    & (coordinates[:, 1] >= center_lat - 20.0)
                    & (coordinates[:, 1] <= center_lat + 16.0)
                )
                for index in np.where(inside)[0]:
                    radius = max(3, min(8, coordinates.shape[0] // 12))
                    if index - radius < 0 or index + radius >= coordinates.shape[0]:
                        continue
                    latitude_window = coordinates[index - radius : index + radius + 1, 1]
                    if coordinates[index, 1] > float(np.nanmin(latitude_window)) + 1.0e-6:
                        continue
                    left = float(np.nanmean(coordinates[index - radius : index, 1]))
                    right = float(np.nanmean(coordinates[index + 1 : index + radius + 1, 1]))
                    prominence = min(left, right) - float(coordinates[index, 1])
                    if prominence < 0.15:
                        continue
                    point_distance = float(distance[index])
                    score = (
                        prominence
                        + 0.02 * max(0.0, center_lat - float(coordinates[index, 1]))
                        - 0.01 * point_distance
                    )
                    candidate = (
                        score,
                        prominence,
                        float(coordinates[index, 0]),
                        float(coordinates[index, 1]),
                    )
                    if best is None or candidate > best:
                        best = candidate
            if best is not None:
                tips.append(
                    {
                        "level": float(level),
                        "score": float(best[0]),
                        "prominence_deg": float(best[1]),
                        "lon": float(best[2]),
                        "lat": float(best[3]),
                    }
                )
    finally:
        figure.clear()
    return center_height, interval, tips


def _pchip_axis(points: list[list[float]], output_points: int = 24) -> np.ndarray | None:
    coordinates = np.asarray(points, dtype=float)
    coordinates = coordinates[np.isfinite(coordinates).all(axis=1)]
    if coordinates.shape[0] < 3:
        return None
    coordinates = coordinates[np.argsort(coordinates[:, 1])]
    _, unique = np.unique(np.round(coordinates[:, 1], 5), return_index=True)
    coordinates = coordinates[np.sort(unique)]
    if coordinates.shape[0] < 3 or float(np.ptp(coordinates[:, 1])) < 2.5:
        return None
    latitude = np.linspace(
        float(coordinates[:, 1].min()),
        float(coordinates[:, 1].max()),
        max(12, int(output_points)),
    )
    longitude = PchipInterpolator(
        coordinates[:, 1],
        coordinates[:, 0],
        extrapolate=False,
    )(latitude)
    output = np.column_stack([longitude, latitude])
    output[:, 0] = np.clip(
        output[:, 0],
        float(np.nanmin(coordinates[:, 0]) - 0.4),
        float(np.nanmax(coordinates[:, 0]) + 0.4),
    )
    return _remove_close_points(output, min_step_km=22.0)


def _branch_axis_from_tips(
    system: dict[str, Any],
    center_height: float,
    interval: float,
    tips: list[dict[str, float]],
) -> tuple[np.ndarray | None, list[dict[str, float]]]:
    source = str(system.get("candidate_source") or "")
    center = system.get("closed_low_center") or []
    original = _line_coordinates(system)
    if len(center) < 2 or original.shape[0] < 2 or not np.isfinite(center_height):
        return None, []
    center_lon, center_lat = float(center[0]), float(center[1])
    anchor = float(np.ceil(center_height / interval) * interval)
    original_min_lat = float(np.nanmin(original[:, 1]))
    original_max_lat = float(np.nanmax(original[:, 1]))

    if source == "closed_low_south_branch":
        selected = [
            item
            for item in tips
            if item["level"] >= anchor - interval * 0.05
            and original_min_lat - 0.8 <= item["lat"] <= center_lat + 1.0
        ]
        selected.sort(key=lambda item: item["level"])
        latitude_direction = -1
    elif source == "closed_low_north_branch":
        selected = [
            item
            for item in tips
            if item["level"] < anchor - interval * 0.05
            and center_lat + 0.8 <= item["lat"] <= original_max_lat + 1.5
        ]
        selected.sort(key=lambda item: item["level"], reverse=True)
        latitude_direction = 1
    else:
        return None, []

    accepted: list[dict[str, float]] = []
    previous_lon, previous_lat = center_lon, center_lat
    previous_level: float | None = None
    for item in selected:
        if previous_level is not None and abs(float(item["level"] - previous_level)) > interval * 1.6:
            break
        latitude_delta = float(item["lat"] - previous_lat)
        if latitude_direction < 0 and latitude_delta >= -0.15:
            continue
        if latitude_direction > 0 and latitude_delta <= 0.15:
            continue
        longitude_jump = abs(float(item["lon"] - previous_lon))
        if longitude_jump > max(6.0, 2.0 * abs(latitude_delta) + 2.0):
            continue
        accepted.append(item)
        previous_lon, previous_lat = float(item["lon"]), float(item["lat"])
        previous_level = float(item["level"])

    if len(accepted) < 2:
        return None, accepted
    points = [[center_lon, center_lat], *[[item["lon"], item["lat"]] for item in accepted]]
    return _pchip_axis(points), accepted


def refine_trough_systems_with_z500(
    systems: Iterable[dict[str, Any]],
    z500: np.ndarray,
    lat: Iterable[float],
    lon: Iterable[float],
    *,
    support_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Rebuild closed-low branches from the equatorward tips of Z500 contours."""
    output = [deepcopy(item) for item in systems]
    closed = [
        item
        for item in output
        if str(item.get("candidate_source") or "").startswith("closed_low_")
    ]
    if not closed:
        return output

    lat_values = np.asarray(list(lat), dtype=float)
    lon_values = np.asarray(list(lon), dtype=float)
    z = np.asarray(z500, dtype=float)
    mask = np.isfinite(z) if support_mask is None else np.asarray(support_mask, dtype=bool)
    cache: dict[
        tuple[float, float],
        tuple[float, float, list[dict[str, float]]],
    ] = {}

    refined: list[dict[str, Any]] = []
    for system in output:
        source = str(system.get("candidate_source") or "")
        center = system.get("closed_low_center") or []
        if not source.startswith("closed_low_") or len(center) < 2:
            refined.append(system)
            continue
        key = (round(float(center[0]), 3), round(float(center[1]), 3))
        if key not in cache:
            cache[key] = _contour_tip_candidates(
                z,
                lat_values,
                lon_values,
                mask,
                float(center[0]),
                float(center[1]),
            )
        center_height, interval, tips = cache[key]
        axis, accepted = _branch_axis_from_tips(system, center_height, interval, tips)
        if axis is None:
            refined.append(system)
            continue

        geometry = dict(system.get("geometry") or {})
        geometry["coordinates"] = [[float(x), float(y)] for x, y in axis]
        system["geometry"] = geometry
        system["axis_length_km"] = round(float(_haversine_length_km(axis)), 1)
        system["method_detail"] = "equatorward_z500_contour_tip_family_v5"
        system["geometry_refinement_version"] = GEOMETRY_REFINEMENT_VERSION
        metrics = dict(system.get("path_metrics") or {})
        metrics.update(
            {
                "contour_tip_level_count": len(accepted),
                "contour_tip_prominence_mean_deg": round(
                    float(np.mean([item["prominence_deg"] for item in accepted])),
                    4,
                ),
                "contour_interval": float(interval),
            }
        )
        system["path_metrics"] = metrics
        system["contour_tip_levels"] = [float(item["level"]) for item in accepted]
        evidence = list(system.get("evidence") or [])
        evidence.append("闭合低涡槽支改由相邻Z500等值线向赤道凹陷的槽尖族连接，轴线直接服从高度场形态")
        system["evidence"] = evidence
        refined.append(system)
    return refined


def install_sounding_geometry_refinements() -> None:
    """Patch only the sounding multi-track product before direct imports occur."""
    from weather_diag.features import sounding_trough_paths as target

    if getattr(target, "_z500_contour_geometry_v5_installed", False):
        return
    original_detect = target.detect_sounding_multitrack_troughs
    original_merge = target.merge_shear_systems

    def detect_with_contour_geometry(
        z500,
        u500,
        v500,
        lat,
        lon,
        *,
        support_distance_km=None,
        support_mask=None,
        confidence=0.72,
        config=None,
    ):
        systems = original_detect(
            z500,
            u500,
            v500,
            lat,
            lon,
            support_distance_km=support_distance_km,
            support_mask=support_mask,
            confidence=confidence,
            config=config,
        )
        return refine_trough_systems_with_z500(
            systems,
            z500,
            lat,
            lon,
            support_mask=support_mask,
        )

    def merge_with_smooth_geometry(
        systems,
        supplement,
        *,
        duplicate_distance_km=180.0,
    ):
        merged = original_merge(
            systems,
            supplement,
            duplicate_distance_km=duplicate_distance_km,
        )
        return smooth_shear_systems(merged)

    detect_with_contour_geometry._z500_contour_geometry_v5 = True
    merge_with_smooth_geometry._sounding_shear_smoothing_v5 = True
    target.detect_sounding_multitrack_troughs = detect_with_contour_geometry
    target.merge_shear_systems = merge_with_smooth_geometry
    target._z500_contour_geometry_v5_installed = True
