from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_diag.diagnosis import sounding as legacy
from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field
from weather_diag.features.shear_line import detect_shear_lines


# Tuned against the four local sounding-vs-CMA H500 screenshots under
# test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625.
# Compared with the first Barnes version this uses broader first/second-pass
# radii and a slightly stronger final smoothing, so 4-dagpm contours look closer
# to operational 500hPa hand analysis instead of following every station-scale
# wiggle.  The support mask is also relaxed: NMC charts keep the full synoptic
# domain visible, so we mask only very weakly supported far-edge areas.
SOUNDING_ANALYSIS_CONFIG = ObjectiveAnalysisConfig(
    radii_km=(850.0, 600.0, 360.0),
    smoothing_sigma_grid=0.95,
    max_support_distance_km=780.0,
)


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


def _selected_frame(csv_path: str | Path, level: str, pressure_level: int) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    frame = df[df["requested_level"].astype(str) == level].copy()
    if frame.empty:
        raise ValueError(f"no sounding rows for {level}")
    frame = frame.dropna(subset=["station_lat", "station_lon", "geopotential_height_m", "temperature_c"])
    if int(pressure_level) == 500:
        frame = frame[frame["geopotential_height_m"].between(4500.0, 6500.0)]
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

    z = objective_analysis_field(frame, "geopotential_height_m", lat, lon, config=SOUNDING_ANALYSIS_CONFIG)
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
    result["summary"] = f"{result['observation_time']} {level} NMC-tuned Barnes sounding objective analysis generated {len(systems)} weather systems."
    return result
