from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from scripts import render_sounding_h500_regression as base
from weather_diag.diagnosis.objective_analysis import (
    ObjectiveAnalysisConfig,
    ObjectiveField,
    mask_unsupported,
    objective_analysis_field,
)
from weather_diag.diagnosis.sounding_optimized import (
    _preprocessed_csv,
    _selected_frame,
    diagnose_sounding_situation,
)


OMEGA = 7.2921159e-5
G0 = 9.80665
EARTH_RADIUS_KM = 6371.0088


def _distance_matrix_km(
    observation_lon: np.ndarray,
    observation_lat: np.ndarray,
    grid_lon2d: np.ndarray,
    grid_lat2d: np.ndarray,
) -> np.ndarray:
    grid_lat_rad = np.deg2rad(np.asarray(grid_lat2d, dtype=float).ravel())[:, None]
    observation_lat_rad = np.deg2rad(np.asarray(observation_lat, dtype=float))[None, :]
    delta_lat = observation_lat_rad - grid_lat_rad
    delta_lon = np.deg2rad(
        (
            np.asarray(observation_lon, dtype=float)[None, :]
            - np.asarray(grid_lon2d, dtype=float).ravel()[:, None]
            + 180.0
        )
        % 360.0
        - 180.0
    )
    haversine = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(grid_lat_rad) * np.cos(observation_lat_rad) * np.sin(delta_lon / 2.0) ** 2
    )
    haversine = np.clip(haversine, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_KM * np.arctan2(
        np.sqrt(haversine),
        np.sqrt(1.0 - haversine),
    )


def _weighted_barnes(
    observation_lon: np.ndarray,
    observation_lat: np.ndarray,
    values: np.ndarray,
    observation_weight: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    radius_km: float,
) -> np.ndarray:
    lon2d, lat2d = np.meshgrid(lon, lat)
    distance = _distance_matrix_km(observation_lon, observation_lat, lon2d, lat2d)
    weights = np.exp(-((distance / max(float(radius_km), 1.0)) ** 2))
    weights *= np.asarray(observation_weight, dtype=float)[None, :]
    finite = np.isfinite(values)
    weights[:, ~finite] = 0.0
    weight_sum = weights.sum(axis=1)
    weighted_sum = weights @ np.where(finite, values, 0.0)
    output = np.full(weight_sum.shape, np.nan, dtype=float)
    np.divide(weighted_sum, weight_sum, out=output, where=weight_sum > 1.0e-8)
    return output.reshape(lat.size, lon.size)


def _wind_augmented_background(frame: pd.DataFrame, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, dict]:
    grid_trend, station_trend = base._robust_latitude_trend(frame, lat, lon)
    station_lon = frame["station_lon"].to_numpy(dtype=float)
    station_lat = frame["station_lat"].to_numpy(dtype=float)
    station_height = frame["geopotential_height_m"].to_numpy(dtype=float)
    u = frame["u_wind_m_s"].to_numpy(dtype=float)
    v = frame["v_wind_m_s"].to_numpy(dtype=float)
    speed = np.hypot(u, v)

    observation_lon = list(station_lon)
    observation_lat = list(station_lat)
    observation_height = list(station_height)
    observation_weight = [1.0] * len(frame)
    pseudo_count = 0
    offset_km = 180.0
    offset_m = offset_km * 1000.0

    for lo, la, height, u_value, v_value, wind_speed in zip(
        station_lon,
        station_lat,
        station_height,
        u,
        v,
        speed,
    ):
        if not all(np.isfinite(item) for item in [lo, la, height, u_value, v_value, wind_speed]):
            continue
        absolute_latitude = abs(float(la))
        latitude_taper = float(np.clip((absolute_latitude - 15.0) / 22.0, 0.0, 1.0))
        if latitude_taper <= 0.0:
            continue
        speed_taper = float(np.clip(wind_speed / 20.0, 0.25, 1.0))
        pseudo_weight = 0.24 * latitude_taper * speed_taper
        if pseudo_weight < 0.025:
            continue

        coriolis = 2.0 * OMEGA * np.sin(np.deg2rad(float(la)))
        dz_dx = coriolis * float(v_value) / G0
        dz_dy = -coriolis * float(u_value) / G0
        delta_lat = offset_km / 111.32
        delta_lon = offset_km / (111.32 * max(np.cos(np.deg2rad(float(la))), 0.2))
        pseudo = [
            (lo + delta_lon, la, height + dz_dx * offset_m),
            (lo - delta_lon, la, height - dz_dx * offset_m),
            (lo, la + delta_lat, height + dz_dy * offset_m),
            (lo, la - delta_lat, height - dz_dy * offset_m),
        ]
        for pseudo_lon, pseudo_lat, pseudo_height in pseudo:
            if not (float(lon.min()) <= pseudo_lon <= float(lon.max())):
                continue
            if not (float(lat.min()) <= pseudo_lat <= float(lat.max())):
                continue
            observation_lon.append(float(pseudo_lon))
            observation_lat.append(float(pseudo_lat))
            observation_height.append(float(pseudo_height))
            observation_weight.append(pseudo_weight)
            pseudo_count += 1

    observation_lon_arr = np.asarray(observation_lon, dtype=float)
    observation_lat_arr = np.asarray(observation_lat, dtype=float)
    observation_height_arr = np.asarray(observation_height, dtype=float)
    observation_weight_arr = np.asarray(observation_weight, dtype=float)
    trend_at_observations = np.interp(observation_lat_arr, lat, grid_trend[:, 0])
    residual = observation_height_arr - trend_at_observations
    broad_anomaly = _weighted_barnes(
        observation_lon_arr,
        observation_lat_arr,
        residual,
        observation_weight_arr,
        lat,
        lon,
        radius_km=1250.0,
    )
    background = grid_trend + np.where(np.isfinite(broad_anomaly), broad_anomaly, 0.0)
    return background, {
        "real_station_count": int(len(frame)),
        "pseudo_observation_count": int(pseudo_count),
        "pseudo_offset_km": offset_km,
        "pseudo_weight_max": float(np.max(observation_weight_arr[len(frame):])) if pseudo_count else 0.0,
        "background_radius_km": 1250.0,
    }


def _candidate(frame: pd.DataFrame, lat: np.ndarray, lon: np.ndarray) -> tuple[ObjectiveField, dict]:
    background, metadata = _wind_augmented_background(frame, lat, lon)
    field = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(850.0, 525.0, 300.0),
            correction_gains=(0.86, 0.62, 0.34),
            smoothing_sigma_grid=0.50,
            max_support_distance_km=850.0,
        ),
        background=background,
    )
    field.quality.update(
        {
            "analysis_version": "station_wind_balanced_experiment_v1",
            "background_method": "latitude_trend_plus_geostrophic_pseudo_observations",
            **metadata,
        }
    )
    return field, metadata


def _mask_plot(
    axis,
    title: str,
    values: np.ndarray,
    support_distance: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    threshold: float | None,
) -> None:
    data = values * 0.1
    if threshold is not None:
        data = np.where(support_distance <= threshold, data, np.nan)
    valid = data[np.isfinite(data)]
    levels = np.arange(
        np.ceil(valid.min() / 4.0) * 4.0,
        np.floor(valid.max() / 4.0) * 4.0 + 0.1,
        4.0,
    )
    contour_set = axis.contour(lon, lat, np.ma.masked_invalid(data), levels=levels, colors="tab:blue", linewidths=0.8)
    axis.clabel(contour_set, inline=True, fontsize=6, fmt="%d")
    axis.set_xlim(50, 150)
    axis.set_ylim(10, 55)
    axis.set_title(title, fontsize=9)
    axis.grid(True, linewidth=0.25, alpha=0.3)


def render(csv_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = diagnose_sounding_situation(csv_path, pressure_level=500)
    current_payload = result["analysis_fields"]["z500"]
    lat = np.asarray(current_payload["lat"], dtype=float)
    lon = np.asarray(current_payload["lon"], dtype=float)
    current = ObjectiveField(
        values=np.asarray(current_payload["values"], dtype=float),
        support_distance_km=np.asarray(current_payload["support_distance_km"], dtype=float),
        support_mask=np.asarray(current_payload["support_mask"], dtype=bool),
        quality=dict(current_payload.get("quality") or {}),
    )
    analysis_csv, _ = _preprocessed_csv(csv_path)
    frame = _selected_frame(analysis_csv, "500hPa", 500)
    wind_field, metadata = _candidate(frame, lat, lon)
    u = np.asarray(result["analysis_fields"]["u500"]["values"], dtype=float)
    v = np.asarray(result["analysis_fields"]["v500"]["values"], dtype=float)
    current_troughs = base._trough_systems(current, u, v, lat, lon)
    wind_troughs = base._trough_systems(wind_field, u, v, lat, lon)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7.5), dpi=145)
    station_lon = frame["station_lon"].to_numpy(dtype=float)
    station_lat = frame["station_lat"].to_numpy(dtype=float)
    base._plot_candidate(axes[0], "current_polynomial", current, current_troughs, lat, lon, station_lon, station_lat)
    base._plot_candidate(axes[1], "wind_balanced", wind_field, wind_troughs, lat, lon, station_lon, station_lat)
    fig.tight_layout()
    fig.savefig(output_dir / "sounding_h500_wind_comparison.png")
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12), dpi=140)
    for axis, threshold in zip(axes.ravel(), [850.0, 1100.0, 1400.0, None]):
        label = "unmasked" if threshold is None else f"support <= {int(threshold)} km"
        _mask_plot(
            axis,
            label,
            current.values,
            current.support_distance_km,
            lat,
            lon,
            threshold,
        )
    fig.tight_layout()
    fig.savefig(output_dir / "sounding_h500_support_mask_comparison.png")
    plt.close(fig)

    np.savez_compressed(
        output_dir / "sounding_h500_fields.npz",
        lat=lat,
        lon=lon,
        current_values=current.values,
        current_support_distance=current.support_distance_km,
        wind_values=wind_field.values,
        wind_support_distance=wind_field.support_distance_km,
    )

    report = {
        "metadata": metadata,
        "current_quality": current.quality,
        "wind_quality": wind_field.quality,
        "current_troughs": base._system_zone_summary(current_troughs, (50.0, 10.0, 150.0, 55.0)),
        "wind_troughs": base._system_zone_summary(wind_troughs, (50.0, 10.0, 150.0, 55.0)),
    }
    (output_dir / "sounding_h500_wind_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=base.DEFAULT_FILE)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/sounding-h500"))
    args = parser.parse_args()
    render(args.csv, args.output_dir)
