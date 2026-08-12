from __future__ import annotations

import numpy as np
from scipy import interpolate, ndimage

from weather_diag.io.geojson import line_feature


def _nan_smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    if sigma <= 0:
        return arr.copy()
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=out, where=weight_sum > 1e-6)
    return out


def _lon_km_per_degree(lat: np.ndarray) -> np.ndarray:
    return 111.32 * np.maximum(np.cos(np.deg2rad(lat)), 0.2)


def _laplacian_metric(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    first_y = np.gradient(field, lat, axis=0, edge_order=1) / 111.32
    first_x = np.gradient(field, lon, axis=1, edge_order=1) / _lon_km_per_degree(lat)[:, None]
    second_y = np.gradient(first_y, lat, axis=0, edge_order=1) / 111.32
    second_x = np.gradient(first_x, lon, axis=1, edge_order=1) / _lon_km_per_degree(lat)[:, None]
    return second_x + second_y


def _field_derivatives_metric(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, ...]:
    lon_scale = _lon_km_per_degree(lat)[:, None]
    zy = np.gradient(field, lat, axis=0, edge_order=1) / 111.32
    zx = np.gradient(field, lon, axis=1, edge_order=1) / lon_scale
    zyy = np.gradient(zy, lat, axis=0, edge_order=1) / 111.32
    zxx = np.gradient(zx, lon, axis=1, edge_order=1) / lon_scale
    zxy = np.gradient(zx, lat, axis=0, edge_order=1) / 111.32
    return zx, zy, zxx, zyy, zxy


def _contour_curvature(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    zx, zy, zxx, zyy, zxy = _field_derivatives_metric(field, lat, lon)
    grad_sq = zx**2 + zy**2
    numerator = zxx * zy**2 - 2.0 * zxy * zx * zy + zyy * zx**2
    curvature = np.zeros_like(field, dtype=float)
    np.divide(numerator, np.maximum(grad_sq, 1e-12) ** 1.5, out=curvature, where=np.isfinite(numerator))
    return curvature, np.sqrt(grad_sq)


def _finite_percentile(values: np.ndarray, percentile: float, default: float = 0.0) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return default
    return float(np.nanpercentile(valid, percentile))


def _scale01(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros_like(arr, dtype=float)
    lo = float(np.nanmin(valid))
    hi = float(np.nanmax(valid))
    if not np.isfinite(hi - lo) or abs(hi - lo) < 1e-12:
        return np.zeros_like(arr, dtype=float)
    return np.clip((arr - lo) / (hi - lo), 0.0, 1.0)


def _percentile_score(values: np.ndarray, lower: float = 50.0, upper: float = 90.0) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros_like(arr, dtype=float)
    lo = float(np.nanpercentile(valid, lower))
    hi = float(np.nanpercentile(valid, upper))
    if not np.isfinite(hi - lo) or abs(hi - lo) < 1e-12:
        return np.zeros_like(arr, dtype=float)
    score = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    return np.where(np.isfinite(score), score, 0.0)


def _shift_with_nan(field: np.ndarray, dy: int, dx: int) -> np.ndarray:
    shifted = np.full_like(field, np.nan, dtype=float)
    if dy >= 0:
        src_y = slice(0, field.shape[0] - dy)
        dst_y = slice(dy, field.shape[0])
    else:
        src_y = slice(-dy, field.shape[0])
        dst_y = slice(0, field.shape[0] + dy)
    if dx >= 0:
        src_x = slice(0, field.shape[1] - dx)
        dst_x = slice(dx, field.shape[1])
    else:
        src_x = slice(-dx, field.shape[1])
        dst_x = slice(0, field.shape[1] + dx)
    shifted[dst_y, dst_x] = field[src_y, src_x]
    return shifted


def _directional_extreme_score(field: np.ndarray, *, mode: str, radius_grid: int = 2) -> np.ndarray:
    score = np.zeros_like(field, dtype=float)
    directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for radius in range(1, max(1, radius_grid) + 1):
        for dy, dx in directions:
            plus = _shift_with_nan(field, dy * radius, dx * radius)
            minus = _shift_with_nan(field, -dy * radius, -dx * radius)
            if mode == "trough":
                candidate = np.minimum(plus - field, minus - field)
            else:
                candidate = np.minimum(field - plus, field - minus)
            score = np.nanmax(np.stack([score, np.where(candidate > 0.0, candidate, 0.0)]), axis=0)
    return np.where(np.isfinite(score), score, 0.0)


def _line_length(coords: np.ndarray) -> float:
    if coords.shape[0] < 2:
        return 0.0
    return float(np.sum(np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))))


def _resample_line(coords: np.ndarray, count: int) -> np.ndarray:
    if coords.shape[0] == 0:
        return coords
    if coords.shape[0] == 1:
        return np.repeat(coords, count, axis=0)
    segments = np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))
    distance = np.concatenate([[0.0], np.cumsum(segments)])
    total = float(distance[-1])
    if total <= 1e-9:
        return np.repeat(coords[:1], count, axis=0)
    target = np.linspace(0.0, total, count)
    return np.column_stack(
        [
            np.interp(target, distance, coords[:, 0]),
            np.interp(target, distance, coords[:, 1]),
        ]
    )


def _smooth_line(coords: list[list[float]], *, count: int, smooth_factor: float) -> np.ndarray:
    arr = np.asarray(coords, dtype=float)
    if arr.shape[0] < 3:
        return _resample_line(arr, count)

    _, unique_idx = np.unique(np.round(arr, 8), axis=0, return_index=True)
    arr = arr[np.sort(unique_idx)]
    if arr.shape[0] < 3:
        return _resample_line(arr, count)

    median_step = np.nanmedian(np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1])))
    if not np.isfinite(median_step) or median_step <= 0:
        return _resample_line(arr, count)
    try:
        spline, _ = interpolate.splprep(
            [arr[:, 0], arr[:, 1]],
            s=float(smooth_factor * arr.shape[0] * median_step**2),
            k=min(3, arr.shape[0] - 1),
        )
        u_new = np.linspace(0.0, 1.0, count)
        smoothed = interpolate.splev(u_new, spline)
        return np.column_stack(smoothed)
    except (ValueError, TypeError, RuntimeError):
        return _resample_line(arr, count)


def _snap_line_to_score(
    coords: np.ndarray,
    score: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    search_radius_grid: int,
) -> np.ndarray:
    snapped = []
    for lon_value, lat_value in coords:
        y0 = int(np.nanargmin(np.abs(lat - lat_value)))
        x0 = int(np.nanargmin(np.abs(lon - lon_value)))
        y_min = max(0, y0 - search_radius_grid)
        y_max = min(score.shape[0], y0 + search_radius_grid + 1)
        x_min = max(0, x0 - search_radius_grid)
        x_max = min(score.shape[1], x0 + search_radius_grid + 1)
        window = score[y_min:y_max, x_min:x_max]
        if window.size == 0 or not np.isfinite(window).any():
            snapped.append([float(lon_value), float(lat_value)])
            continue
        ys, xs = np.indices(window.shape)
        dist = np.hypot(ys + y_min - y0, xs + x_min - x0)
        value = np.where(np.isfinite(window), window, -np.inf) - 0.12 * dist
        best = int(np.nanargmax(value))
        wy, wx = np.unravel_index(best, window.shape)
        snapped.append([float(lon[x_min + wx]), float(lat[y_min + wy])])
    return np.asarray(snapped, dtype=float)


def _orient_axis(coords: list[list[float]]) -> list[list[float]]:
    if len(coords) < 2:
        return coords
    lon_span = abs(max(point[0] for point in coords) - min(point[0] for point in coords))
    lat_span = abs(max(point[1] for point in coords) - min(point[1] for point in coords))
    if lat_span >= lon_span and coords[0][1] > coords[-1][1]:
        coords.reverse()
    elif lon_span > lat_span and coords[0][0] > coords[-1][0]:
        coords.reverse()
    return coords


def _clean_coordinates(coords: np.ndarray) -> list[list[float]]:
    cleaned: list[list[float]] = []
    for lon_value, lat_value in coords:
        if not np.isfinite([lon_value, lat_value]).all():
            continue
        point = [float(lon_value), float(lat_value)]
        if cleaned and np.allclose(cleaned[-1], point):
            continue
        cleaned.append(point)
    return _orient_axis(cleaned)


def _axis_coordinates(
    ys: np.ndarray,
    xs: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    weights: np.ndarray,
    *,
    max_points: int = 64,
) -> list[list[float]]:
    coords = np.column_stack([lon[xs], lat[ys]]).astype(float)
    finite = np.isfinite(coords).all(axis=1)
    coords = coords[finite]
    weights = np.asarray(weights, dtype=float)[finite]
    if coords.shape[0] == 0:
        return []
    if coords.shape[0] == 1:
        return [[float(coords[0, 0]), float(coords[0, 1])]]

    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1.0)
    center = np.average(coords, axis=0, weights=weights)
    centered = coords - center
    try:
        _, _, vh = np.linalg.svd(centered * np.sqrt(weights[:, None]), full_matrices=False)
        axis = vh[0]
    except np.linalg.LinAlgError:
        axis = np.array([0.0, 1.0])
    projection = centered @ axis
    p_min = float(np.nanmin(projection))
    p_max = float(np.nanmax(projection))
    if np.isclose(p_min, p_max):
        ordered = coords[np.argsort(projection)]
    else:
        bin_count = min(max_points, max(4, int(np.ceil(np.sqrt(coords.shape[0]) * 2))))
        bins = np.linspace(p_min, p_max, bin_count + 1)
        parts = []
        for left, right in zip(bins[:-1], bins[1:]):
            if right == bins[-1]:
                mask = (projection >= left) & (projection <= right)
            else:
                mask = (projection >= left) & (projection < right)
            if np.any(mask):
                parts.append(np.average(coords[mask], axis=0, weights=weights[mask]))
        ordered = np.asarray(parts, dtype=float)

    cleaned: list[list[float]] = []
    for lon_value, lat_value in ordered:
        point = [float(lon_value), float(lat_value)]
        if cleaned and np.allclose(cleaned[-1], point):
            continue
        cleaned.append(point)
    if len(cleaned) >= 2:
        lon_span = abs(max(point[0] for point in cleaned) - min(point[0] for point in cleaned))
        lat_span = abs(max(point[1] for point in cleaned) - min(point[1] for point in cleaned))
        if lat_span >= lon_span and cleaned[0][1] > cleaned[-1][1]:
            cleaned.reverse()
        elif lon_span > lat_span and cleaned[0][0] > cleaned[-1][0]:
            cleaned.reverse()
    return cleaned


def _scored_axis_coordinates(
    ys: np.ndarray,
    xs: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    score: np.ndarray,
    weights: np.ndarray,
    *,
    max_points: int = 64,
) -> list[list[float]]:
    coords = np.column_stack([lon[xs], lat[ys]]).astype(float)
    finite = np.isfinite(coords).all(axis=1)
    coords = coords[finite]
    raw_score = np.asarray(score[ys, xs], dtype=float)[finite]
    raw_weights = np.asarray(weights, dtype=float)[finite]
    if coords.shape[0] == 0:
        return []
    if coords.shape[0] == 1:
        return [[float(coords[0, 0]), float(coords[0, 1])]]

    axis_weights = np.where(np.isfinite(raw_score) & (raw_score > 0), raw_score, 0.05)
    axis_weights += np.where(np.isfinite(raw_weights) & (raw_weights > 0), 0.15 * raw_weights, 0.0)
    center = np.average(coords, axis=0, weights=axis_weights)
    centered = coords - center
    try:
        _, _, vh = np.linalg.svd(centered * np.sqrt(axis_weights[:, None]), full_matrices=False)
        axis = vh[0]
    except np.linalg.LinAlgError:
        axis = np.array([0.0, 1.0])

    projection = centered @ axis
    p_min = float(np.nanmin(projection))
    p_max = float(np.nanmax(projection))
    if np.isclose(p_min, p_max):
        ordered = coords[np.argsort(projection)]
    else:
        bin_count = min(max_points, max(6, int(np.ceil(np.sqrt(coords.shape[0]) * 2))))
        bins = np.linspace(p_min, p_max, bin_count + 1)
        parts = []
        for left, right in zip(bins[:-1], bins[1:]):
            if right == bins[-1]:
                mask = (projection >= left) & (projection <= right)
            else:
                mask = (projection >= left) & (projection < right)
            if not np.any(mask):
                continue
            local_idx = np.where(mask)[0]
            local_score = raw_score[local_idx]
            if np.isfinite(local_score).any():
                cutoff = float(np.nanpercentile(local_score, 70.0))
                selected = local_idx[local_score >= cutoff]
                if selected.size == 0:
                    selected = local_idx[[int(np.nanargmax(local_score))]]
            else:
                selected = local_idx
            selected_weights = np.where(
                np.isfinite(raw_score[selected]) & (raw_score[selected] > 0),
                raw_score[selected],
                0.05,
            )
            parts.append(np.average(coords[selected], axis=0, weights=selected_weights))
        ordered = np.asarray(parts, dtype=float)

    cleaned = _clean_coordinates(ordered)
    if len(cleaned) < 3:
        return _axis_coordinates(ys, xs, lat, lon, weights, max_points=max_points)

    output_count = min(max_points, max(32, len(cleaned) * 3))
    smooth = _smooth_line(cleaned, count=output_count, smooth_factor=0.18)
    snapped = _snap_line_to_score(smooth, score, lat, lon, search_radius_grid=2)
    final = _smooth_line(_clean_coordinates(snapped), count=output_count, smooth_factor=0.08)
    return _clean_coordinates(final)


def _candidate_components(
    mask: np.ndarray,
    *,
    min_points: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    structure = np.ones((3, 3), dtype=int)
    labels, count = ndimage.label(mask, structure=structure)
    components = []
    for label_id in range(1, count + 1):
        ys, xs = np.where(labels == label_id)
        if ys.size >= min_points:
            components.append((ys, xs))
    return components


def trough_ridge_axis_candidates(
    anom: np.ndarray,
    lat,
    lon,
    *,
    mode: str,
    percentile: float,
    min_points: int,
    max_lines: int,
    curvature_percentile: float = 55.0,
    smoothing_sigma: float = 1.0,
    vorticity: np.ndarray | None = None,
) -> list[dict]:
    if mode not in {"trough", "ridge"}:
        raise ValueError("mode must be trough or ridge")

    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    anom_arr = np.asarray(anom, dtype=float)
    smooth = _nan_smooth(anom_arr, smoothing_sigma)
    laplacian = _laplacian_metric(smooth, lat_arr, lon_arr)
    contour_curvature, grad_mag = _contour_curvature(smooth, lat_arr, lon_arr)
    curvature_support = np.maximum(laplacian if mode == "trough" else -laplacian, np.abs(contour_curvature))
    threshold = (
        _finite_percentile(smooth, percentile)
        if mode == "trough"
        else _finite_percentile(smooth, 100.0 - percentile)
    )
    tail_mask = smooth <= threshold if mode == "trough" else smooth >= threshold
    local_extreme = _directional_extreme_score(smooth, mode=mode, radius_grid=2)

    curvature_threshold = max(0.0, _finite_percentile(curvature_support, curvature_percentile))
    curvature_mask = curvature_support > curvature_threshold
    base_mask = tail_mask & curvature_mask & np.isfinite(smooth)
    intensity_grid = threshold - smooth if mode == "trough" else smooth - threshold
    local_score = _percentile_score(local_extreme, 50.0, 90.0)
    curvature_score = _percentile_score(np.maximum(curvature_support, 0.0), 50.0, 90.0)
    intensity_score = _percentile_score(np.maximum(intensity_grid, 0.0), 50.0, 90.0)
    gradient_score = _percentile_score(grad_mag, 50.0, 90.0)
    method = "curvature_component_axis"
    components = _candidate_components(base_mask, min_points=min_points)
    if not components:
        method = "anomaly_component_axis"
        components = _candidate_components(tail_mask & np.isfinite(smooth), min_points=min_points)

    candidates = []
    vorticity_support = None
    if vorticity is not None:
        vort = np.asarray(vorticity, dtype=float)
        vorticity_support = vort if mode == "trough" else -vort
    vort_score = (
        _percentile_score(np.maximum(vorticity_support, 0.0), 50.0, 90.0)
        if vorticity_support is not None
        else None
    )

    for ys, xs in components:
        intensity = threshold - smooth[ys, xs] if mode == "trough" else smooth[ys, xs] - threshold
        curvature_values = curvature_support[ys, xs]
        axis_score = (
            0.40 * local_score
            + 0.25 * curvature_score
            + 0.25 * intensity_score
            + 0.10 * gradient_score
        )
        weights = 1.0 + _scale01(intensity) + _scale01(np.maximum(curvature_values, 0.0))
        if vorticity_support is not None and vort_score is not None:
            axis_score = (
                0.34 * local_score
                + 0.22 * curvature_score
                + 0.22 * intensity_score
                + 0.12 * vort_score
                + 0.10 * gradient_score
            )
            weights = weights + 0.5 * _scale01(np.maximum(vorticity_support[ys, xs], 0.0))
        coords = _scored_axis_coordinates(ys, xs, lat_arr, lon_arr, axis_score, weights)
        if len(coords) < 2:
            continue
        values = anom_arr[ys, xs]
        lons = [coord[0] for coord in coords]
        lats = [coord[1] for coord in coords]
        axis_length = float(
            np.sum(
                np.hypot(
                    np.diff([coord[0] for coord in coords]),
                    np.diff([coord[1] for coord in coords]),
                )
            )
        )
        vort_mean = None
        if vorticity_support is not None:
            support_values = vorticity_support[ys, xs]
            if np.isfinite(support_values).any():
                vort_mean = float(np.nanmean(support_values))
        candidates.append(
            {
                "rank": 0,
                "mode": mode,
                "method": method,
                "coordinates": coords,
                "bbox": [min(lons), min(lats), max(lons), max(lats)],
                "point_count": int(ys.size),
                "axis_length": axis_length,
                "threshold_value": threshold,
                "curvature_threshold": curvature_threshold,
                "curvature_mean": float(np.nanmean(curvature_values)),
                "vorticity_support_mean": vort_mean,
                "min_value": float(np.nanmin(values)),
                "max_value": float(np.nanmax(values)),
                "mean_value": float(np.nanmean(values)),
            }
        )

    candidates.sort(
        key=lambda item: (item["axis_length"], item["point_count"], abs(item["mean_value"])),
        reverse=True,
    )
    for rank, candidate in enumerate(candidates[:max_lines], start=1):
        candidate["rank"] = rank
    return candidates[:max_lines]


def _candidate_lines_from_anomaly(
    anom: np.ndarray,
    lat,
    lon,
    *,
    mode: str,
    percentile: float,
    min_points: int,
    max_lines: int,
    curvature_percentile: float,
    smoothing_sigma: float,
    vorticity: np.ndarray | None = None,
):
    features = []
    for candidate in trough_ridge_axis_candidates(
        anom,
        lat,
        lon,
        mode=mode,
        percentile=percentile,
        min_points=min_points,
        max_lines=max_lines,
        curvature_percentile=curvature_percentile,
        smoothing_sigma=smoothing_sigma,
        vorticity=vorticity,
    ):
        feature_type = "trough" if mode == "trough" else "ridge"
        title = "500hPa 槽线" if mode == "trough" else "500hPa 脊线"
        evidence = [
            "500hPa 位势高度距平达到尾部分位",
            "轴线位于高度场曲率支撑的连续槽脊带内",
        ]
        if candidate["vorticity_support_mean"] is not None:
            evidence.append("500hPa 相对涡度符号与槽脊性质一致")
        features.append(
            line_feature(
                candidate["coordinates"],
                {
                    "id": f"{feature_type}_{candidate['rank']:03d}",
                    "feature_type": feature_type,
                    "title": title,
                    "level": "500hPa",
                    "confidence": 0.68 if candidate["method"] == "curvature_component_axis" else 0.56,
                    "method": candidate["method"],
                    "point_count": candidate["point_count"],
                    "axis_length": candidate["axis_length"],
                    "threshold_value": candidate["threshold_value"],
                    "curvature_mean": candidate["curvature_mean"],
                    "vorticity_support_mean": candidate["vorticity_support_mean"],
                    "evidence": evidence,
                },
            )
        )
    return features


def detect_trough_ridge(
    z500: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    vorticity500: np.ndarray | None = None,
) -> tuple[list[dict], list[dict]]:
    cfg = thresholds.get("trough_ridge", {})
    percentile = float(cfg.get("anomaly_percentile", 20))
    curvature_percentile = float(cfg.get("curvature_percentile", 55))
    smoothing_sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    min_points = int(cfg.get("min_points_per_line", 4))
    max_lines = int(cfg.get("max_lines", 8))
    anom = z500 - np.nanmean(z500, axis=1, keepdims=True)
    troughs = _candidate_lines_from_anomaly(
        anom,
        lat,
        lon,
        mode="trough",
        percentile=percentile,
        min_points=min_points,
        max_lines=max_lines,
        curvature_percentile=curvature_percentile,
        smoothing_sigma=smoothing_sigma,
        vorticity=vorticity500,
    )
    ridges = _candidate_lines_from_anomaly(
        anom,
        lat,
        lon,
        mode="ridge",
        percentile=percentile,
        min_points=min_points,
        max_lines=max_lines,
        curvature_percentile=curvature_percentile,
        smoothing_sigma=smoothing_sigma,
        vorticity=vorticity500,
    )
    return troughs, ridges
