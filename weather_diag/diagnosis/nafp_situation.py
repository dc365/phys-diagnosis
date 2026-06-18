from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from weather_diag.data.nafp import NAFP_SAMPLE_ROOT, NafpField, load_nafp_field, parse_run_time


DEFAULT_OPTIONAL_FIELDS = [
    ("uv", "500", "uv500"),
    ("uv", "850", "uv850"),
    ("q", "850", "q850"),
    ("rh", "850", "rh850"),
    ("div", "850", "div850"),
    ("ttadv", "850", "ttadv850"),
    ("div", "200", "div200"),
    ("div", "300", "div300"),
    ("pv", "300", "pv300"),
    ("pvadv", "300", "pvadv300"),
    ("w", "700", "w700"),
    ("kindex", "999", "kindex"),
    ("cape", "999", "cape"),
    ("cin", "999", "cin"),
    ("tcwv", "999", "tcwv"),
    ("rain6", "999", "rain6"),
    ("shr850-200", "999", "shr850-200"),
]


def field_array(field: NafpField, preferred: str | None = None) -> np.ndarray | None:
    if not field.exists:
        return None
    if preferred and preferred in field.values:
        return field.values[preferred]
    if len(field.values) == 1:
        return next(iter(field.values.values()))
    return None


def finite_stats(values: np.ndarray) -> dict[str, Any]:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return {"min": None, "max": None, "mean": None, "p75": None, "p90": None}
    return {
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "p75": float(np.nanpercentile(valid, 75)),
        "p90": float(np.nanpercentile(valid, 90)),
    }


def bbox_for_mask(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> list[float] | None:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return None
    return [
        float(lon[int(xs.min())]),
        float(lat[int(ys.min())]),
        float(lon[int(xs.max())]),
        float(lat[int(ys.max())]),
    ]


def largest_component(mask: np.ndarray, min_points: int = 12) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    idx = int(np.argmax(sizes)) + 1
    if float(sizes[idx - 1]) < min_points:
        return np.zeros_like(mask, dtype=bool)
    return labels == idx


def load_field_bundle(
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
) -> tuple[dict[str, NafpField], list[dict[str, Any]]]:
    fields = {"gh500": load_nafp_field(root, "gh", "500", run_time, forecast_hour, required=True)}
    missing = []
    for element, level, key in DEFAULT_OPTIONAL_FIELDS:
        field = load_nafp_field(root, element, level, run_time, forecast_hour, required=False)
        fields[key] = field
        if not field.exists:
            missing.append(
                {
                    "field": key,
                    "element": element,
                    "level": level,
                    "reason": field.missing_reason,
                    "source_path": field.source_path,
                }
            )
    return fields, missing


def score_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.45:
        return "moderate"
    return "low"


def _evidence(
    field_name: str,
    field: NafpField,
    signal: str,
    value: str,
    weight: float,
    contribution: float,
) -> dict[str, Any]:
    return {
        "field": field_name,
        "signal": signal,
        "value": value,
        "weight": weight,
        "contribution": contribution,
        "source_path": field.source_path,
    }


def _add_scalar_diagnostic(
    diagnostics: dict[str, Any],
    fields: dict[str, NafpField],
    key: str,
    preferred: str | None = None,
) -> np.ndarray | None:
    arr = field_array(fields[key], preferred)
    if arr is None:
        return None
    diagnostics[key] = {**finite_stats(arr), "source_path": fields[key].source_path}
    return arr


def _add_wind_diagnostic(
    diagnostics: dict[str, Any],
    fields: dict[str, NafpField],
    key: str,
    out_key: str,
) -> np.ndarray | None:
    field = fields[key]
    if not field.exists or "u" not in field.values or "v" not in field.values:
        return None
    speed = np.hypot(field.values["u"], field.values["v"])
    diagnostics[out_key] = {**finite_stats(speed), "source_path": field.source_path}
    return speed


def diagnose_systems(fields: dict[str, NafpField], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = []
    gh_field = fields["gh500"]
    gh = field_array(gh_field, "gh")
    if gh is None:
        return systems
    lat, lon = gh_field.lat, gh_field.lon

    threshold = 588.0 if float(np.nanmax(gh)) < 1000 else 5880.0
    subtropical_mask = largest_component(gh >= threshold, min_points=20)
    bbox = bbox_for_mask(subtropical_mask, lat, lon)
    if bbox:
        systems.append(
            {
                "id": "system-subtropical-high-500",
                "type": "subtropical_high",
                "name": "500hPa subtropical high area",
                "level": "500",
                "geometry": {"type": "bbox", "bbox": bbox},
                "confidence": 0.78,
                "diagnosis": f"500hPa height field has a contiguous area above {threshold:g}.",
                "evidence": [
                    {
                        "field": "gh500",
                        "signal": "height threshold area",
                        "value": f"max={float(np.nanmax(gh)):.2f}, threshold={threshold:g}",
                        "source_path": gh_field.source_path,
                    }
                ],
            }
        )

    zonal_mean = np.nanmean(gh, axis=1, keepdims=True)
    anomaly = gh - zonal_mean
    diagnostics["gh500_anomaly"] = finite_stats(anomaly)
    for system_type, mask, confidence in [
        ("trough_candidate", anomaly <= np.nanpercentile(anomaly, 8), 0.52),
        ("ridge_candidate", anomaly >= np.nanpercentile(anomaly, 92), 0.52),
    ]:
        component = largest_component(mask, min_points=24)
        component_bbox = bbox_for_mask(component, lat, lon)
        if component_bbox:
            systems.append(
                {
                    "id": f"system-{system_type}-500",
                    "type": system_type,
                    "name": f"500hPa {system_type.replace('_', ' ')}",
                    "level": "500",
                    "geometry": {"type": "bbox", "bbox": component_bbox},
                    "confidence": confidence,
                    "diagnosis": "500hPa height anomaly identifies a candidate synoptic feature.",
                    "evidence": [
                        {
                            "field": "gh500",
                            "signal": "height anomaly",
                            "value": f"anomaly_p08={float(np.nanpercentile(anomaly, 8)):.2f}, anomaly_p92={float(np.nanpercentile(anomaly, 92)):.2f}",
                            "source_path": gh_field.source_path,
                        }
                    ],
                }
            )
    return systems


def _risk_region_from_arrays(fields: dict[str, NafpField], arrays: list[np.ndarray | None]) -> dict[str, Any]:
    base_field = fields["gh500"]
    valid_arrays = [arr for arr in arrays if arr is not None and np.isfinite(arr).any()]
    if not valid_arrays:
        return {"bbox": [float(base_field.lon.min()), float(base_field.lat.min()), float(base_field.lon.max()), float(base_field.lat.max())]}
    normalized = []
    for arr in valid_arrays:
        valid = arr[np.isfinite(arr)]
        low, high = np.nanpercentile(valid, [10, 90])
        scale = high - low
        if scale == 0:
            normalized.append(np.zeros_like(arr, dtype=float))
        else:
            normalized.append(np.clip((arr - low) / scale, 0, 1))
    risk = np.nanmean(np.stack(normalized), axis=0)
    mask = largest_component(risk >= np.nanpercentile(risk[np.isfinite(risk)], 85), min_points=16)
    bbox = bbox_for_mask(mask, base_field.lat, base_field.lon)
    if not bbox:
        bbox = [float(base_field.lon.min()), float(base_field.lat.min()), float(base_field.lon.max()), float(base_field.lat.max())]
    return {"bbox": bbox}


def diagnose_evidence_chains(fields: dict[str, NafpField], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    uv850_speed = _add_wind_diagnostic(diagnostics, fields, "uv850", "uv850_speed")
    q850 = _add_scalar_diagnostic(diagnostics, fields, "q850", "q")
    div850 = _add_scalar_diagnostic(diagnostics, fields, "div850", "div")
    w700 = _add_scalar_diagnostic(diagnostics, fields, "w700", "w")
    kindex = _add_scalar_diagnostic(diagnostics, fields, "kindex", "kindex")
    cape = _add_scalar_diagnostic(diagnostics, fields, "cape", "cape")
    cin = _add_scalar_diagnostic(diagnostics, fields, "cin", "cin")
    rain6 = _add_scalar_diagnostic(diagnostics, fields, "rain6", "rain6")
    shear = _add_scalar_diagnostic(diagnostics, fields, "shr850-200", "shr850-200")
    tcwv = _add_scalar_diagnostic(diagnostics, fields, "tcwv", "tcwv")
    div200 = _add_scalar_diagnostic(diagnostics, fields, "div200", "div")
    div300 = _add_scalar_diagnostic(diagnostics, fields, "div300", "div")
    pv300 = _add_scalar_diagnostic(diagnostics, fields, "pv300", "pv")
    pvadv300 = _add_scalar_diagnostic(diagnostics, fields, "pvadv300", "pvadv")

    moisture_flux = None
    if uv850_speed is not None and q850 is not None:
        moisture_flux = uv850_speed * q850
        diagnostics["moisture_flux850"] = finite_stats(moisture_flux)

    chains = [
        _heavy_rain_chain(fields, q850, moisture_flux, div850, w700, kindex, cape, rain6, tcwv),
        _convection_chain(fields, cape, cin, kindex, shear, q850, div850, div200, div300, pv300, pvadv300),
    ]
    return [chain for chain in chains if chain]


def _heavy_rain_chain(
    fields: dict[str, NafpField],
    q850: np.ndarray | None,
    moisture_flux: np.ndarray | None,
    div850: np.ndarray | None,
    w700: np.ndarray | None,
    kindex: np.ndarray | None,
    cape: np.ndarray | None,
    rain6: np.ndarray | None,
    tcwv: np.ndarray | None,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0
    if q850 is not None:
        p75 = float(np.nanpercentile(q850, 75))
        contribution = min(max((p75 - 8.0) / 8.0, 0.0), 1.0) * 0.18
        score += contribution
        evidence.append(_evidence("q850", fields["q850"], "low-level moisture", f"p75={p75:.2f} g/kg", 0.18, contribution))
    else:
        missing.append("q850")
    if tcwv is not None:
        p75 = float(np.nanpercentile(tcwv, 75))
        contribution = min(max((p75 - 30.0) / 35.0, 0.0), 1.0) * 0.12
        score += contribution
        evidence.append(_evidence("tcwv", fields["tcwv"], "column water vapor", f"p75={p75:.2f}", 0.12, contribution))
    else:
        missing.append("tcwv")
    if moisture_flux is not None:
        p90 = float(np.nanpercentile(moisture_flux, 90))
        contribution = min(max(p90 / 220.0, 0.0), 1.0) * 0.18
        score += contribution
        evidence.append(_evidence("moisture_flux850", fields["uv850"], "moisture transport", f"p90={p90:.2f}", 0.18, contribution))
    else:
        missing.append("moisture_flux850")
    if div850 is not None:
        min_div = float(np.nanpercentile(div850, 10))
        contribution = min(max(abs(min_div) / 25.0, 0.0), 1.0) * 0.16 if min_div < 0 else 0.0
        score += contribution
        evidence.append(_evidence("div850", fields["div850"], "low-level convergence", f"p10={min_div:.2f}", 0.16, contribution))
    else:
        missing.append("div850")
    if w700 is not None:
        min_w = float(np.nanpercentile(w700, 10))
        contribution = min(max(abs(min_w) / 8.0, 0.0), 1.0) * 0.16 if min_w < 0 else 0.0
        score += contribution
        evidence.append(_evidence("w700", fields["w700"], "700hPa upward motion", f"p10={min_w:.2f}", 0.16, contribution))
    else:
        missing.append("w700")
    if kindex is not None:
        p75 = float(np.nanpercentile(kindex, 75))
        contribution = min(max((p75 - 25.0) / 15.0, 0.0), 1.0) * 0.10
        score += contribution
        evidence.append(_evidence("kindex", fields["kindex"], "convective instability", f"p75={p75:.2f}", 0.10, contribution))
    else:
        missing.append("kindex")
    if cape is not None:
        p75 = float(np.nanpercentile(cape, 75))
        contribution = min(max(p75 / 1500.0, 0.0), 1.0) * 0.08
        score += contribution
        evidence.append(_evidence("cape", fields["cape"], "CAPE support", f"p75={p75:.2f} J/kg", 0.08, contribution))
    else:
        missing.append("cape")
    if rain6 is not None:
        p90 = float(np.nanpercentile(rain6, 90))
        contribution = min(max(p90 / 25.0, 0.0), 1.0) * 0.12
        score += contribution
        evidence.append(_evidence("rain6", fields["rain6"], "model 6h precipitation", f"p90={p90:.2f} mm", 0.12, contribution))
    else:
        missing.append("rain6")

    region = _risk_region_from_arrays(fields, [q850, moisture_flux, np.negative(div850) if div850 is not None else None, rain6])
    return {
        "id": "evidence-heavy-rain-potential",
        "target_type": "heavy_rain_potential",
        "level": score_level(score),
        "region": region,
        "score": round(float(score), 3),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _convection_chain(
    fields: dict[str, NafpField],
    cape: np.ndarray | None,
    cin: np.ndarray | None,
    kindex: np.ndarray | None,
    shear: np.ndarray | None,
    q850: np.ndarray | None,
    div850: np.ndarray | None,
    div200: np.ndarray | None,
    div300: np.ndarray | None,
    pv300: np.ndarray | None,
    pvadv300: np.ndarray | None,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0
    if cape is not None:
        p75 = float(np.nanpercentile(cape, 75))
        contribution = min(max(p75 / 1800.0, 0.0), 1.0) * 0.22
        score += contribution
        evidence.append(_evidence("cape", fields["cape"], "instability energy", f"p75={p75:.2f} J/kg", 0.22, contribution))
    else:
        missing.append("cape")
    if cin is not None:
        p50 = float(np.nanpercentile(cin, 50))
        contribution = min(max((200.0 - abs(p50)) / 200.0, 0.0), 1.0) * 0.08
        score += contribution
        evidence.append(_evidence("cin", fields["cin"], "inhibition is not excessive", f"p50={p50:.2f} J/kg", 0.08, contribution))
    else:
        missing.append("cin")
    if kindex is not None:
        p75 = float(np.nanpercentile(kindex, 75))
        contribution = min(max((p75 - 25.0) / 15.0, 0.0), 1.0) * 0.12
        score += contribution
        evidence.append(_evidence("kindex", fields["kindex"], "thermodynamic instability", f"p75={p75:.2f}", 0.12, contribution))
    else:
        missing.append("kindex")
    if shear is not None:
        p75 = float(np.nanpercentile(shear, 75))
        contribution = min(max(p75 / 25.0, 0.0), 1.0) * 0.16
        score += contribution
        evidence.append(_evidence("shr850-200", fields["shr850-200"], "deep-layer shear", f"p75={p75:.2f}", 0.16, contribution))
    else:
        missing.append("shr850-200")
    if q850 is not None:
        p75 = float(np.nanpercentile(q850, 75))
        contribution = min(max((p75 - 8.0) / 8.0, 0.0), 1.0) * 0.12
        score += contribution
        evidence.append(_evidence("q850", fields["q850"], "low-level moisture", f"p75={p75:.2f} g/kg", 0.12, contribution))
    else:
        missing.append("q850")
    if div850 is not None:
        p10 = float(np.nanpercentile(div850, 10))
        contribution = min(max(abs(p10) / 25.0, 0.0), 1.0) * 0.10 if p10 < 0 else 0.0
        score += contribution
        evidence.append(_evidence("div850", fields["div850"], "low-level trigger", f"p10={p10:.2f}", 0.10, contribution))
    else:
        missing.append("div850")
    upper = div200 if div200 is not None else div300
    upper_key = "div200" if div200 is not None else "div300"
    if upper is not None:
        p90 = float(np.nanpercentile(upper, 90))
        contribution = min(max(p90 / 20.0, 0.0), 1.0) * 0.10
        score += contribution
        evidence.append(_evidence(upper_key, fields[upper_key], "upper-level divergence", f"p90={p90:.2f}", 0.10, contribution))
    else:
        missing.append("div200/div300")
    if pv300 is not None:
        p90 = float(np.nanpercentile(pv300, 90))
        contribution = min(max(p90 / 5.0, 0.0), 1.0) * 0.05
        score += contribution
        evidence.append(_evidence("pv300", fields["pv300"], "upper-level PV support", f"p90={p90:.2f}", 0.05, contribution))
    else:
        missing.append("pv300")
    if pvadv300 is not None:
        p90 = float(np.nanpercentile(np.abs(pvadv300), 90))
        contribution = min(max(p90 / 20.0, 0.0), 1.0) * 0.05
        score += contribution
        evidence.append(_evidence("pvadv300", fields["pvadv300"], "PV advection support", f"abs_p90={p90:.2f}", 0.05, contribution))
    else:
        missing.append("pvadv300")

    region = _risk_region_from_arrays(fields, [cape, shear, q850, np.negative(div850) if div850 is not None else None])
    return {
        "id": "evidence-convection-potential",
        "target_type": "convection_potential",
        "level": score_level(score),
        "region": region,
        "score": round(float(score), 3),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def build_summary(systems: list[dict[str, Any]], evidence_chains: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    parts = []
    if systems:
        counts: dict[str, int] = {}
        for system in systems:
            counts[system["type"]] = counts.get(system["type"], 0) + 1
        parts.append("天气形势识别到" + "、".join(f"{key} {value} 个" for key, value in counts.items()) + "。")
    else:
        parts.append("天气形势暂未识别到稳定的大尺度系统。")
    for chain in evidence_chains:
        parts.append(f"{chain['target_type']} 为 {chain['level']}，评分 {chain['score']:.2f}。")
    if missing:
        parts.append(f"缺少 {len(missing)} 个可选证据场，已在 missing_fields 中列出。")
    return "".join(parts)


def diagnose_nafp_situation(
    root: str | Path = NAFP_SAMPLE_ROOT,
    run_time: str | datetime = "2026-06-17T20:00:00",
    forecast_hour: int = 24,
) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    fields, missing = load_field_bundle(root, rt, forecast_hour)
    gh = field_array(fields["gh500"], "gh")
    if gh is None:
        raise FileNotFoundError("gh500")
    lat = fields["gh500"].lat
    lon = fields["gh500"].lon
    diagnostics = {"gh500": {**finite_stats(gh), "source_path": fields["gh500"].source_path}}
    systems = diagnose_systems(fields, diagnostics)
    evidence_chains = diagnose_evidence_chains(fields, diagnostics)
    valid_time = rt + timedelta(hours=int(forecast_hour))
    return {
        "run_time": rt.isoformat(),
        "forecast_hour": int(forecast_hour),
        "valid_time": valid_time.isoformat(),
        "domain": {
            "lat_min": float(lat.min()),
            "lat_max": float(lat.max()),
            "lon_min": float(lon.min()),
            "lon_max": float(lon.max()),
        },
        "systems": systems,
        "diagnostics": diagnostics,
        "evidence_chains": evidence_chains,
        "missing_fields": missing,
        "summary": build_summary(systems, evidence_chains, missing),
    }
