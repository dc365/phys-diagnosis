from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from metpy.calc import cape_cin, lcl, parcel_profile, precipitable_water
from metpy.units import units
from scipy import ndimage
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, score_level as matrix_score_level
from weather_diag.diagnosis.risk_taxonomy import HAZARD_TYPES
from weather_diag.features.trough_ridge import detect_trough_ridge
from weather_diag.io.geojson import feature_collection, point_feature


DEFAULT_DOMAIN = {
    "lat_min": 5.0,
    "lat_max": 55.0,
    "lon_min": 50.0,
    "lon_max": 160.0,
    "resolution": 1.0,
}


def _level_name(pressure_level: int | float | str) -> str:
    if isinstance(pressure_level, str):
        return pressure_level if pressure_level.endswith("hPa") else f"{pressure_level}hPa"
    return f"{int(pressure_level)}hPa"


def _json_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    text = str(value)
    return text if text and text.lower() != "nan" else None


def _wind_components(direction_degree: np.ndarray, speed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    direction = np.deg2rad(np.asarray(direction_degree, dtype=float))
    wind_speed = np.asarray(speed, dtype=float)
    return -wind_speed * np.sin(direction), -wind_speed * np.cos(direction)


def _quantity_float(value: Any, unit: str) -> float | None:
    try:
        number = float(value.to(unit).magnitude)
    except Exception:
        return None
    return round(number, 3) if np.isfinite(number) else None


def _profile_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "pressure_hpa",
        "temperature_c",
        "dew_point_temperature_c",
        "geopotential_height_m",
        "wind_direction_degree",
        "wind_speed_m_s",
    ]
    profile = frame[cols].apply(pd.to_numeric, errors="coerce").dropna(
        subset=["pressure_hpa", "temperature_c", "dew_point_temperature_c"]
    )
    profile = profile.sort_values("pressure_hpa", ascending=False)
    return profile.drop_duplicates(subset=["pressure_hpa"])


def _metpy_indices(profile: pd.DataFrame) -> tuple[dict[str, float | None], dict[str, Any]]:
    if len(profile) < 3:
        return (
            {
                "cape_j_kg": None,
                "cin_j_kg": None,
                "lcl_pressure_hpa": None,
                "lcl_temperature_c": None,
                "precipitable_water_mm": None,
            },
            {"available": False, "reason": "insufficient_profile_levels", "profile_level_count": int(len(profile))},
        )
    pressure = profile["pressure_hpa"].to_numpy(dtype=float) * units.hPa
    temperature = profile["temperature_c"].to_numpy(dtype=float) * units.degC
    dewpoint = profile["dew_point_temperature_c"].to_numpy(dtype=float) * units.degC
    try:
        lcl_pressure, lcl_temperature = lcl(pressure[0], temperature[0], dewpoint[0])
        pw = precipitable_water(pressure, dewpoint)
        parcel = parcel_profile(pressure, temperature[0], dewpoint[0])
        cape, cin = cape_cin(pressure, temperature, dewpoint, parcel)
    except Exception as exc:
        return (
            {
                "cape_j_kg": None,
                "cin_j_kg": None,
                "lcl_pressure_hpa": None,
                "lcl_temperature_c": None,
                "precipitable_water_mm": None,
            },
            {"available": False, "reason": type(exc).__name__, "profile_level_count": int(len(profile))},
        )
    return (
        {
            "cape_j_kg": _quantity_float(cape, "J/kg"),
            "cin_j_kg": _quantity_float(cin, "J/kg"),
            "lcl_pressure_hpa": _quantity_float(lcl_pressure, "hPa"),
            "lcl_temperature_c": _quantity_float(lcl_temperature, "degC"),
            "precipitable_water_mm": _quantity_float(pw, "mm"),
        },
        {"available": True, "reason": None, "profile_level_count": int(len(profile))},
    )


def _station_diagnostics(df: pd.DataFrame) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for station_id, group in df.groupby("station_id", sort=True):
        profile = _profile_frame(group)
        indices, quality = _metpy_indices(profile)
        first = group.iloc[0]
        diagnostics.append(
            {
                "station_id": str(station_id),
                "station_name": _json_text(first.get("station_name")),
                "station_lat": _json_float(first.get("station_lat")),
                "station_lon": _json_float(first.get("station_lon")),
                "observation_time": pd.to_datetime(first.get("request_datetime_bjt")).isoformat(),
                "source": "metpy",
                "indices": indices,
                "quality": quality,
            }
        )
    return diagnostics


def _score_pos(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    if high <= low:
        return None
    return float(np.clip((float(value) - low) / (high - low), 0.0, 1.0))


def _score_neg(value: float | None, high: float, low: float) -> float | None:
    if value is None:
        return None
    if high <= low:
        return None
    return float(np.clip((high - float(value)) / (high - low), 0.0, 1.0))


def _weighted_score(factors: dict[str, tuple[float | None, float, str]]) -> tuple[float, list[dict[str, Any]], float]:
    configured = sum(weight for _score, weight, _label in factors.values())
    available = sum(weight for score, weight, _label in factors.values() if score is not None)
    if available <= 0:
        return 0.0, [], 0.0
    dominant = []
    total = 0.0
    for factor, (score, weight, label) in factors.items():
        if score is None:
            continue
        contribution = float(score) * weight / available
        total += contribution
        dominant.append(
            {
                "factor": factor,
                "label": label,
                "score": round(float(score), 3),
                "weight": round(weight, 3),
                "contribution": round(contribution, 3),
            }
        )
    dominant.sort(key=lambda item: item["contribution"], reverse=True)
    return float(np.clip(total, 0.0, 1.0)), dominant[:3], available / configured if configured else 0.0


def _threshold_matrix_summary(matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "matrix_id": matrix["matrix_id"],
        "algorithm_id": matrix["algorithm_id"],
        "status": matrix["status"],
        "updated_at": matrix.get("updated_at"),
        "updated_by": matrix.get("updated_by"),
    }


def _risk_item(
    hazard_type: str,
    score: float,
    dominant_factors: list[dict[str, Any]],
    input_completeness: float,
    *,
    threshold_matrix: dict[str, Any],
    score_cap: float,
    missing_critical_factors: list[str],
) -> dict[str, Any]:
    meta = HAZARD_TYPES[hazard_type]
    capped = min(float(score), score_cap)
    return {
        "hazard_type": hazard_type,
        "label": meta["label"],
        "risk_domain": list(meta["risk_domain"]),
        "feature_type": meta["feature_type"],
        "score": round(capped, 3),
        "risk_level": matrix_score_level(capped, threshold_matrix),
        "score_source": "sounding_profile_indices",
        "source_indices": [item["factor"] for item in dominant_factors],
        "dominant_factors": dominant_factors,
        "input_completeness": round(float(input_completeness), 3),
        "missing_critical_factors": missing_critical_factors,
        "score_cap_applied": bool(score > score_cap or missing_critical_factors),
        "score_cap_value": score_cap,
    }


def _station_risk_diagnoses(
    station_diagnostics: list[dict[str, Any]],
    threshold_matrix: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    matrix = threshold_matrix or load_threshold_matrix()
    out: list[dict[str, Any]] = []
    for item in station_diagnostics:
        indices = item.get("indices") or {}
        cape = _score_pos(indices.get("cape_j_kg"), 500.0, 2500.0)
        pw = _score_pos(indices.get("precipitable_water_mm"), 30.0, 55.0)
        cin = _score_neg(abs(float(indices["cin_j_kg"])) if indices.get("cin_j_kg") is not None else None, 150.0, 25.0)
        lcl = _score_pos(indices.get("lcl_pressure_hpa"), 650.0, 900.0)

        short_score, short_factors, short_complete = _weighted_score(
            {
                "cape": (cape, 0.38, "CAPE"),
                "precipitable_water": (pw, 0.44, "可降水量"),
                "cin_breakable": (cin, 0.18, "CIN 可突破"),
            }
        )
        rotating_score, rotating_factors, rotating_complete = _weighted_score(
            {
                "cape": (cape, 0.45, "CAPE"),
                "lcl": (lcl, 0.25, "LCL 低云底"),
                "cin_breakable": (cin, 0.30, "CIN 可突破"),
            }
        )
        risks = [
            _risk_item(
                "short_duration_heavy_rain",
                short_score,
                short_factors,
                short_complete * 0.6,
                threshold_matrix=matrix,
                score_cap=0.65,
                missing_critical_factors=["低层辐合/水汽辐合触发", "短时降水或雨强"],
            ),
            _risk_item(
                "rotating_storm_or_supercell",
                rotating_score,
                rotating_factors,
                rotating_complete * 0.5,
                threshold_matrix=matrix,
                score_cap=0.55,
                missing_critical_factors=["0-6km深层风切变", "0-1km低层风切变", "SRH风暴相对螺旋度"],
            ),
        ]
        composite_score = max(risk["score"] for risk in risks) if risks else 0.0
        composite_factors = risks[0]["dominant_factors"] if risks else []
        risks.append(
            _risk_item(
                "severe_convection_composite",
                composite_score,
                composite_factors,
                max((risk["input_completeness"] for risk in risks), default=0.0),
                threshold_matrix=matrix,
                score_cap=0.65,
                missing_critical_factors=sorted({factor for risk in risks for factor in risk["missing_critical_factors"]}),
            )
        )
        risks.sort(key=lambda risk: risk["score"], reverse=True)
        out.append(
            {
                "station_id": item["station_id"],
                "station_name": item.get("station_name"),
                "station_lat": item.get("station_lat"),
                "station_lon": item.get("station_lon"),
                "observation_time": item.get("observation_time"),
                "risks": risks,
            }
        )
    return out


def _grid(domain: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    step = float(domain.get("resolution", 1.0))
    lat = np.arange(float(domain["lat_min"]), float(domain["lat_max"]) + step * 0.5, step)
    lon = np.arange(float(domain["lon_min"]), float(domain["lon_max"]) + step * 0.5, step)
    return lat, lon


def _analysis_field(
    frame: pd.DataFrame,
    value_column: str,
    lat: np.ndarray,
    lon: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    rows = frame[["station_lon", "station_lat", value_column]].dropna()
    points = rows[["station_lon", "station_lat"]].to_numpy(dtype=float)
    values = rows[value_column].to_numpy(dtype=float)
    gx, gy = np.meshgrid(lon, lat)
    if len(rows) < 3:
        field = np.full((lat.size, lon.size), np.nan, dtype=float)
    else:
        linear = griddata(points, values, (gx, gy), method="linear")
        nearest = griddata(points, values, (gx, gy), method="nearest")
        field = np.where(np.isfinite(linear), linear, nearest)
    distance_km = np.full(field.shape, np.nan, dtype=float)
    if len(rows):
        tree = cKDTree(points)
        dist_deg, _ = tree.query(np.column_stack([gx.ravel(), gy.ravel()]), k=1)
        distance_km = dist_deg.reshape(field.shape) * 111.32
    quality = {
        "method": "linear_with_nearest_fill",
        "station_count": int(len(rows)),
        "grid_shape": [int(lat.size), int(lon.size)],
        "mean_nearest_station_km": round(float(np.nanmean(distance_km)), 1) if np.isfinite(distance_km).any() else None,
        "max_nearest_station_km": round(float(np.nanmax(distance_km)), 1) if np.isfinite(distance_km).any() else None,
    }
    return field.astype(float), quality


def _center_features(
    values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    high_type: str,
    low_type: str,
    high_label: str,
    low_label: str,
    unit: str,
    level: str,
    confidence: float,
    max_centers: int = 2,
) -> list[dict[str, Any]]:
    smooth = ndimage.gaussian_filter(np.asarray(values, dtype=float), sigma=1.2, mode="nearest")
    finite = np.isfinite(smooth)
    if not finite.any():
        return []
    features: list[dict[str, Any]] = []
    for mode, feature_type, label in [
        ("max", high_type, high_label),
        ("min", low_type, low_label),
    ]:
        filt = (
            ndimage.maximum_filter(smooth, size=7, mode="nearest")
            if mode == "max"
            else ndimage.minimum_filter(smooth, size=7, mode="nearest")
        )
        ys, xs = np.where((smooth == filt) & finite)
        candidates: list[tuple[float, int, int]] = []
        for y, x in zip(ys, xs):
            if y in {0, smooth.shape[0] - 1} or x in {0, smooth.shape[1] - 1}:
                continue
            y0, y1 = max(0, y - 4), min(smooth.shape[0], y + 5)
            x0, x1 = max(0, x - 4), min(smooth.shape[1], x + 5)
            local = smooth[y0:y1, x0:x1]
            prominence = smooth[y, x] - np.nanmean(local) if mode == "max" else np.nanmean(local) - smooth[y, x]
            if np.isfinite(prominence):
                candidates.append((float(prominence), int(y), int(x)))
        candidates.sort(reverse=True)
        for rank, (prominence, y, x) in enumerate(candidates[:max_centers], start=1):
            features.append(
                {
                    "id": f"sounding-{feature_type}-{rank:03d}",
                    "type": feature_type,
                    "feature_type": feature_type,
                    "name": f"{level} {label}",
                    "label": label,
                    "level": level,
                    "value": round(float(values[y, x]), 2),
                    "unit": unit,
                    "confidence": round(float(min(0.9, confidence + min(prominence, 10.0) * 0.01)), 2),
                    "geometry": {"type": "point", "coordinates": [float(lon[x]), float(lat[y])]},
                    "evidence": [
                        f"{level} sounding objective analysis local {'maximum' if mode == 'max' else 'minimum'}",
                        f"local prominence {prominence:.2f} {unit}",
                    ],
                }
            )
    return features


def _station_features(frame: pd.DataFrame, level: str) -> dict[str, Any]:
    features = []
    for row in frame.sort_values("station_id").itertuples(index=False):
        props = {
            "feature_type": "sounding_station_wind",
            "station_id": str(row.station_id),
            "station_name": _json_text(getattr(row, "station_name", None)),
            "level": level,
            "pressure_hpa": _json_float(row.pressure_hpa),
            "height_m": _json_float(row.geopotential_height_m),
            "temperature_c": _json_float(row.temperature_c),
            "dew_point_temperature_c": _json_float(row.dew_point_temperature_c),
            "wind_direction_degree": _json_float(row.wind_direction_degree),
            "wind_speed_m_s": _json_float(row.wind_speed_m_s),
        }
        features.append(point_feature(float(row.station_lon), float(row.station_lat), props))
    return feature_collection(features)


def _system_confidence(quality: dict[str, Any]) -> float:
    count_score = min(1.0, float(quality.get("station_count") or 0) / 220.0)
    distance = float(quality.get("mean_nearest_station_km") or 220.0)
    distance_score = max(0.0, min(1.0, (260.0 - distance) / 220.0))
    return round(0.45 + 0.35 * count_score + 0.15 * distance_score, 2)


def _trough_ridge_systems(
    z500: np.ndarray,
    u500: np.ndarray | None,
    v500: np.ndarray | None,
    lat: np.ndarray,
    lon: np.ndarray,
    confidence: float,
    support_distance_km: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    thresholds = {
        "trough_ridge": {
            "analysis_lat_min": 15.0,
            "analysis_lat_max": 55.0,
            "analysis_lon_min": 60.0,
            "analysis_lon_max": 150.0,
            "smooth_radius_km": 170.0,
            "second_smooth_radius_km": 75.0,
            "component_percentile": 76.0,
            "seed_percentile": 86.0,
            "min_points_per_line": 4,
            "min_length_km": 320.0,
            "max_lines": 8,
            "output_points": 28,
            "low_lat_zonal_filter_max_lat": 30.0,
            "low_lat_zonal_max_aspect_ratio": 1.5,
            "enable_meridional_valley_tracks": True,
            "meridional_track_lon_min": 95.0,
            "meridional_track_lon_max": 120.0,
            "meridional_track_lat_min": 15.0,
            "meridional_track_lat_max": 52.0,
            "meridional_track_max_lines": 2,
        }
    }
    vort = None
    if u500 is not None and v500 is not None:
        dudy = np.gradient(u500, lat, axis=0, edge_order=1) / 111_320.0
        dvdx = np.gradient(v500, lon, axis=1, edge_order=1) / (
            111_320.0 * np.maximum(np.cos(np.deg2rad(lat))[:, None], 0.2)
        )
        vort = dvdx - dudy
    troughs, ridges = detect_trough_ridge(z500, lat, lon, thresholds, vorticity500=vort)
    systems: list[dict[str, Any]] = []
    for feature in [*troughs, *ridges]:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}
        coordinates = np.asarray(geometry.get("coordinates") or [], dtype=float)
        support_mean_km = None
        support_p90_km = None
        if (
            support_distance_km is not None
            and np.asarray(support_distance_km).shape == np.asarray(z500).shape
            and coordinates.ndim == 2
            and coordinates.shape[0] >= 2
        ):
            support = np.asarray(support_distance_km, dtype=float)
            y_index = np.abs(np.asarray(lat, dtype=float)[:, None] - coordinates[:, 1][None, :]).argmin(axis=0)
            x_index = np.abs(np.asarray(lon, dtype=float)[:, None] - coordinates[:, 0][None, :]).argmin(axis=0)
            line_support = support[y_index, x_index]
            line_support = line_support[np.isfinite(line_support)]
            if line_support.size:
                support_mean_km = float(np.nanmean(line_support))
                support_p90_km = float(np.nanpercentile(line_support, 90))
                if support_mean_km > 380.0 or support_p90_km > 650.0:
                    continue
        feature_type = str(props.get("feature_type") or props.get("type") or "trough_candidate")
        feature_type = {"trough": "trough_candidate", "ridge": "ridge_candidate"}.get(feature_type, feature_type)
        systems.append(
            {
                "id": props.get("id") or f"sounding-{feature_type}-{len(systems) + 1:03d}",
                "type": feature_type,
                "feature_type": feature_type,
                "name": props.get("name") or props.get("label") or feature_type,
                "level": "500hPa",
                "confidence": round(min(float(props.get("confidence") or confidence), confidence), 2),
                "method": props.get("method"),
                "analysis_domain": props.get("analysis_domain"),
                "candidate_source": props.get("candidate_source"),
                "support_mean_distance_km": round(support_mean_km, 1) if support_mean_km is not None else None,
                "support_p90_distance_km": round(support_p90_km, 1) if support_p90_km is not None else None,
                "geometry": {"type": "line", "coordinates": geometry.get("coordinates") or []},
                "evidence": [
                    "500hPa sounding objective height field axis extraction",
                    "axis generated from station-based objective analysis, not model forecast grid",
                ],
            }
        )
    return systems


def diagnose_sounding_situation(
    csv_path: str | Path,
    *,
    pressure_level: int = 500,
    domain: dict[str, float] | None = None,
) -> dict[str, Any]:
    level = _level_name(pressure_level)
    df = pd.read_csv(csv_path)
    frame = df[df["requested_level"].astype(str) == level].copy()
    if frame.empty:
        raise ValueError(f"no sounding rows for {level}")
    frame = frame.dropna(subset=["station_lat", "station_lon", "geopotential_height_m", "temperature_c"])
    if int(pressure_level) == 500:
        # ponytail: fixed sanity gate for the current 500hPa map layer; make this per-level when more sounding layers ship.
        frame = frame[frame["geopotential_height_m"].between(4500.0, 6500.0)]
    if frame.empty:
        raise ValueError(f"no quality-controlled sounding rows for {level}")
    u, v = _wind_components(frame["wind_direction_degree"].to_numpy(), frame["wind_speed_m_s"].to_numpy())
    frame["u_wind_m_s"] = u
    frame["v_wind_m_s"] = v

    grid_domain = dict(DEFAULT_DOMAIN)
    if domain:
        grid_domain.update(domain)
    lat, lon = _grid(grid_domain)

    z500, z_quality = _analysis_field(frame, "geopotential_height_m", lat, lon)
    t500, t_quality = _analysis_field(frame, "temperature_c", lat, lon)
    u500, u_quality = _analysis_field(frame, "u_wind_m_s", lat, lon)
    v500, v_quality = _analysis_field(frame, "v_wind_m_s", lat, lon)
    confidence = _system_confidence(z_quality)

    systems = []
    systems.extend(
        _center_features(
            z500,
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
        _center_features(
            t500,
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
    systems.extend(_trough_ridge_systems(z500, u500, v500, lat, lon, confidence))

    station_diagnostics = _station_diagnostics(df)
    threshold_matrix = load_threshold_matrix()
    obs_time = pd.to_datetime(frame["request_datetime_bjt"].iloc[0]).isoformat()
    return {
        "data_type": "sounding",
        "observation_time": obs_time,
        "analysis_level": level,
        "threshold_matrix": _threshold_matrix_summary(threshold_matrix),
        "domain": {
            "lat_min": float(lat.min()),
            "lat_max": float(lat.max()),
            "lon_min": float(lon.min()),
            "lon_max": float(lon.max()),
            "resolution": float(grid_domain["resolution"]),
        },
        "analysis_fields": {
            "z500": {"values": z500, "lat": lat, "lon": lon, "unit": "gpm", "quality": z_quality},
            "t500": {"values": t500, "lat": lat, "lon": lon, "unit": "degC", "quality": t_quality},
            "u500": {"values": u500, "lat": lat, "lon": lon, "unit": "m/s", "quality": u_quality},
            "v500": {"values": v500, "lat": lat, "lon": lon, "unit": "m/s", "quality": v_quality},
        },
        "systems": systems,
        "station_features": _station_features(frame, level),
        "station_diagnostics": station_diagnostics,
        "station_risk_diagnoses": _station_risk_diagnoses(station_diagnostics, threshold_matrix),
        "summary": f"{obs_time} {level} sounding objective analysis generated {len(systems)} weather systems.",
    }
