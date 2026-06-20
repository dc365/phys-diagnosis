from __future__ import annotations

import numpy as np
from scipy import ndimage

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


def _laplacian_degrees(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    first_y = np.gradient(field, lat, axis=0, edge_order=1)
    first_x = np.gradient(field, lon, axis=1, edge_order=1)
    second_y = np.gradient(first_y, lat, axis=0, edge_order=1)
    second_x = np.gradient(first_x, lon, axis=1, edge_order=1)
    return second_x + second_y


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
    laplacian = _laplacian_degrees(smooth, lat_arr, lon_arr)
    curvature_support = laplacian if mode == "trough" else -laplacian
    threshold = (
        _finite_percentile(smooth, percentile)
        if mode == "trough"
        else _finite_percentile(smooth, 100.0 - percentile)
    )
    tail_mask = smooth <= threshold if mode == "trough" else smooth >= threshold

    curvature_threshold = max(0.0, _finite_percentile(curvature_support, curvature_percentile))
    curvature_mask = curvature_support > curvature_threshold
    base_mask = tail_mask & curvature_mask & np.isfinite(smooth)
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

    for ys, xs in components:
        intensity = threshold - smooth[ys, xs] if mode == "trough" else smooth[ys, xs] - threshold
        curvature_values = curvature_support[ys, xs]
        weights = 1.0 + _scale01(intensity) + _scale01(np.maximum(curvature_values, 0.0))
        if vorticity_support is not None:
            weights = weights + 0.5 * _scale01(np.maximum(vorticity_support[ys, xs], 0.0))
        coords = _axis_coordinates(ys, xs, lat_arr, lon_arr, weights)
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

    candidates.sort(key=lambda item: (item["axis_length"], item["point_count"], abs(item["mean_value"])), reverse=True)
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
