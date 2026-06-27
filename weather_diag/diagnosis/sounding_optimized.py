from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_diag.diagnosis import sounding as legacy
from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field
from weather_diag.features.shear_line import detect_shear_lines


# Tuned for the 2026-06-24/25 radiosonde H500 comparisons against the CMA/NMC
# 500hPa weather charts.  This version makes two important changes:
# 1) z500 uses a broad polynomial first guess plus station increments, so the
#    subtropical 588-dagpm belt is preserved better over South China/Hainan.
# 2) obvious 500hPa height outliers are filtered before Barnes analysis, which
#    suppresses unrealistically dense closed contours over the northern domain.
SOUNDING_ANALYSIS_CONFIG = ObjectiveAnalysisConfig(
    radii_km=(800.0, 560.0, 340.0),
    smoothing_sigma_grid=0.80,
    max_support_distance_km=850.0,
)

Z500_HARD_MIN_M = 5400.0
Z500_HARD_MAX_M = 6020.0


def _field_payload(obj, *, unit: str, lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    return {
        "values": obj.values,
        "lat": lat,
        "lon": lon,
        "unit": unit,
        "quality": obj.quality,
        "support_distance_km": obj.support_distance_km,
        "support_mask": obj.support_mask,
    }


def _poly_terms(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon0 = 105.0
    lat0 = 30.0
    x = (lon - lon0) / 35.0
    y = (lat - lat0) / 18.0
    return np.column_stack(
        [
            np.ones_like(x),
            x,
            y,
            x * y,
            x * x,
            y * y,
        ]
    )


def _robust_polyfit(lon: np.ndarray, lat: np.ndarray, values: np.ndarray) -> tuple[np.ndarray | None, np.ndarray]:
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(lon) & np.isfinite(lat) & np.isfinite(values)
    if valid.sum() < 12:
        return None, valid

    keep = valid.copy()
    coeff = None
    for _ in range(4):
        design = _poly_terms(lon[keep], lat[keep])
        try:
            coeff, *_ = np.linalg.lstsq(design, values[keep], rcond=None)
        except np.linalg.LinAlgError:
            return None, valid
        estimate = _poly_terms(lon[valid], lat[valid]) @ coeff
        residual = values[valid] - estimate
        med = float(np.nanmedian(residual))
        mad = float(np.nanmedian(np.abs(residual - med)))
        scale = max(1.4826 * mad, 25.0)
        new_valid_indices = np.where(valid)[0][np.abs(residual - med) <= max(150.0, 4.0 * scale)]
        new_keep = np.zeros_like(valid, dtype=bool)
        new_keep[new_valid_indices] = True
        if np.array_equal(new_keep, keep):
            break
        keep = new_keep
    return coeff, keep


def _background_surface(frame: pd.DataFrame, value_column: str, lat: np.ndarray, lon: np.ndarray) -> np.ndarray | None:
    rows = frame[["station_lon", "station_lat", value_column]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(rows) < 12:
        return None
    coeff, keep = _robust_polyfit(
        rows["station_lon"].to_numpy(dtype=float),
        rows["station_lat"].to_numpy(dtype=float),
        rows[value_column].to_numpy(dtype=float),
    )
    if coeff is None:
        return None
    lon2d, lat2d = np.meshgrid(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    background = (_poly_terms(lon2d.ravel(), lat2d.ravel()) @ coeff).reshape(lon2d.shape)
    return background.astype(float)


def _qc_500_height(frame: pd.DataFrame) -> pd.DataFrame:
    """Filter obvious z500 station outliers before objective analysis.

    The northern red-box issue was caused by unrealistically deep 500hPa height
    pockets.  A single or small cluster of bad heights can create 516/532-dagpm
    nested contours.  This filter keeps the QC conservative: coherent lows are
    retained by the buddy/polynomial check, while hard physically implausible
    June H500 values are rejected.
    """
    if frame.empty or "geopotential_height_m" not in frame:
        return frame
    work = frame.copy()
    z = pd.to_numeric(work["geopotential_height_m"], errors="coerce")
    hard = z.between(Z500_HARD_MIN_M, Z500_HARD_MAX_M)

    lon = pd.to_numeric(work["station_lon"], errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(work["station_lat"], errors="coerce").to_numpy(dtype=float)
    values = z.to_numpy(dtype=float)
    coeff, robust_keep = _robust_polyfit(lon[hard.to_numpy()], lat[hard.to_numpy()], values[hard.to_numpy()])
    if coeff is not None:
        expected = _poly_terms(lon, lat) @ coeff
        residual = values - expected
        finite = np.isfinite(residual)
        med = float(np.nanmedian(residual[finite])) if finite.any() else 0.0
        mad = float(np.nanmedian(np.abs(residual[finite] - med))) if finite.any() else 0.0
        threshold = max(130.0, min(230.0, 4.2 * max(1.4826 * mad, 20.0)))
        buddy = np.abs(residual - med) <= threshold
    else:
        buddy = np.ones(len(work), dtype=bool)

    keep = hard.to_numpy(dtype=bool) & buddy & np.isfinite(values)
    out = work.loc[keep].copy()
    out.attrs["height_qc_removed"] = int((~keep).sum())
    out.attrs["height_qc_kept"] = int(keep.sum())
    return out


def _selected_frame(csv_path: str | Path, level: str, pressure_level: int) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    frame = df[df["requested_level"].astype(str) == level].copy()
    if frame.empty:
        raise ValueError(f"no sounding rows for {level}")
    frame = frame.dropna(subset=["station_lat", "station_lon", "geopotential_height_m", "temperature_c"])
    if int(pressure_level) == 500:
        frame = frame[frame["geopotential_height_m"].between(4500.0, 6500.0)]
        frame = _qc_500_height(frame)
    if frame.empty:
        raise ValueError(f"no quality-controlled sounding rows for {level}")
    u, v = legacy._wind_components(frame["wind_direction_degree"].to_numpy(), frame["wind_speed_m_s"].to_numpy())
    frame["u_wind_m_s"] = u
    frame["v_wind_m_s"] = v
    return frame


def _system_confidence(quality: dict[str, Any]) -> float:
    count_score = min(1.0, float(quality.get("station_count") or 0) / 220.0)
    support_score = min(1.0, float(quality.get("supported_grid_ratio") or 0.0))
    distance = float(quality.get("mean_nearest_station_km") or 320.0)
    distance_score = max(0.0, min(1.0, (420.0 - distance) / 360.0))
    residual = quality.get("station_residual_rmse")
    residual_score = 0.7 if residual is None else max(0.0, min(1.0, (24.0 - float(residual)) / 24.0))
    return round(0.36 + 0.24 * count_score + 0.16 * distance_score + 0.16 * support_score + 0.08 * residual_score, 2)


def _shear_systems(u: np.ndarray, v: np.ndarray, t: np.ndarray, lat: np.ndarray, lon: np.ndarray, confidence: float) -> list[dict[str, Any]]:
    thresholds = {
        "shear_line": {
            "score_percentile": 90.0,
            "dynamic_percentile": 84.0,
            "vorticity_min": 0.8e-5,
            "convergence_min": 0.0,
            "min_support_components": 1,
            "min_area_grid_points": 10,
            "min_length_km": 520.0,
            "max_objects": 4,
            "smoothing_sigma_grid": 1.35,
            "separate_front_with_shear": True,
            "front_gradient_percentile": 88.0,
        }
    }
    try:
        features = detect_shear_lines(u, v, lat, lon, thresholds, level=500, temperature=t)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        feature_type = str(props.get("feature_type") or "shear_line")
        out.append(
            {
                "id": props.get("id") or f"sounding-{feature_type}-{len(out) + 1:03d}",
                "type": feature_type,
                "feature_type": feature_type,
                "name": props.get("title") or "500hPa shear line",
                "level": "500hPa",
                "confidence": round(min(float(props.get("confidence") or confidence), confidence), 2),
                "geometry": {"type": "line", "coordinates": coords},
                "axis_length_km": props.get("axis_length_km"),
                "evidence": [
                    "500hPa wind shear, positive vorticity and deformation support",
                    "NMC-tuned smoothing and length gates reduce station-scale noisy shear axes",
                    "temperature-gradient support marks front_with_shear when applicable",
                ],
            }
        )
    return out


def diagnose_sounding_situation(
    csv_path: str | Path,
    *,
    pressure_level: int = 500,
    domain: dict[str, float] | None = None,
) -> dict[str, Any]:
    result = legacy.diagnose_sounding_situation(csv_path, pressure_level=pressure_level, domain=domain)
    level = legacy._level_name(pressure_level)
    frame = _selected_frame(csv_path, level, pressure_level)
    lat = np.asarray(result["analysis_fields"]["z500"]["lat"], dtype=float)
    lon = np.asarray(result["analysis_fields"]["z500"]["lon"], dtype=float)

    z_background = _background_surface(frame, "geopotential_height_m", lat, lon)
    z = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=SOUNDING_ANALYSIS_CONFIG,
        background=z_background,
    )
    t = objective_analysis_field(frame, "temperature_c", lat, lon, config=SOUNDING_ANALYSIS_CONFIG)
    u = objective_analysis_field(frame, "u_wind_m_s", lat, lon, config=SOUNDING_ANALYSIS_CONFIG)
    v = objective_analysis_field(frame, "v_wind_m_s", lat, lon, config=SOUNDING_ANALYSIS_CONFIG)
    confidence = _system_confidence(z.quality)

    systems: list[dict[str, Any]] = []
    systems.extend(
        legacy._center_features(
            z.values,
            lat,
            lon,
            high_type="height_high",
            low_type="height_low",
            high_label="H",
            low_label="L",
            unit="gpm",
            level=level,
            confidence=confidence,
        )
    )
    systems.extend(
        legacy._center_features(
            t.values,
            lat,
            lon,
            high_type="warm_center",
            low_type="cold_center",
            high_label="W",
            low_label="C",
            unit="degC",
            level=level,
            confidence=confidence,
        )
    )
    systems.extend(legacy._trough_ridge_systems(z.values, u.values, v.values, lat, lon, confidence))
    systems.extend(_shear_systems(u.values, v.values, t.values, lat, lon, confidence))

    result = dict(result)
    result["analysis_fields"] = {
        "z500": _field_payload(z, unit="gpm", lat=lat, lon=lon),
        "t500": _field_payload(t, unit="degC", lat=lat, lon=lon),
        "u500": _field_payload(u, unit="m/s", lat=lat, lon=lon),
        "v500": _field_payload(v, unit="m/s", lat=lat, lon=lon),
    }
    result["systems"] = systems
    result["station_features"] = legacy._station_features(frame, level)
    result["summary"] = f"{result['observation_time']} {level} NMC-tuned Barnes sounding objective analysis generated {len(systems)} weather systems."
    return result
