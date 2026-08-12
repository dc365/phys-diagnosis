from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator


EARTH_RADIUS_KM = 6371.0088


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
    correction_gains: tuple[float, ...] | None = None


@dataclass
class ObjectiveField:
    values: np.ndarray
    support_distance_km: np.ndarray
    support_mask: np.ndarray
    quality: dict[str, Any]


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
    if station_lon.size == 0:
        return np.empty((grid_lon2d.size, 0), dtype=float)
    grid_lat_rad = np.deg2rad(np.asarray(grid_lat2d, dtype=float).ravel())[:, None]
    station_lat_rad = np.deg2rad(np.asarray(station_lat, dtype=float))[None, :]
    delta_lat = station_lat_rad - grid_lat_rad
    delta_lon_deg = (
        np.asarray(station_lon, dtype=float)[None, :]
        - np.asarray(grid_lon2d, dtype=float).ravel()[:, None]
        + 180.0
    ) % 360.0 - 180.0
    delta_lon = np.deg2rad(delta_lon_deg)
    haversine = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(grid_lat_rad) * np.cos(station_lat_rad) * np.sin(delta_lon / 2.0) ** 2
    )
    haversine = np.clip(haversine, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_KM * np.arctan2(np.sqrt(haversine), np.sqrt(1.0 - haversine))


def _nearest_station_spacing_km(station_lon: np.ndarray, station_lat: np.ndarray) -> np.ndarray:
    if station_lon.size < 2:
        return np.full(station_lon.shape, np.nan, dtype=float)
    lon2d = np.asarray(station_lon, dtype=float).reshape(-1, 1)
    lat2d = np.asarray(station_lat, dtype=float).reshape(-1, 1)
    distances = _distance_matrix_km(station_lon, station_lat, lon2d, lat2d)
    np.fill_diagonal(distances, np.inf)
    return np.min(distances, axis=1)


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
    return np.min(
        _distance_matrix_km(station_lon, station_lat, grid_lon2d, grid_lat2d),
        axis=1,
    ).reshape(grid_lon2d.shape)


def _correction_gain(config: ObjectiveAnalysisConfig, radius_index: int) -> float:
    gains = config.correction_gains
    if not gains:
        return 1.0
    if radius_index < len(gains):
        return max(0.0, float(gains[radius_index]))
    return max(0.0, float(gains[-1]))


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
    station_lon, station_lat, values, _ = _station_points(frame, value_column)
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

    if not cfg.radii_km:
        raise ValueError("objective analysis requires at least one radius")

    distance_km = _distance_matrix_km(station_lon, station_lat, grid_lon2d, grid_lat2d)
    background_used = False
    if background is not None and np.asarray(background).shape == shape:
        supplied_background = np.asarray(background, dtype=float)
        background_used = bool(np.isfinite(supplied_background).any())
        first_pass = _weighted_grid_average(
            values,
            distance_km,
            radius_km=cfg.radii_km[0],
            min_weight_sum=cfg.min_weight_sum,
            distance_exponent=cfg.distance_exponent,
            shape=shape,
        )
        analysis = np.where(np.isfinite(supplied_background), supplied_background, first_pass)
    else:
        analysis = _weighted_grid_average(
            values,
            distance_km,
            radius_km=cfg.radii_km[0],
            min_weight_sum=cfg.min_weight_sum,
            distance_exponent=cfg.distance_exponent,
            shape=shape,
        )

    correction_indices = range(len(cfg.radii_km)) if background_used else range(1, len(cfg.radii_km))
    applied_radii: list[float] = []
    applied_gains: list[float] = []
    for radius_index in correction_indices:
        radius = float(cfg.radii_km[radius_index])
        gain = _correction_gain(cfg, radius_index)
        if gain <= 0.0:
            continue
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
        analysis = np.where(np.isfinite(correction), analysis + gain * correction, analysis)
        applied_radii.append(radius)
        applied_gains.append(gain)

    analysis = _smooth_nan(analysis, cfg.smoothing_sigma_grid)
    support_distance = np.min(distance_km, axis=1).reshape(shape)
    support_mask = support_distance <= cfg.max_support_distance_km
    station_spacing = _nearest_station_spacing_km(station_lon, station_lat)
    finite_spacing = station_spacing[np.isfinite(station_spacing)]
    final_estimate = _sample_grid_at_points(analysis, lat_arr, lon_arr, station_lat, station_lon)
    residual = values - final_estimate
    residual = residual[np.isfinite(residual)]
    quality = {
        "method": "barnes_successive_correction",
        "available": True,
        "station_count": int(values.size),
        "grid_shape": [int(shape[0]), int(shape[1])],
        "radii_km": [float(item) for item in cfg.radii_km],
        "correction_radii_km": applied_radii,
        "correction_gains": applied_gains,
        "background_used": background_used,
        "distance_method": "great_circle_haversine",
        "smoothing_sigma_grid": float(cfg.smoothing_sigma_grid),
        "max_support_distance_km": float(cfg.max_support_distance_km),
        "supported_grid_ratio": round(float(np.mean(support_mask)), 3),
        "mean_nearest_station_km": round(float(np.nanmean(support_distance)), 1),
        "max_nearest_station_km": round(float(np.nanmax(support_distance)), 1),
        "median_station_spacing_km": round(float(np.nanmedian(finite_spacing)), 1) if finite_spacing.size else None,
        "station_spacing_p90_km": round(float(np.nanpercentile(finite_spacing, 90)), 1) if finite_spacing.size else None,
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
