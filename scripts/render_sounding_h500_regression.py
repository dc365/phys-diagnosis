from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from weather_diag.diagnosis import sounding as legacy
from weather_diag.diagnosis.objective_analysis import (
    ObjectiveAnalysisConfig,
    ObjectiveField,
    mask_unsupported,
    objective_analysis_field,
)
from weather_diag.diagnosis.sounding_optimized import (
    SOUNDING_ANALYSIS_CONFIG,
    _background_surface,
    _preprocessed_csv,
    _selected_frame,
    diagnose_sounding_situation,
)
from weather_diag.io.contours import contours_to_geojson


DEFAULT_DATA_DIR = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625"
)
DEFAULT_FILE = DEFAULT_DATA_DIR / "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv"


def _line_coordinates(system: dict) -> np.ndarray:
    geometry = system.get("geometry") or {}
    coordinates = np.asarray(geometry.get("coordinates") or [], dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] < 2:
        return np.empty((0, 2), dtype=float)
    return coordinates[:, :2]


def _contour_collection(values: np.ndarray, support_mask: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> dict:
    return contours_to_geojson(
        "z500",
        "500hPa geopotential height",
        "dagpm",
        mask_unsupported(values * 0.1, support_mask),
        lat=lat,
        lon=lon,
        interval=4.0,
        min_length_km=120.0,
        smooth=True,
        smooth_iterations=2,
        simplify_tolerance_deg=0.012,
    )


def _contour_zone_summary(contours: dict, bounds: tuple[float, float, float, float]) -> dict:
    lon_min, lat_min, lon_max, lat_max = bounds
    levels: dict[str, int] = {}
    feature_count = 0
    for feature in contours.get("features") or []:
        coordinates = np.asarray((feature.get("geometry") or {}).get("coordinates") or [], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            continue
        intersects = (
            (coordinates[:, 0] >= lon_min)
            & (coordinates[:, 0] <= lon_max)
            & (coordinates[:, 1] >= lat_min)
            & (coordinates[:, 1] <= lat_max)
        )
        if not np.any(intersects):
            continue
        feature_count += 1
        value = str((feature.get("properties") or {}).get("value"))
        levels[value] = levels.get(value, 0) + 1
    return {"feature_count": feature_count, "levels": levels}


def _system_zone_summary(systems: list[dict], bounds: tuple[float, float, float, float]) -> list[dict]:
    lon_min, lat_min, lon_max, lat_max = bounds
    output = []
    for system in systems:
        coordinates = _line_coordinates(system)
        if coordinates.size == 0:
            continue
        intersects = (
            (coordinates[:, 0] >= lon_min)
            & (coordinates[:, 0] <= lon_max)
            & (coordinates[:, 1] >= lat_min)
            & (coordinates[:, 1] <= lat_max)
        )
        if not np.any(intersects):
            continue
        output.append(
            {
                "id": system.get("id"),
                "feature_type": system.get("feature_type"),
                "method": system.get("method"),
                "method_detail": system.get("method_detail"),
                "candidate_source": system.get("candidate_source"),
                "axis_length_km": system.get("axis_length_km"),
                "lon_min": float(np.nanmin(coordinates[:, 0])),
                "lon_max": float(np.nanmax(coordinates[:, 0])),
                "lat_min": float(np.nanmin(coordinates[:, 1])),
                "lat_max": float(np.nanmax(coordinates[:, 1])),
            }
        )
    return output


def _robust_latitude_trend(frame: pd.DataFrame, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = frame[["station_lat", "geopotential_height_m"]].apply(pd.to_numeric, errors="coerce").dropna()
    latitude = rows["station_lat"].to_numpy(dtype=float)
    height = rows["geopotential_height_m"].to_numpy(dtype=float)
    if latitude.size < 12:
        mean = float(np.nanmean(height)) if height.size else 5700.0
        return np.full((lat.size, lon.size), mean), np.full(latitude.shape, mean)

    bin_width = 2.5
    bin_id = np.floor((latitude - float(np.nanmin(latitude))) / bin_width).astype(int)
    binned_lat = []
    binned_height = []
    for index in np.unique(bin_id):
        mask = bin_id == index
        if np.count_nonzero(mask) < 2:
            continue
        binned_lat.append(float(np.nanmedian(latitude[mask])))
        binned_height.append(float(np.nanmedian(height[mask])))
    x = np.asarray(binned_lat, dtype=float)
    y = np.asarray(binned_height, dtype=float)
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

    station_trend = np.polyval(coefficients, latitude)
    grid_trend_1d = np.polyval(coefficients, lat)
    grid_trend = np.repeat(grid_trend_1d[:, None], lon.size, axis=1)
    return grid_trend.astype(float), station_trend.astype(float)


def _latitude_barnes_background(frame: pd.DataFrame, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    grid_trend, station_trend = _robust_latitude_trend(frame, lat, lon)
    residual_frame = frame.copy()
    residual_frame["z500_residual"] = (
        pd.to_numeric(residual_frame["geopotential_height_m"], errors="coerce").to_numpy(dtype=float)
        - station_trend
    )
    broad = objective_analysis_field(
        residual_frame,
        "z500_residual",
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


def _candidate_fields(frame: pd.DataFrame, lat: np.ndarray, lon: np.ndarray, current: dict) -> dict[str, ObjectiveField]:
    current_field = ObjectiveField(
        values=np.asarray(current["values"], dtype=float),
        support_distance_km=np.asarray(current["support_distance_km"], dtype=float),
        support_mask=np.asarray(current["support_mask"], dtype=bool),
        quality=dict(current.get("quality") or {}),
    )
    broad = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(1500.0, 900.0, 575.0, 350.0),
            correction_gains=(1.0, 0.92, 0.64, 0.34),
            smoothing_sigma_grid=0.65,
            max_support_distance_km=850.0,
        ),
    )
    lat_background = _latitude_barnes_background(frame, lat, lon)
    latitude_barnes = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(900.0, 600.0, 350.0),
            correction_gains=(0.88, 0.62, 0.34),
            smoothing_sigma_grid=0.62,
            max_support_distance_km=850.0,
        ),
        background=lat_background,
    )
    latitude_barnes_fine = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(850.0, 525.0, 300.0),
            correction_gains=(0.92, 0.72, 0.42),
            smoothing_sigma_grid=0.45,
            max_support_distance_km=850.0,
        ),
        background=lat_background,
    )
    poly_background = _background_surface(frame, "geopotential_height_m", lat, lon)
    polynomial_fine = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=ObjectiveAnalysisConfig(
            radii_km=(900.0, 600.0, 350.0),
            correction_gains=(1.0, 0.80, 0.45),
            smoothing_sigma_grid=0.55,
            max_support_distance_km=850.0,
        ),
        background=poly_background,
    )
    return {
        "current_polynomial": current_field,
        "broad_barnes": broad,
        "latitude_barnes": latitude_barnes,
        "latitude_barnes_fine": latitude_barnes_fine,
        "polynomial_fine": polynomial_fine,
    }


def _trough_systems(
    field: ObjectiveField,
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
) -> list[dict]:
    systems = legacy._trough_ridge_systems(
        np.asarray(field.values, dtype=float),
        u,
        v,
        lat,
        lon,
        0.8,
        support_distance_km=np.asarray(field.support_distance_km, dtype=float),
    )
    return [item for item in systems if item.get("feature_type") in {"trough", "trough_candidate"}]


def _nearest_level_point(contours: dict, level: float, target: tuple[float, float]) -> dict | None:
    best = None
    for feature in contours.get("features") or []:
        props = feature.get("properties") or {}
        if not np.isclose(float(props.get("value", np.nan)), level):
            continue
        coordinates = np.asarray((feature.get("geometry") or {}).get("coordinates") or [], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            continue
        mean_lat = (coordinates[:, 1] + target[1]) / 2.0
        dx = (coordinates[:, 0] - target[0]) * np.maximum(np.cos(np.deg2rad(mean_lat)), 0.2)
        dy = coordinates[:, 1] - target[1]
        distance = np.hypot(dx, dy)
        index = int(np.nanargmin(distance))
        item = {
            "distance_deg": float(distance[index]),
            "lon": float(coordinates[index, 0]),
            "lat": float(coordinates[index, 1]),
        }
        if best is None or item["distance_deg"] < best["distance_deg"]:
            best = item
    return best


def _southernmost_level_point(contours: dict, level: float, lon_bounds: tuple[float, float]) -> dict | None:
    output = []
    for feature in contours.get("features") or []:
        props = feature.get("properties") or {}
        if not np.isclose(float(props.get("value", np.nan)), level):
            continue
        coordinates = np.asarray((feature.get("geometry") or {}).get("coordinates") or [], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            continue
        mask = (coordinates[:, 0] >= lon_bounds[0]) & (coordinates[:, 0] <= lon_bounds[1])
        if np.any(mask):
            selected = coordinates[mask]
            index = int(np.nanargmin(selected[:, 1]))
            output.append({"lon": float(selected[index, 0]), "lat": float(selected[index, 1])})
    return min(output, key=lambda item: item["lat"]) if output else None


def _plot_candidate(
    axis,
    name: str,
    field: ObjectiveField,
    troughs: list[dict],
    lat: np.ndarray,
    lon: np.ndarray,
    station_lon: np.ndarray,
    station_lat: np.ndarray,
) -> None:
    supported = mask_unsupported(np.asarray(field.values, dtype=float) * 0.1, field.support_mask)
    levels = np.arange(
        np.ceil(np.nanmin(supported) / 4.0) * 4.0,
        np.floor(np.nanmax(supported) / 4.0) * 4.0 + 0.1,
        4.0,
    )
    contour_set = axis.contour(
        lon,
        lat,
        np.ma.masked_invalid(supported),
        levels=levels,
        colors="tab:blue",
        linewidths=0.75,
    )
    axis.clabel(contour_set, inline=True, fontsize=5.5, fmt="%d")
    for system in troughs:
        coordinates = _line_coordinates(system)
        if coordinates.shape[0] >= 2:
            axis.plot(coordinates[:, 0], coordinates[:, 1], color="purple", linewidth=2.0)
    axis.scatter(station_lon, station_lat, s=2.0, color="black", alpha=0.28)
    rmse = (field.quality or {}).get("station_residual_rmse")
    axis.set_title(f"{name}\nstation RMSE={rmse}", fontsize=9)
    axis.set_xlim(50, 150)
    axis.set_ylim(10, 55)
    axis.set_xticks(np.arange(50, 151, 20))
    axis.set_yticks(np.arange(10, 56, 10))
    axis.grid(True, linewidth=0.25, alpha=0.35)


def render(csv_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = diagnose_sounding_situation(csv_path, pressure_level=500)
    current = result["analysis_fields"]["z500"]
    lat = np.asarray(current["lat"], dtype=float)
    lon = np.asarray(current["lon"], dtype=float)

    analysis_csv, _ = _preprocessed_csv(csv_path)
    frame = _selected_frame(analysis_csv, "500hPa", 500)
    frame[
        [
            "station_id",
            "station_name",
            "station_lat",
            "station_lon",
            "geopotential_height_m",
            "temperature_c",
            "wind_direction_degree",
            "wind_speed_m_s",
        ]
    ].sort_values(["station_lat", "station_lon"]).to_csv(
        output_dir / "z500_stations.csv",
        index=False,
    )

    candidates = _candidate_fields(frame, lat, lon, current)
    u = np.asarray(result["analysis_fields"]["u500"]["values"], dtype=float)
    v = np.asarray(result["analysis_fields"]["v500"]["values"], dtype=float)
    station_lon = frame["station_lon"].to_numpy(dtype=float)
    station_lat = frame["station_lat"].to_numpy(dtype=float)

    candidate_troughs = {
        name: _trough_systems(field, u, v, lat, lon)
        for name, field in candidates.items()
    }
    candidate_contours = {
        name: _contour_collection(field.values, field.support_mask, lat, lon)
        for name, field in candidates.items()
    }

    fig, axes = plt.subplots(3, 2, figsize=(16, 16), dpi=140)
    for axis, (name, field) in zip(axes.ravel(), candidates.items()):
        _plot_candidate(
            axis,
            name,
            field,
            candidate_troughs[name],
            lat,
            lon,
            station_lon,
            station_lat,
        )
    axes.ravel()[-1].axis("off")
    fig.suptitle(f"{result.get('observation_time')} station-only H500 method comparison", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(output_dir / "sounding_h500_method_comparison.png")
    plt.close(fig)

    reference = next(DEFAULT_DATA_DIR.glob("SEVP_NMC_WESA*.jpeg"), None)
    if reference is not None:
        (output_dir / "reference_nmc.jpeg").write_bytes(reference.read_bytes())

    zones = {
        "hainan": (104.0, 13.0, 115.0, 26.0),
        "northeast": (112.0, 27.0, 145.0, 52.0),
        "mongolia_russia_west": (92.0, 32.0, 111.0, 55.0),
        "russia_far_east": (112.0, 35.0, 132.0, 55.0),
    }
    report = {
        "csv_path": str(csv_path),
        "observation_time": result.get("observation_time"),
        "production_config": {
            "radii_km": list(SOUNDING_ANALYSIS_CONFIG.radii_km),
            "correction_gains": list(SOUNDING_ANALYSIS_CONFIG.correction_gains or []),
            "smoothing_sigma_grid": SOUNDING_ANALYSIS_CONFIG.smoothing_sigma_grid,
        },
        "candidates": {},
    }
    for name, field in candidates.items():
        contours = candidate_contours[name]
        troughs = candidate_troughs[name]
        report["candidates"][name] = {
            "quality": field.quality,
            "contour_count": len(contours.get("features") or []),
            "trough_count": len(troughs),
            "anchors": {
                "hainan_588_nearest_110e18n": _nearest_level_point(contours, 588.0, (110.0, 18.0)),
                "mongolia_572_southernmost_95e105e": _southernmost_level_point(contours, 572.0, (95.0, 105.0)),
                "far_east_568_southernmost_116e126e": _southernmost_level_point(contours, 568.0, (116.0, 126.0)),
                "northeast_576_southernmost_112e125e": _southernmost_level_point(contours, 576.0, (112.0, 125.0)),
            },
            "zones": {
                zone_name: {
                    "contours": _contour_zone_summary(contours, bounds),
                    "troughs": _system_zone_summary(troughs, bounds),
                }
                for zone_name, bounds in zones.items()
            },
        }
    (output_dir / "sounding_h500_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/sounding-h500"))
    args = parser.parse_args()
    render(args.csv, args.output_dir)
