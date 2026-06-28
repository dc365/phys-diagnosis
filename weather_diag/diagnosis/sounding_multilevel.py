from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_diag.config import load_thresholds
from weather_diag.diagnosis import sounding as legacy
from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field
from weather_diag.diagnosis.risk_taxonomy import HAZARD_TYPES
from weather_diag.diagnostics.grid import derivatives_lonlat
from weather_diag.features.convergence import detect_low_level_convergence, detect_upper_divergence
from weather_diag.features.front import detect_front_candidates
from weather_diag.features.low_level_jet import detect_low_level_jet
from weather_diag.features.moisture_transport import detect_moisture_transport
from weather_diag.features.upper_jet import detect_upper_jet
from weather_diag.features.vortex import detect_cold_vortex


MULTILEVELS = (850, 700, 500, 300, 200)
MULTILEVEL_CONFIG = ObjectiveAnalysisConfig(
    radii_km=(760.0, 520.0, 320.0),
    smoothing_sigma_grid=0.75,
    max_support_distance_km=850.0,
)


def _rh_from_t_td(temp_c: np.ndarray, dewpoint_c: np.ndarray) -> np.ndarray:
    temp = np.asarray(temp_c, dtype=float)
    dew = np.asarray(dewpoint_c, dtype=float)
    es_ratio = np.exp((17.625 * dew / (243.04 + dew)) - (17.625 * temp / (243.04 + temp)))
    return np.clip(100.0 * es_ratio, 0.0, 100.0)


def _specific_humidity_gkg(dewpoint_c: np.ndarray, pressure_hpa: float) -> np.ndarray:
    dew = np.asarray(dewpoint_c, dtype=float)
    e = 6.112 * np.exp((17.67 * dew) / (dew + 243.5))
    q = 622.0 * e / np.maximum(float(pressure_hpa) - 0.378 * e, 1.0)
    return np.clip(q, 0.0, 40.0)


def _wind_components(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return legacy._wind_components(frame["wind_direction_degree"].to_numpy(), frame["wind_speed_m_s"].to_numpy())


def _level_frame(all_rows: pd.DataFrame, level: int) -> pd.DataFrame:
    key = f"{int(level)}hPa"
    frame = all_rows[all_rows["requested_level"].astype(str).eq(key)].copy()
    frame = frame.dropna(subset=["station_lat", "station_lon", "temperature_c", "dew_point_temperature_c"])
    if frame.empty:
        return frame
    u, v = _wind_components(frame)
    frame["u_wind_m_s"] = u
    frame["v_wind_m_s"] = v
    frame["relative_humidity_percent"] = _rh_from_t_td(frame["temperature_c"].to_numpy(), frame["dew_point_temperature_c"].to_numpy())
    frame["specific_humidity_gkg"] = _specific_humidity_gkg(frame["dew_point_temperature_c"].to_numpy(), level)
    return frame


def _analyze(frame: pd.DataFrame, column: str, lat: np.ndarray, lon: np.ndarray, *, config: ObjectiveAnalysisConfig = MULTILEVEL_CONFIG):
    if column not in frame.columns or frame[column].dropna().shape[0] < 3:
        return None
    return objective_analysis_field(frame, column, lat, lon, config=config)


def _field_payload(obj, unit: str, lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    return {
        "values": obj.values,
        "lat": lat,
        "lon": lon,
        "unit": unit,
        "quality": obj.quality,
        "support_distance_km": obj.support_distance_km,
        "support_mask": obj.support_mask,
    }


def _derived_payload(values: np.ndarray, unit: str, lat: np.ndarray, lon: np.ndarray, *, method: str) -> dict[str, Any]:
    finite = values[np.isfinite(values)]
    return {
        "values": values,
        "lat": lat,
        "lon": lon,
        "unit": unit,
        "quality": {
            "method": method,
            "available": bool(finite.size),
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        },
        "support_distance_km": None,
        "support_mask": np.isfinite(values),
    }


def _div_vort(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    dudx, dudy = derivatives_lonlat(u, lat, lon)
    dvdx, dvdy = derivatives_lonlat(v, lat, lon)
    return dudx + dvdy, dvdx - dudy


def _score01(values: np.ndarray, low: float, high: float, *, reverse: bool = False) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    lo = float(low)
    hi = float(high)
    if np.isclose(lo, hi):
        out = np.zeros_like(arr, dtype=float)
    elif hi > lo:
        out = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    else:
        out = np.clip((lo - arr) / (lo - hi), 0.0, 1.0)
    return 1.0 - out if reverse else out


def _common_thresholds(thresholds: dict[str, Any]) -> dict[str, Any]:
    return dict((thresholds.get("risk_scoring") or {}).get("common") or {})


def _range(common: dict[str, Any], key: str, default_low: float, default_high: float) -> tuple[float, float]:
    cfg = common.get(key) or {}
    return float(cfg.get("low", default_low)), float(cfg.get("high", default_high))


def _cold_t500_score(values: np.ndarray, common: dict[str, Any]) -> np.ndarray:
    cfg = common.get("t500_c") or {}
    warm = float(cfg.get("high", -8.0))
    cold = float(cfg.get("low", -18.0))
    return np.clip((warm - np.asarray(values, dtype=float)) / max(warm - cold, 1.0e-6), 0.0, 1.0)


def _weighted_sum(weighted_terms: list[tuple[np.ndarray, float]]) -> np.ndarray:
    total_weight = sum(max(float(weight), 0.0) for _value, weight in weighted_terms)
    if total_weight <= 0:
        return np.zeros_like(weighted_terms[0][0], dtype=float) if weighted_terms else np.zeros((1, 1), dtype=float)
    total = sum(np.asarray(value, dtype=float) * max(float(weight), 0.0) for value, weight in weighted_terms)
    return np.clip(total / total_weight, 0.0, 1.0)


def build_multilevel_fields(csv_path: str | Path, lat: np.ndarray, lon: np.ndarray) -> dict[str, dict[str, Any]]:
    rows = pd.read_csv(csv_path)
    fields: dict[str, dict[str, Any]] = {}
    analyzed: dict[str, Any] = {}
    for level in MULTILEVELS:
        frame = _level_frame(rows, level)
        if frame.empty:
            continue
        for name, column, unit in [
            (f"t{level}", "temperature_c", "degC"),
            (f"td{level}", "dew_point_temperature_c", "degC"),
            (f"rh{level}", "relative_humidity_percent", "%"),
            (f"q{level}", "specific_humidity_gkg", "g/kg"),
            (f"u{level}", "u_wind_m_s", "m/s"),
            (f"v{level}", "v_wind_m_s", "m/s"),
        ]:
            obj = _analyze(frame, column, lat, lon)
            if obj is None:
                continue
            fields[name] = _field_payload(obj, unit, lat, lon)
            analyzed[name] = obj.values
        if "geopotential_height_m" in frame.columns and frame["geopotential_height_m"].dropna().shape[0] >= 3:
            obj = _analyze(frame, "geopotential_height_m", lat, lon)
            if obj is not None:
                fields[f"z{level}"] = _field_payload(obj, "gpm", lat, lon)
                analyzed[f"z{level}"] = obj.values
        if f"u{level}" in analyzed and f"v{level}" in analyzed:
            u = analyzed[f"u{level}"]
            v = analyzed[f"v{level}"]
            wind = np.hypot(u, v)
            div, vort = _div_vort(u, v, lat, lon)
            fields[f"wind{level}_speed"] = _derived_payload(wind, "m/s", lat, lon, method="hypot(u,v)")
            fields[f"div{level}"] = _derived_payload(div, "s^-1", lat, lon, method="divergence_from_sounding_wind")
            fields[f"vort{level}"] = _derived_payload(vort, "s^-1", lat, lon, method="vorticity_from_sounding_wind")
            analyzed[f"wind{level}_speed"] = wind
            analyzed[f"div{level}"] = div
            analyzed[f"vort{level}"] = vort
        if f"q{level}" in analyzed and f"wind{level}_speed" in analyzed:
            flux = analyzed[f"q{level}"] * analyzed[f"wind{level}_speed"]
            fields[f"moisture_flux{level}"] = _derived_payload(flux, "g/kg*m/s", lat, lon, method="q*wind_speed")
            analyzed[f"moisture_flux{level}"] = flux
    if "t700" in analyzed and "t500" in analyzed and "z700" in analyzed and "z500" in analyzed:
        dz_km = np.maximum((analyzed["z500"] - analyzed["z700"]) / 1000.0, 0.1)
        lapse = (analyzed["t700"] - analyzed["t500"]) / dz_km
        fields["lapse_rate_700_500"] = _derived_payload(lapse, "degC/km", lat, lon, method="(t700-t500)/(z500-z700)")
        analyzed["lapse_rate_700_500"] = lapse
    if "u850" in analyzed and "u500" in analyzed and "v850" in analyzed and "v500" in analyzed:
        shear = np.hypot(analyzed["u500"] - analyzed["u850"], analyzed["v500"] - analyzed["v850"])
        fields["shear_850_500"] = _derived_payload(shear, "m/s", lat, lon, method="vector_shear_850_500")
        analyzed["shear_850_500"] = shear
    fields["_analyzed"] = analyzed  # internal convenience, removed by caller
    return fields


def _geojson_feature_to_system(feature: dict[str, Any], fallback_type: str, index: int) -> dict[str, Any] | None:
    geometry = feature.get("geometry") or {}
    props = feature.get("properties") or {}
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "LineString":
        sys_geom = {"type": "line", "coordinates": coords}
    elif kind == "Point":
        sys_geom = {"type": "point", "coordinates": coords}
    elif kind in {"Polygon", "MultiPolygon"}:
        sys_geom = {"type": "polygon", "geojson_type": kind, "coordinates": coords, "bbox": props.get("bbox") or props.get("source_area_bbox")}
    else:
        return None
    feature_type = str(props.get("feature_type") or fallback_type)
    return {
        "id": props.get("id") or f"sounding-{feature_type}-{index:03d}",
        "type": feature_type,
        "feature_type": feature_type,
        "name": props.get("title") or props.get("label") or feature_type,
        "level": props.get("level") or "",
        "confidence": float(props.get("confidence") or 0.62),
        "geometry": sys_geom,
        "evidence": props.get("evidence") or ["sounding multilevel objective analysis support"],
        **{key: value for key, value in props.items() if key not in {"id", "evidence"}},
    }


def build_multilevel_systems(analysis_fields: dict[str, dict[str, Any]], lat: np.ndarray, lon: np.ndarray) -> list[dict[str, Any]]:
    analyzed = analysis_fields.get("_analyzed") or {}
    thresholds = load_thresholds()
    systems: list[dict[str, Any]] = []

    def add(features: list[dict[str, Any]], fallback: str) -> None:
        for feature in features:
            system = _geojson_feature_to_system(feature, fallback, len(systems) + 1)
            if system is not None:
                systems.append(system)

    try:
        if "wind850_speed" in analyzed and "u850" in analyzed and "v850" in analyzed:
            add(detect_low_level_jet(analyzed["wind850_speed"], analyzed.get("moisture_flux850"), lat, lon, thresholds, u850=analyzed["u850"], v850=analyzed["v850"]), "low_level_jet")
    except Exception:
        pass
    try:
        if "moisture_flux850" in analyzed:
            add(detect_moisture_transport(analyzed["moisture_flux850"], lat, lon, thresholds, u850=analyzed.get("u850"), v850=analyzed.get("v850")), "moisture_transport")
    except Exception:
        pass
    try:
        if "div850" in analyzed:
            add(detect_low_level_convergence(analyzed["div850"], lat, lon, thresholds, u850=analyzed.get("u850"), v850=analyzed.get("v850")), "low_level_convergence")
    except Exception:
        pass
    try:
        for level in (200, 300):
            if f"div{level}" in analyzed:
                add(detect_upper_divergence(analyzed[f"div{level}"], lat, lon, thresholds, level, u_upper=analyzed.get(f"u{level}"), v_upper=analyzed.get(f"v{level}")), "upper_divergence")
    except Exception:
        pass
    try:
        for level in (200, 300):
            if f"u{level}" in analyzed and f"v{level}" in analyzed:
                add(detect_upper_jet(analyzed[f"u{level}"], analyzed[f"v{level}"], lat, lon, thresholds, level=level, divergence_field=analyzed.get(f"div{level}")), "upper_jet")
    except Exception:
        pass
    try:
        if all(key in analyzed for key in ["z500", "u500", "v500", "t500"]):
            add(detect_cold_vortex(analyzed["z500"], lat, lon, thresholds, u=analyzed["u500"], v=analyzed["v500"], temperature=analyzed["t500"], level=500), "cold_vortex")
    except Exception:
        pass
    try:
        if all(key in analyzed for key in ["t850", "u850", "v850"]):
            add(detect_front_candidates(analyzed["t850"], analyzed.get("div850"), None, lat, lon, thresholds, u850=analyzed["u850"], v850=analyzed["v850"], rh850=analyzed.get("rh850")), "front_candidate")
    except Exception:
        pass
    return systems


def _risk_level(score: float) -> str:
    if score >= 0.8:
        return "very_high"
    if score >= 0.6:
        return "high"
    if score >= 0.4:
        return "medium"
    if score >= 0.2:
        return "low"
    return "very_low"


def _risk_grid_payload(values: np.ndarray, lat: np.ndarray, lon: np.ndarray, hazard: str, sources: list[str]) -> dict[str, Any]:
    meta = HAZARD_TYPES[hazard]
    return _derived_payload(values, "0-1", lat, lon, method="sounding_multilevel_risk:" + "+".join(sources)) | {
        "risk_metadata": {
            "hazard_type": hazard,
            "label": meta["label"],
            "feature_type": meta["feature_type"],
            "sources": sources,
            "threshold_source": "configs/thresholds.yaml:risk_scoring.common",
        }
    }


def build_multilevel_risk_fields(analysis_fields: dict[str, dict[str, Any]], lat: np.ndarray, lon: np.ndarray) -> dict[str, dict[str, Any]]:
    a = analysis_fields.get("_analyzed") or {}
    thresholds = load_thresholds()
    common = _common_thresholds(thresholds)
    risks: dict[str, dict[str, Any]] = {}
    shape = (len(lat), len(lon))

    q_low, q_high = _range(common, "q850_gkg", 6.0, 14.0)
    rh850_low, rh850_high = _range(common, "rh850", 60.0, 90.0)
    rh700_low, rh700_high = _range(common, "rh700", 60.0, 90.0)
    shear_low, shear_high = _range(common, "deep_shear_ms", 10.0, 25.0)
    lapse_low, lapse_high = _range(common, "lapse_rate_700_500", 6.0, 8.0)
    wind_low, wind_high = _range(common, "wind500_ms", 15.0, 30.0)
    conv_min = float((thresholds.get("convergence") or {}).get("convergence_min", 1.0e-5))
    div_min = float((thresholds.get("upper_divergence") or {}).get("divergence_min", 1.0e-5))

    moisture = _score01(a.get("q850", np.zeros(shape)), q_low, q_high)
    rh_terms = []
    if "rh850" in a:
        rh_terms.append(_score01(a["rh850"], rh850_low, rh850_high))
    if "rh700" in a:
        rh_terms.append(_score01(a["rh700"], rh700_low, rh700_high))
    rh_deep = np.nanmean(rh_terms, axis=0) if rh_terms else np.zeros(shape)
    convergence = _score01(-a.get("div850", np.zeros(shape)), conv_min * 0.2, conv_min * 1.5)
    shear = _score01(a.get("shear_850_500", np.zeros(shape)), shear_low, shear_high)
    lapse = _score01(a.get("lapse_rate_700_500", np.zeros(shape)), lapse_low, lapse_high)
    mid_cold = _cold_t500_score(a.get("t500", np.zeros(shape)), common)
    upper_wind = _score01(a.get("wind300_speed", a.get("wind200_speed", np.zeros(shape))), wind_low, wind_high)
    upper_div = _score01(np.maximum(a.get("div300", 0.0), a.get("div200", 0.0)), div_min * 0.2, div_min * 1.5)

    persistent = _weighted_sum([(moisture, 0.40), (rh_deep, 0.28), (convergence, 0.20), (upper_div, 0.12)])
    short_heavy = _weighted_sum([(moisture, 0.36), (rh_deep, 0.22), (convergence, 0.26), (upper_div, 0.16)])
    thunder_gale = _weighted_sum([(lapse, 0.25), (shear, 0.25), (upper_wind, 0.25), (mid_cold, 0.25)])
    hail = _weighted_sum([(lapse, 0.28), (shear, 0.28), (mid_cold, 0.28), (convergence, 0.16)])
    rotating = np.clip(_weighted_sum([(shear, 0.45), (convergence, 0.25), (lapse, 0.20), (upper_wind, 0.10)]), 0.0, 0.62)
    composite = np.nanmax(np.stack([short_heavy, thunder_gale, hail, rotating]), axis=0)

    risks["risk_persistent_heavy_rain_score"] = _risk_grid_payload(persistent, lat, lon, "persistent_heavy_rain", ["q850", "rh850/rh700", "div850", "div200/300"])
    risks["risk_short_duration_heavy_rain_score"] = _risk_grid_payload(short_heavy, lat, lon, "short_duration_heavy_rain", ["q850", "div850", "upper_divergence"])
    risks["risk_thunderstorm_gale_score"] = _risk_grid_payload(thunder_gale, lat, lon, "thunderstorm_gale", ["lapse_rate_700_500", "shear_850_500", "upper_wind", "t500"])
    risks["risk_hail_score"] = _risk_grid_payload(hail, lat, lon, "hail", ["lapse_rate_700_500", "shear_850_500", "t500", "div850"])
    risks["risk_rotating_storm_score"] = _risk_grid_payload(rotating, lat, lon, "rotating_storm_or_supercell", ["shear_850_500", "div850", "lapse_rate_700_500"])
    risks["risk_severe_convection_composite_score"] = _risk_grid_payload(composite, lat, lon, "severe_convection_composite", ["short_heavy", "gale", "hail", "rotating"])
    return risks


def augment_station_risks(station_risk_items: list[dict[str, Any]], station_diagnostics: list[dict[str, Any]], thresholds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    thresholds = thresholds or load_thresholds()
    common = _common_thresholds(thresholds)
    cape_low, cape_high = _range(common, "cape", 500.0, 2500.0)
    pw_low, pw_high = _range(common, "pw_mm", 30.0, 55.0)
    by_id = {str(item.get("station_id")): item for item in station_risk_items}
    for diag in station_diagnostics:
        station_id = str(diag.get("station_id"))
        target = by_id.get(station_id)
        if not target:
            continue
        indices = diag.get("indices") or {}
        cape = float(indices.get("cape_j_kg") or 0.0)
        pw = float(indices.get("precipitable_water_mm") or 0.0)
        lclp = indices.get("lcl_pressure_hpa")
        cape_s = float(np.clip((cape - cape_low) / max(cape_high - cape_low, 1.0e-6), 0.0, 1.0))
        pw_s = float(np.clip((pw - pw_low) / max(pw_high - pw_low, 1.0e-6), 0.0, 1.0))
        lcl_s = float(np.clip((float(lclp or 650.0) - 650.0) / 250.0, 0.0, 1.0))
        extra = [
            ("persistent_heavy_rain", min(0.70, 0.58 * pw_s + 0.22 * cape_s)),
            ("thunderstorm_gale", min(0.60, 0.55 * cape_s + 0.15 * (1 - pw_s))),
            ("hail", min(0.56, 0.48 * cape_s + 0.12 * (1 - pw_s))),
        ]
        existing = {risk.get("hazard_type") for risk in target.get("risks") or []}
        for hazard, score in extra:
            if hazard in existing:
                continue
            meta = HAZARD_TYPES[hazard]
            target.setdefault("risks", []).append(
                {
                    "hazard_type": hazard,
                    "label": meta["label"],
                    "risk_domain": list(meta["risk_domain"]),
                    "feature_type": meta["feature_type"],
                    "score": round(float(score), 3),
                    "risk_level": _risk_level(float(score)),
                    "score_source": "sounding_profile_indices_extended",
                    "threshold_source": "configs/thresholds.yaml:risk_scoring.common",
                    "source_indices": ["cape", "precipitable_water", "lcl"],
                    "dominant_factors": [
                        {"factor": "cape", "label": "CAPE", "score": round(cape_s, 3), "contribution": round(0.45 * cape_s, 3)},
                        {"factor": "precipitable_water", "label": "可降水量", "score": round(pw_s, 3), "contribution": round(0.45 * pw_s, 3)},
                        {"factor": "lcl", "label": "LCL", "score": round(lcl_s, 3), "contribution": round(0.1 * lcl_s, 3)},
                    ],
                    "input_completeness": 0.45,
                    "missing_critical_factors": ["触发系统", "深层/低层风切变或SRH"],
                    "score_cap_applied": True,
                    "score_cap_value": 0.70 if hazard == "persistent_heavy_rain" else 0.60,
                }
            )
        target["risks"] = sorted(target.get("risks") or [], key=lambda risk: float(risk.get("score") or 0.0), reverse=True)
    return list(by_id.values())


def augment_sounding_result(result: dict[str, Any], analysis_csv: str | Path, lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    additions = build_multilevel_fields(analysis_csv, lat, lon)
    analyzed = additions.pop("_analyzed", {})
    additions_internal = {"_analyzed": analyzed}
    result["analysis_fields"].update(additions)
    systems = build_multilevel_systems({**additions, **additions_internal}, lat, lon)
    result["systems"] = list(result.get("systems") or []) + systems
    risks = build_multilevel_risk_fields({**additions, **additions_internal}, lat, lon)
    result["analysis_fields"].update(risks)
    result["station_risk_diagnoses"] = augment_station_risks(result.get("station_risk_diagnoses") or [], result.get("station_diagnostics") or [])
    result["multilevel_summary"] = {
        "available_levels": [level for level in MULTILEVELS if f"t{level}" in additions],
        "added_field_count": len(additions) + len(risks),
        "added_system_count": len(systems),
        "risk_grid_count": len(risks),
        "threshold_source": "shared_nafp_threshold_matrix",
    }
    return result
