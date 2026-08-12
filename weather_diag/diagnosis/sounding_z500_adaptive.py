from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator

from weather_diag.diagnosis.objective_analysis import (
    ObjectiveAnalysisConfig,
    ObjectiveField,
    objective_analysis_field,
)


ADAPTIVE_Z500_VERSION = "sounding_z500_synoptic_v3"


def _smoothstep(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _nan_gaussian(field: np.ndarray, sigma_yx: tuple[float, float]) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.full_like(arr, np.nan, dtype=float)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma_yx, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma_yx, mode="nearest")
    output = np.full_like(arr, np.nan, dtype=float)
    np.divide(smoothed, weight_sum, out=output, where=weight_sum > 1.0e-6)
    return output


def _robust_latitude_trend(
    frame: pd.DataFrame,
    lat: np.ndarray,
    lon: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    rows = frame[["station_lat", "geopotential_height_m"]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    station_lat = rows["station_lat"].to_numpy(dtype=float)
    station_height = rows["geopotential_height_m"].to_numpy(dtype=float)
    if station_lat.size < 12:
        mean_height = float(np.nanmean(station_height)) if station_height.size else 5700.0
        return (
            np.full((lat.size, lon.size), mean_height, dtype=float),
            np.full(station_lat.shape, mean_height, dtype=float),
        )

    bin_width = 2.5
    bin_id = np.floor((station_lat - float(np.nanmin(station_lat))) / bin_width).astype(int)
    binned_lat: list[float] = []
    binned_height: list[float] = []
    for index in np.unique(bin_id):
        mask = bin_id == index
        if np.count_nonzero(mask) < 2:
            continue
        binned_lat.append(float(np.nanmedian(station_lat[mask])))
        binned_height.append(float(np.nanmedian(station_height[mask])))

    x = np.asarray(binned_lat, dtype=float)
    y = np.asarray(binned_height, dtype=float)
    if x.size < 2:
        mean_height = float(np.nanmedian(station_height))
        return (
            np.full((lat.size, lon.size), mean_height, dtype=float),
            np.full(station_lat.shape, mean_height, dtype=float),
        )

    degree = min(3, max(1, x.size - 1))
    keep = np.isfinite(x) & np.isfinite(y)
    coefficients = np.polyfit(x[keep], y[keep], degree)
    for _ in range(4):
        fitted = np.polyval(coefficients, x)
        residual = y - fitted
        median = float(np.nanmedian(residual[keep]))
        mad = float(np.nanmedian(np.abs(residual[keep] - median)))
        threshold = max(35.0, 3.5 * max(1.4826 * mad, 8.0))
        next_keep = keep & (np.abs(residual - median) <= threshold)
        if np.count_nonzero(next_keep) <= degree or np.array_equal(next_keep, keep):
            break
        keep = next_keep
        coefficients = np.polyfit(x[keep], y[keep], degree)

    station_trend = np.polyval(coefficients, station_lat)
    grid_trend = np.repeat(np.polyval(coefficients, lat)[:, None], lon.size, axis=1)
    return grid_trend.astype(float), station_trend.astype(float)


def _latitude_barnes_background(
    frame: pd.DataFrame,
    lat: np.ndarray,
    lon: np.ndarray,
) -> np.ndarray:
    grid_trend, station_trend = _robust_latitude_trend(frame, lat, lon)
    residual_frame = frame.copy()
    residual_frame["z500_latitude_residual"] = (
        pd.to_numeric(residual_frame["geopotential_height_m"], errors="coerce").to_numpy(dtype=float)
        - station_trend
    )
    broad = objective_analysis_field(
        residual_frame,
        "z500_latitude_residual",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(1450.0,),
            smoothing_sigma_grid=1.1,
            max_support_distance_km=2200.0,
        ),
    )
    anomaly = np.asarray(broad.values, dtype=float)
    anomaly = np.where(np.isfinite(anomaly), anomaly, 0.0)
    return grid_trend + anomaly


def _station_residual_metrics(
    field: np.ndarray,
    frame: pd.DataFrame,
    lat: np.ndarray,
    lon: np.ndarray,
) -> dict[str, float | None]:
    rows = frame[["station_lat", "station_lon", "geopotential_height_m"]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    if rows.empty:
        return {
            "station_residual_bias": None,
            "station_residual_rmse": None,
            "station_residual_abs_p90": None,
        }
    interpolator = RegularGridInterpolator(
        (np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)),
        np.asarray(field, dtype=float),
        bounds_error=False,
        fill_value=np.nan,
    )
    estimate = interpolator(
        np.column_stack(
            [
                rows["station_lat"].to_numpy(dtype=float),
                rows["station_lon"].to_numpy(dtype=float),
            ]
        )
    )
    residual = rows["geopotential_height_m"].to_numpy(dtype=float) - estimate
    residual = residual[np.isfinite(residual)]
    if residual.size == 0:
        return {
            "station_residual_bias": None,
            "station_residual_rmse": None,
            "station_residual_abs_p90": None,
        }
    return {
        "station_residual_bias": round(float(np.nanmean(residual)), 3),
        "station_residual_rmse": round(float(np.sqrt(np.nanmean(residual**2))), 3),
        "station_residual_abs_p90": round(float(np.nanpercentile(np.abs(residual), 90)), 3),
    }


def adaptive_station_z500(
    frame: pd.DataFrame,
    lat: np.ndarray,
    lon: np.ndarray,
    baseline: ObjectiveField,
) -> ObjectiveField:
    """Refine station-only Z500 with latitude- and scale-adaptive analysis.

    The method deliberately does not use a numerical-model background.  It blends
    two independent station analyses: the existing robust-polynomial Barnes field
    and a latitude-trend Barnes field.  A high-latitude residual pass restores
    Mongolia/Russia trough curvature, while an anisotropic tropical regularizer
    suppresses small closed 588-dagpm islands caused by sparse low-latitude
    observations.
    """

    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    baseline_values = np.asarray(baseline.values, dtype=float)
    lat2d = np.repeat(lat_values[:, None], lon_values.size, axis=1)
    lon2d = np.repeat(lon_values[None, :], lat_values.size, axis=0)

    latitude_background = _latitude_barnes_background(frame, lat_values, lon_values)
    latitude_analysis = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat_values,
        lon_values,
        config=ObjectiveAnalysisConfig(
            radii_km=(900.0, 600.0, 350.0),
            correction_gains=(0.88, 0.62, 0.34),
            smoothing_sigma_grid=0.62,
            max_support_distance_km=float(
                baseline.quality.get("max_support_distance_km") or 850.0
            ),
        ),
        background=latitude_background,
    )

    # Retain the robust-polynomial analysis over the subtropics, then transition
    # toward the station-only latitude Barnes field across the mid/high latitudes.
    north_weight = 0.85 * _smoothstep((lat2d - 32.0) / 14.0)
    hybrid = (
        (1.0 - north_weight) * baseline_values
        + north_weight * np.asarray(latitude_analysis.values, dtype=float)
    )

    # A compact station-increment pass is used only where the northern sounding
    # network is dense enough to resolve the Mongolia/Russia and Northeast valleys.
    high_detail = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat_values,
        lon_values,
        config=ObjectiveAnalysisConfig(
            radii_km=(300.0,),
            correction_gains=(1.0,),
            smoothing_sigma_grid=0.0,
            max_support_distance_km=float(
                baseline.quality.get("max_support_distance_km") or 850.0
            ),
        ),
        background=hybrid,
    )
    high_weight = 0.65 * _smoothstep((lat2d - 35.0) / 12.0)
    support_distance = np.asarray(baseline.support_distance_km, dtype=float)
    density_weight = 0.35 + 0.65 * (1.0 - _smoothstep((support_distance - 220.0) / 430.0))
    high_weight *= density_weight
    hybrid = hybrid + high_weight * (
        np.asarray(high_detail.values, dtype=float) - hybrid
    )

    # Tropical/subtropical height contours are predominantly zonal and the station
    # network becomes sparse over the South China Sea.  Smooth farther in longitude
    # than latitude, with a latitude taper, so the 588 contour forms one synoptic
    # boundary instead of several compact station-scale loops.
    tropical_smooth = _nan_gaussian(hybrid, (2.0, 5.0))
    tropical_weight = 0.85 * _smoothstep((30.0 - lat2d) / 12.0)
    longitude_window = (
        _smoothstep((lon2d - 75.0) / 15.0)
        * _smoothstep((140.0 - lon2d) / 15.0)
    )
    tropical_weight *= longitude_window
    values = (1.0 - tropical_weight) * hybrid + tropical_weight * tropical_smooth

    quality: dict[str, Any] = dict(baseline.quality)
    quality.update(
        {
            "analysis_version": ADAPTIVE_Z500_VERSION,
            "field_role": "synoptic_z500",
            "background_used": False,
            "background_method": "station_only_adaptive_multiscale",
            "adaptive_station_only": True,
            "adaptive_north_blend": {
                "latitude_start_deg": 32.0,
                "latitude_full_deg": 46.0,
                "maximum_weight": 0.85,
                "detail_radius_km": 300.0,
                "detail_maximum_weight": 0.65,
            },
            "adaptive_tropical_regularization": {
                "latitude_full_deg": 18.0,
                "latitude_end_deg": 30.0,
                "sigma_lat_grid": 2.0,
                "sigma_lon_grid": 5.0,
                "maximum_weight": 0.85,
            },
        }
    )
    quality.update(_station_residual_metrics(values, frame, lat_values, lon_values))

    return ObjectiveField(
        values=np.asarray(values, dtype=float),
        support_distance_km=np.asarray(baseline.support_distance_km, dtype=float),
        support_mask=np.asarray(baseline.support_mask, dtype=bool),
        quality=quality,
    )
