from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_diag.config import PROJECT_ROOT
from weather_diag.diagnosis import sounding as legacy
from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field
from weather_diag.diagnosis.sounding_multilevel import augment_sounding_result
from weather_diag.diagnosis.sounding_preprocess import preprocess_sounding_csv
from weather_diag.features.shear_line import detect_shear_lines


# Synoptic-scale Z500 analysis for sparse sounding observations.  The final
# correction is intentionally damped: it retains supported trough curvature
# without turning individual station increments into closed contour centres.
SOUNDING_ANALYSIS_CONFIG = ObjectiveAnalysisConfig(
    radii_km=(900.0, 650.0, 450.0),
    correction_gains=(1.0, 0.85, 0.55),
    smoothing_sigma_grid=1.0,
    max_support_distance_km=850.0,
)

Z500_HARD_MIN_M = 5400.0
Z500_HARD_MAX_M = 6020.0
Z500_ANALYSIS_VERSION = "sounding_z500_synoptic_v2"

_VERTICAL_SCALAR_COLUMNS = (
    "geopotential_height_m",
    "temperature_c",
    "dew_point_temperature_c",
    "ice_point_temperature_c",
    "relative_humidity_pct",
    "humidity_wrt_ice_pct",
    "mixing_ratio_g_per_kg",
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


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _preprocessed_csv(csv_path: str | Path) -> tuple[Path, dict[str, Any] | None]:
    source = _resolve_project_path(csv_path)
    if ".clean" in source.name:
        return source, {"skipped": True, "reason": "already_preprocessed", "cleaned_csv_path": str(source)}
    try:
        report = preprocess_sounding_csv(source, force=False, write_outputs=True)
        cleaned = _resolve_project_path(report.get("cleaned_csv_path") or source)
        if cleaned.exists():
            return cleaned, report
        return source, report
    except Exception as exc:
        return source, {"error": str(exc), "error_type": type(exc).__name__, "fallback_to_raw": True}


def _sounding_display_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    out = dict(report)
    for key in ["source_path", "cleaned_csv_path", "report_path"]:
        if key in out and out[key] is not None:
            out[key] = str(out[key]).replace("radiosonde", "sounding")
    return out


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


def _interpolate_station_level(group: pd.DataFrame, pressure_level: int) -> pd.Series | None:
    target = float(pressure_level)
    profile = group.copy()
    profile["pressure_hpa"] = pd.to_numeric(profile["pressure_hpa"], errors="coerce")
    profile = profile.dropna(subset=["pressure_hpa"]).sort_values("pressure_hpa", ascending=False)
    profile = profile.drop_duplicates(subset=["pressure_hpa"], keep="last")
    if profile.empty:
        return None

    distance = (profile["pressure_hpa"] - target).abs()
    nearest = profile.loc[distance.idxmin()].copy()
    nearest_pressure = float(nearest["pressure_hpa"])
    if abs(nearest_pressure - target) <= 0.5:
        nearest["pressure_hpa"] = target
        nearest["vertical_interpolated"] = False
        nearest["vertical_source_pressure_low_hpa"] = target
        nearest["vertical_source_pressure_high_hpa"] = target
        return nearest

    below = profile[profile["pressure_hpa"] > target].sort_values("pressure_hpa")
    above = profile[profile["pressure_hpa"] < target].sort_values("pressure_hpa", ascending=False)
    if below.empty or above.empty:
        nearest["vertical_interpolated"] = False
        nearest["vertical_source_pressure_low_hpa"] = nearest_pressure
        nearest["vertical_source_pressure_high_hpa"] = nearest_pressure
        return nearest

    low_row = below.iloc[0]
    high_row = above.iloc[0]
    low_pressure = float(low_row["pressure_hpa"])
    high_pressure = float(high_row["pressure_hpa"])
    if low_pressure - high_pressure > 220.0:
        nearest["vertical_interpolated"] = False
        nearest["vertical_source_pressure_low_hpa"] = nearest_pressure
        nearest["vertical_source_pressure_high_hpa"] = nearest_pressure
        return nearest

    denominator = np.log(high_pressure) - np.log(low_pressure)
    if abs(float(denominator)) <= 1.0e-9:
        return nearest
    weight = float((np.log(target) - np.log(low_pressure)) / denominator)
    output = nearest.copy()
    for column in _VERTICAL_SCALAR_COLUMNS:
        if column not in profile:
            continue
        low_value = pd.to_numeric(pd.Series([low_row.get(column)]), errors="coerce").iloc[0]
        high_value = pd.to_numeric(pd.Series([high_row.get(column)]), errors="coerce").iloc[0]
        if np.isfinite(low_value) and np.isfinite(high_value):
            output[column] = float(low_value + weight * (high_value - low_value))

    low_direction = pd.to_numeric(pd.Series([low_row.get("wind_direction_degree")]), errors="coerce").iloc[0]
    high_direction = pd.to_numeric(pd.Series([high_row.get("wind_direction_degree")]), errors="coerce").iloc[0]
    low_speed = pd.to_numeric(pd.Series([low_row.get("wind_speed_m_s")]), errors="coerce").iloc[0]
    high_speed = pd.to_numeric(pd.Series([high_row.get("wind_speed_m_s")]), errors="coerce").iloc[0]
    if all(np.isfinite(item) for item in [low_direction, high_direction, low_speed, high_speed]):
        low_u, low_v = legacy._wind_components(np.asarray([low_direction]), np.asarray([low_speed]))
        high_u, high_v = legacy._wind_components(np.asarray([high_direction]), np.asarray([high_speed]))
        u = float(low_u[0] + weight * (high_u[0] - low_u[0]))
        v = float(low_v[0] + weight * (high_v[0] - low_v[0]))
        output["wind_speed_m_s"] = float(np.hypot(u, v))
        output["wind_direction_degree"] = float((np.rad2deg(np.arctan2(-u, -v)) + 360.0) % 360.0)

    output["requested_level"] = f"{int(pressure_level)}hPa"
    output["pressure_hpa"] = target
    output["vertical_interpolated"] = True
    output["vertical_source_pressure_low_hpa"] = low_pressure
    output["vertical_source_pressure_high_hpa"] = high_pressure
    return output


def _interpolate_pressure_level(all_rows: pd.DataFrame, pressure_level: int) -> pd.DataFrame:
    rows: list[pd.Series] = []
    for _, group in all_rows.groupby("station_id", sort=False, dropna=True):
        row = _interpolate_station_level(group, pressure_level)
        if row is not None:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=all_rows.columns)
    frame = pd.DataFrame(rows).reset_index(drop=True)
    interpolated = frame.get("vertical_interpolated", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    frame.attrs["vertical_interpolated_station_count"] = int(interpolated.sum())
    frame.attrs["vertical_exact_station_count"] = int((~interpolated).sum())
    return frame


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
    if int(pressure_level) == 500:
        frame = _interpolate_pressure_level(df, pressure_level)
    else:
        frame = df[df["requested_level"].astype(str) == level].copy()
    if frame.empty:
        raise ValueError(f"no sounding rows for {level}")
    frame = frame.dropna(subset=["station_lat", "station_lon", "geopotential_height_m", "temperature_c"])
    if int(pressure_level) == 500:
        frame = frame[frame["geopotential_height_m"].between(4500.0, 6500.0)]
        frame = _qc_500_height(frame)
        interpolated = frame.get("vertical_interpolated", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        frame.attrs["vertical_interpolated_station_count"] = int(interpolated.sum())
        frame.attrs["vertical_exact_station_count"] = int((~interpolated).sum())
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
    analysis_csv, preprocess_report = _preprocessed_csv(csv_path)
    result = legacy.diagnose_sounding_situation(analysis_csv, pressure_level=pressure_level, domain=domain)
    level = legacy._level_name(pressure_level)
    frame = _selected_frame(analysis_csv, level, pressure_level)
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
    z.quality.update(
        {
            "analysis_version": Z500_ANALYSIS_VERSION,
            "field_role": "synoptic_z500",
            "background_method": "robust_quadratic_station_trend",
            "vertical_interpolated_station_count": int(frame.attrs.get("vertical_interpolated_station_count", 0)),
            "vertical_exact_station_count": int(frame.attrs.get("vertical_exact_station_count", 0)),
        }
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
    systems.extend(
        legacy._trough_ridge_systems(
            z.values,
            u.values,
            v.values,
            lat,
            lon,
            confidence,
            support_distance_km=z.support_distance_km,
        )
    )
    systems.extend(_shear_systems(u.values, v.values, t.values, lat, lon, confidence))

    result = dict(result)
    result["analysis_fields"] = {
        "z500": _field_payload(z, unit="gpm", lat=lat, lon=lon),
        "t500": _field_payload(t, unit="degC", lat=lat, lon=lon),
        "u500": _field_payload(u, unit="m/s", lat=lat, lon=lon),
        "v500": _field_payload(v, unit="m/s", lat=lat, lon=lon),
    }
    result["systems"] = systems
    result["analysis_contract"] = {
        "synoptic_height_field": "z500",
        "height_contour_field": "z500",
        "height_center_field": "z500",
        "trough_ridge_field": "z500",
        "analysis_version": Z500_ANALYSIS_VERSION,
    }
    result["station_features"] = legacy._station_features(frame, level)
    result["preprocess_report"] = _sounding_display_report(preprocess_report)
    result = augment_sounding_result(result, analysis_csv, lat, lon)
    result["summary"] = (
        f"{result['observation_time']} {level} multiscale synoptic sounding objective analysis "
        f"generated {len(result.get('systems') or [])} weather systems; "
        f"multilevel fields {result.get('multilevel_summary', {}).get('added_field_count', 0)}."
    )
    return result
