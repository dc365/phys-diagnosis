from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class ObjectiveAnalysisConfig:
    """Configuration for station-to-grid objective analysis.

    The defaults are intentionally synoptic-scale. Radiosonde stations are not
    dense enough for mesoscale interpolation over 5-55N/50-160E, so this module
    uses successive-correction Barnes-style analysis instead of a triangulated
    linear field plus nearest fill. The returned field keeps a support-distance
    mask so downstream contours can suppress weakly observed areas.
    """

    radii_km: tuple[float, ...] = (720.0, 480.0, 300.0)
    smoothing_sigma_grid: float = 0.65
    max_support_distance_km: float = 520.0
    min_station_count: int = 3
    min_weight_sum: float = 1.0e-6
    distance_exponent: float = 1.0


@dataclass
class ObjectiveField:
    values: np.ndarray
    support_distance_km: np.ndarray
    support_mask: np.ndarray
    quality: dict[str, Any]


def _lonlat_to_xy_km(lon: np.ndarray, lat: np.ndarray, *, ref_lon: float, ref_lat: float) -> tuple[np.ndarray, np.ndarray]:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    x = (lon_arr - ref_lon) * 111.32 * max(float(np.cos(np.deg2rad(ref_lat))), 0.2)
    y = (lat_arr - ref_lat) * 111.32
    return x, y


def _station_points(frame: pd.DataFrame, value_column: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    rows = frame[["station_lon", "station_lat", value_column]].copy()
    rows = rows.apply(pd.to_numeric, errors="coerce").dropna()
    rows = rows.drop_duplicates(subset=["station_lon", "station_lat"], keep="last")
    points = rows[["station_lon", "station_lat"]].to_numpy(dtype=float)
    values = rows[value_column].to_numpy(dtype=float)
    return points[:, 0] if len(rows) else np.array([]), points[:, 1] if len(rows) else np.array([]), values, rows


def _distance_matrix_km(
    station_lon: np.ndarray,
    station_lat: np.ndarray,
    grid_lon2d: np.ndarray,
    grid_lat2d: np.ndarray,
) -> np.ndarray:
    ref_lon = float(np.nanmedian(station_lon)) if station_lon.size else float(np.nanmedian(grid_lon2d))
    ref_lat = float(np.nanmedian(station_lat)) if station_lat.size else float(np.nanmedian(grid_lat2d))
    sx, sy = _lonlat_to_xy_km(station_lon, station_lat, ref_lon=ref_lon, ref_lat=ref_lat)
    gx, gy = _lonlat_to_xy_km(grid_lon2d.ravel(), grid_lat2d.ravel(), ref_lon=ref_lon, ref_lat=ref_lat)
    dx = gx[:, None] - sx[None, :]
    dy = gy[:, None] - sy[None, :]
    return np.hypot(dx, dy)


def _weighted_grid_average(
    values: np.ndarray,
    distance_km: np.ndarray,
    *,
    radius_km: float,
    min_weight_sum: float,
    distance_exponent: float,
    shape: tuple[int, int],
) -> np.ndarray:
    if values.size == 0:
        return np.full(shape, np.nan, dtype=float)
    radius = max(float(radius_km), 1.0)
    weights = np.exp(-((distance_km / radius) ** 2) * float(distance_exponent))
    finite = np.isfinite(values)
    weights[:, ~finite] = 0.0
    weight_sum = weights.sum(axis=1)
    weighted_sum = weights @ np.where(finite, values, 0.0)
    out = np.full(weight_sum.shape, np.nan, dtype=float)
    np.divide(weighted_sum, weight_sum, out=out, where=weight_sum > min_weight_sum)
    return out.reshape(shape)


def _sample_grid_at_points(field: np.ndarray, lat: np.ndarray, lon: np.ndarray, point_lat: np.ndarray, point_lon: np.ndarray) -> np.ndarray:
    valid_field = np.asarray(field, dtype=float)
    filled = valid_field.copy()
    if not np.isfinite(filled).all():
        finite_values = filled[np.isfinite(filled)]
        fill_value = float(np.nanmean(finite_values)) if finite_values.size else 0.0
        filled = np.where(np.isfinite(filled), filled, fill_value)
    interpolator = RegularGridInterpolator(
        (np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)),
        filled,
        bounds_error=False,
        fill_value=np.nan,
    )
    return interpolator(np.column_stack([point_lat, point_lon]))


def _smooth_nan(field: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return np.asarray(field, dtype=float)
    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def _support_distance(
    station_lon: np.ndarray,
    station_lat: np.ndarray,
    grid_lon2d: np.ndarray,
    grid_lat2d: np.ndarray,
) -> np.ndarray:
    if station_lon.size == 0:
        return np.full(grid_lon2d.shape, np.nan, dtype=float)
    ref_lon = float(np.nanmedian(station_lon))
    ref_lat = float(np.nanmedian(station_lat))
    sx, sy = _lonlat_to_xy_km(station_lon, station_lat, ref_lon=ref_lon, ref_lat=ref_lat)
    gx, gy = _lonlat_to_xy_km(grid_lon2d.ravel(), grid_lat2d.ravel(), ref_lon=ref_lon, ref_lat=ref_lat)
    tree = cKDTree(np.column_stack([sx, sy]))
    distance, _ = tree.query(np.column_stack([gx, gy]), k=1)
    return distance.reshape(grid_lon2d.shape)


def objective_analysis_field(
    frame: pd.DataFrame,
    value_column: str,
    lat: Iterable[float],
    lon: Iterable[float],
    *,
    config: ObjectiveAnalysisConfig | None = None,
    background: np.ndarray | None = None,
) -> ObjectiveField:
    cfg = config or ObjectiveAnalysisConfig()
    lat_arr = np.asarray(list(lat), dtype=float)
    lon_arr = np.asarray(list(lon), dtype=float)
    grid_lon2d, grid_lat2d = np.meshgrid(lon_arr, lat_arr)
    shape = grid_lon2d.shape
    station_lon, station_lat, values, rows = _station_points(frame, value_column)
    if values.size < cfg.min_station_count:
        empty = np.full(shape, np.nan, dtype=float)
        support = _support_distance(station_lon, station_lat, grid_lon2d, grid_lat2d)
        return ObjectiveField(
            values=empty,
            support_distance_km=support,
            support_mask=np.zeros(shape, dtype=bool),
            quality={
                "method": "barnes_successive_correction",
                "available": False,
                "reason": "insufficient_station_count",
                "station_count": int(values.size),
                "grid_shape": [int(shape[0]), int(shape[1])],
            },
        )

    distance_km = _distance_matrix_km(station_lon, station_lat, grid_lon2d, grid_lat2d)
    if background is not None and np.asarray(background).shape == shape:
        analysis = np.asarray(background, dtype=float).copy()
        if not np.isfinite(analysis).any():
            analysis = _weighted_grid_average(
                values,
                distance_km,
                radius_km=cfg.radii_km[0],
                min_weight_sum=cfg.min_weight_sum,
                distance_exponent=cfg.distance_exponent,
                shape=shape,
            )
    else:
        analysis = _weighted_grid_average(
            values,
            distance_km,
            radius_km=cfg.radii_km[0],
            min_weight_sum=cfg.min_weight_sum,
            distance_exponent=cfg.distance_exponent,
            shape=shape,
        )

    for radius in cfg.radii_km[1:]:
        estimate = _sample_grid_at_points(analysis, lat_arr, lon_arr, station_lat, station_lon)
        increments = values - estimate
        increments = np.where(np.isfinite(increments), increments, 0.0)
        correction = _weighted_grid_average(
            increments,
            distance_km,
            radius_km=radius,
            min_weight_sum=cfg.min_weight_sum,
            distance_exponent=cfg.distance_exponent,
            shape=shape,
        )
        analysis = np.where(np.isfinite(correction), analysis + correction, analysis)

    analysis = _smooth_nan(analysis, cfg.smoothing_sigma_grid)
    support_distance = _support_distance(station_lon, station_lat, grid_lon2d, grid_lat2d)
    support_mask = support_distance <= cfg.max_support_distance_km
    final_estimate = _sample_grid_at_points(analysis, lat_arr, lon_arr, station_lat, station_lon)
    residual = values - final_estimate
    residual = residual[np.isfinite(residual)]
    quality = {
        "method": "barnes_successive_correction",
        "available": True,
        "station_count": int(values.size),
        "grid_shape": [int(shape[0]), int(shape[1])],
        "radii_km": [float(item) for item in cfg.radii_km],
        "smoothing_sigma_grid": float(cfg.smoothing_sigma_grid),
        "max_support_distance_km": float(cfg.max_support_distance_km),
        "supported_grid_ratio": round(float(np.mean(support_mask)), 3),
        "mean_nearest_station_km": round(float(np.nanmean(support_distance)), 1),
        "max_nearest_station_km": round(float(np.nanmax(support_distance)), 1),
        "station_residual_bias": round(float(np.nanmean(residual)), 3) if residual.size else None,
        "station_residual_rmse": round(float(np.sqrt(np.nanmean(residual**2))), 3) if residual.size else None,
        "station_residual_abs_p90": round(float(np.nanpercentile(np.abs(residual), 90)), 3) if residual.size else None,
    }
    return ObjectiveField(
        values=analysis.astype(float),
        support_distance_km=support_distance.astype(float),
        support_mask=support_mask.astype(bool),
        quality=quality,
    )


def mask_unsupported(field: np.ndarray, support_mask: np.ndarray | None) -> np.ndarray:
    if support_mask is None:
        return np.asarray(field, dtype=float)
    return np.where(np.asarray(support_mask, dtype=bool), np.asarray(field, dtype=float), np.nan)
