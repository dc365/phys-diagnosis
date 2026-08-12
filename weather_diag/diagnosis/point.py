from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np

from weather_diag.data.nafp import NAFP_SAMPLE_ROOT, NafpField, parse_run_time
from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, threshold_entries_by_id
from weather_diag.diagnosis.conclusions import conclusions_from_chains
from weather_diag.diagnosis.nafp_layers import load_nafp_layer
from weather_diag.diagnosis.nafp_situation import (
    NAFP_RISK_CHAIN_HAZARDS,
    _add_scalar_diagnostic,
    _append_missing_if_enabled,
    _dominant_evidence,
    _moisture_flux_from_fields,
    _normalized_score,
    _phase_label,
    _relative_vorticity_from_wind,
    _rule_enabled,
    _rule_float,
    _to_celsius,
    field_array,
    finite_stats,
    load_field_bundle,
    score_level,
)
from weather_diag.diagnosis.risk_taxonomy import hazard_metadata, risk_grid_for_hazard


ValueFormatter = Callable[[float, float], str]


def _round_coord(value: float) -> float:
    return round(float(value), 6)


def _normalize_query_lon(lon_values: np.ndarray, lon: float) -> float:
    lon_min = float(np.nanmin(lon_values))
    lon_max = float(np.nanmax(lon_values))
    query = float(lon)
    if lon_min >= 0.0 and lon_max > 180.0 and query < 0.0:
        return query % 360.0
    if lon_min < 0.0 and lon_max <= 180.0 and query > 180.0:
        return ((query + 180.0) % 360.0) - 180.0
    return query


def nearest_grid_point(
    lat_values: np.ndarray,
    lon_values: np.ndarray,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    lats = np.asarray(lat_values, dtype=float)
    lons = np.asarray(lon_values, dtype=float)
    if lats.size == 0 or lons.size == 0:
        raise ValueError("empty latitude or longitude coordinate")
    query_lon = _normalize_query_lon(lons, lon)
    lat_idx = int(np.nanargmin(np.abs(lats - float(lat))))
    lon_idx = int(np.nanargmin(np.abs(lons - query_lon)))
    nearest_lat = float(lats[lat_idx])
    nearest_lon = float(lons[lon_idx])
    distance = float(np.hypot(nearest_lat - float(lat), nearest_lon - query_lon))
    outside_domain = (
        float(lat) < float(np.nanmin(lats))
        or float(lat) > float(np.nanmax(lats))
        or query_lon < float(np.nanmin(lons))
        or query_lon > float(np.nanmax(lons))
    )
    return {
        "lat": _round_coord(nearest_lat),
        "lon": _round_coord(nearest_lon),
        "lat_index": lat_idx,
        "lon_index": lon_idx,
        "distance_degrees": round(distance, 6),
        "outside_domain": outside_domain,
        "normalized_query_lon": _round_coord(query_lon),
    }


def _domain_from_field(field: NafpField) -> dict[str, float]:
    return {
        "lat_min": float(np.nanmin(field.lat)),
        "lat_max": float(np.nanmax(field.lat)),
        "lon_min": float(np.nanmin(field.lon)),
        "lon_max": float(np.nanmax(field.lon)),
    }


def _prepare_2d(values: np.ndarray, lat_values: np.ndarray, lon_values: np.ndarray) -> np.ndarray | None:
    arr = np.asarray(values, dtype=float).squeeze()
    if arr.ndim != 2:
        return None
    if arr.shape == (len(lat_values), len(lon_values)):
        return arr
    if arr.shape == (len(lon_values), len(lat_values)):
        return arr.T
    return None


def _sample_value(
    values: np.ndarray,
    lat_values: np.ndarray,
    lon_values: np.ndarray,
    lat: float,
    lon: float,
) -> tuple[float | None, dict[str, Any]]:
    point = nearest_grid_point(lat_values, lon_values, lat, lon)
    arr = _prepare_2d(values, lat_values, lon_values)
    if arr is None:
        return None, point
    raw = float(arr[point["lat_index"], point["lon_index"]])
    if not np.isfinite(raw):
        return None, point
    return raw, point


def _fmt(unit: str = "", *, prefix: str = "point") -> ValueFormatter:
    def formatter(scoring_value: float, _observed_value: float) -> str:
        suffix = f" {unit}" if unit else ""
        return f"{prefix}={scoring_value:.2f}{suffix}"

    return formatter


def _fmt_abs(unit: str = "") -> ValueFormatter:
    def formatter(scoring_value: float, observed_value: float) -> str:
        suffix = f" {unit}" if unit else ""
        return f"abs(point)={scoring_value:.2f}{suffix}, signed={observed_value:.2f}{suffix}"

    return formatter


def _point_evidence(
    field_name: str,
    signal: str,
    value: str,
    rule: dict[str, Any],
    raw_value: float,
    observed_value: float,
    sample_point: dict[str, Any],
    source_path: str,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    normalized = round(float(_normalized_score(raw_value, rule)), 6)
    weight = _rule_float(rule, "weight", 0.0)
    contribution = round(normalized * weight, 6)
    item = {
        "entry_id": rule["entry_id"],
        "field": field_name,
        "signal": signal,
        "value": value,
        "statistic": "point",
        "rule_statistic": rule.get("statistic"),
        "sample_method": "nearest_grid_point",
        "sample_point": sample_point,
        "operator": rule.get("operator"),
        "threshold": rule.get("threshold"),
        "scale": rule.get("scale"),
        "raw_value": round(float(raw_value), 6),
        "observed_value": round(float(observed_value), 6),
        "normalized_score": normalized,
        "weight": weight,
        "contribution": contribution,
        "source_path": source_path,
        "unit": rule.get("unit"),
    }
    if source_paths:
        item["source_paths"] = source_paths
    return item


def _append_point_rule(
    evidence: list[dict[str, Any]],
    missing: list[str],
    *,
    rule: dict[str, Any],
    field_name: str,
    source_field: NafpField,
    values: np.ndarray | None,
    lat: float,
    lon: float,
    signal: str,
    value_formatter: ValueFormatter,
    score_transform: Callable[[float], float] | None = None,
    source_path: str | None = None,
    source_paths: list[str] | None = None,
) -> tuple[float, float | None]:
    if not _rule_enabled(rule):
        return 0.0, None
    if values is None or not source_field.exists:
        _append_missing_if_enabled(missing, rule, field_name)
        return 0.0, None
    observed_value, sample_point = _sample_value(values, source_field.lat, source_field.lon, lat, lon)
    if observed_value is None:
        _append_missing_if_enabled(missing, rule, field_name)
        return 0.0, None
    scoring_value = score_transform(observed_value) if score_transform else observed_value
    if not np.isfinite(scoring_value):
        _append_missing_if_enabled(missing, rule, field_name)
        return 0.0, None
    item = _point_evidence(
        field_name=field_name,
        signal=signal,
        value=value_formatter(scoring_value, observed_value),
        rule=rule,
        raw_value=float(scoring_value),
        observed_value=float(observed_value),
        sample_point=sample_point,
        source_path=source_path or source_field.source_path,
        source_paths=source_paths,
    )
    evidence.append(item)
    return float(item["contribution"]), float(scoring_value)


def _score_sum(evidence: list[dict[str, Any]]) -> float:
    return round(float(sum(float(item.get("contribution") or 0.0) for item in evidence)), 3)


def _heavy_rain_point_chain(
    fields: dict[str, NafpField],
    q850: np.ndarray | None,
    moisture_flux: np.ndarray | None,
    div850: np.ndarray | None,
    w700: np.ndarray | None,
    kindex: np.ndarray | None,
    cape: np.ndarray | None,
    rain6: np.ndarray | None,
    tcwv: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
    lat: float,
    lon: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.q850"],
        field_name="q850",
        source_field=fields["q850"],
        values=q850,
        lat=lat,
        lon=lon,
        signal="low-level moisture",
        value_formatter=_fmt("g/kg"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.tcwv"],
        field_name="tcwv",
        source_field=fields["tcwv"],
        values=tcwv,
        lat=lat,
        lon=lon,
        signal="column water vapor",
        value_formatter=_fmt("mm"),
    )
    moisture_source_paths = [
        fields["uv850"].source_path,
        fields["q850"].source_path,
    ]
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.moisture_flux850"],
        field_name="moisture_flux850",
        source_field=fields["q850"],
        values=moisture_flux,
        lat=lat,
        lon=lon,
        signal="moisture transport",
        value_formatter=_fmt(),
        source_path=fields["uv850"].source_path,
        source_paths=moisture_source_paths,
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.div850"],
        field_name="div850",
        source_field=fields["div850"],
        values=div850,
        lat=lat,
        lon=lon,
        signal="low-level convergence",
        value_formatter=_fmt(),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.w700"],
        field_name="w700",
        source_field=fields["w700"],
        values=w700,
        lat=lat,
        lon=lon,
        signal="700hPa upward motion",
        value_formatter=_fmt(),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.kindex"],
        field_name="kindex",
        source_field=fields["kindex"],
        values=kindex,
        lat=lat,
        lon=lon,
        signal="convective instability",
        value_formatter=_fmt("degC"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.cape"],
        field_name="cape",
        source_field=fields["cape"],
        values=cape,
        lat=lat,
        lon=lon,
        signal="CAPE support",
        value_formatter=_fmt("J/kg"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["heavy_rain.rain6"],
        field_name="rain6",
        source_field=fields["rain6"],
        values=rain6,
        lat=lat,
        lon=lon,
        signal="model 6h precipitation",
        value_formatter=_fmt("mm"),
    )

    score = _score_sum(evidence)
    return {
        "id": "point-evidence-heavy-rain-potential",
        "target_type": "heavy_rain_potential",
        "level": score_level(score, matrix),
        "score": score,
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _convection_point_chain(
    fields: dict[str, NafpField],
    cape: np.ndarray | None,
    cin: np.ndarray | None,
    kindex: np.ndarray | None,
    shear: np.ndarray | None,
    shear01: np.ndarray | None,
    q850: np.ndarray | None,
    div850: np.ndarray | None,
    div200: np.ndarray | None,
    div300: np.ndarray | None,
    pv300: np.ndarray | None,
    pvadv300: np.ndarray | None,
    li: np.ndarray | None,
    dcape: np.ndarray | None,
    srh: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
    lat: float,
    lon: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.cape"],
        field_name="cape",
        source_field=fields["cape"],
        values=cape,
        lat=lat,
        lon=lon,
        signal="instability energy",
        value_formatter=_fmt("J/kg"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.cin"],
        field_name="cin",
        source_field=fields["cin"],
        values=cin,
        lat=lat,
        lon=lon,
        signal="inhibition is not excessive",
        value_formatter=_fmt("J/kg"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.kindex"],
        field_name="kindex",
        source_field=fields["kindex"],
        values=kindex,
        lat=lat,
        lon=lon,
        signal="thermodynamic instability",
        value_formatter=_fmt("degC"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.shr850_200"],
        field_name="shr850-200",
        source_field=fields["shr850-200"],
        values=shear,
        lat=lat,
        lon=lon,
        signal="deep-layer shear",
        value_formatter=_fmt("m/s"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.q850"],
        field_name="q850",
        source_field=fields["q850"],
        values=q850,
        lat=lat,
        lon=lon,
        signal="low-level moisture",
        value_formatter=_fmt("g/kg"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.div850"],
        field_name="div850",
        source_field=fields["div850"],
        values=div850,
        lat=lat,
        lon=lon,
        signal="low-level trigger",
        value_formatter=_fmt(),
    )
    upper = div200 if div200 is not None else div300
    upper_key = "div200" if div200 is not None else "div300"
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.upper_divergence"],
        field_name=upper_key if upper is not None else "div200/div300",
        source_field=fields[upper_key],
        values=upper,
        lat=lat,
        lon=lon,
        signal="upper-level divergence",
        value_formatter=_fmt(),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.pv300"],
        field_name="pv300",
        source_field=fields["pv300"],
        values=pv300,
        lat=lat,
        lon=lon,
        signal="upper-level PV support",
        value_formatter=_fmt("PVU"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.pvadv300"],
        field_name="pvadv300",
        source_field=fields["pvadv300"],
        values=pvadv300,
        lat=lat,
        lon=lon,
        signal="PV advection support",
        value_formatter=_fmt_abs(),
        score_transform=abs,
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.li"],
        field_name="li",
        source_field=fields["li"],
        values=li,
        lat=lat,
        lon=lon,
        signal="lifted index instability",
        value_formatter=_fmt("degC"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["convection.dcape"],
        field_name="dcape",
        source_field=fields["dcape"],
        values=dcape,
        lat=lat,
        lon=lon,
        signal="downdraft CAPE",
        value_formatter=_fmt("J/kg"),
    )
    if srh is not None:
        _append_point_rule(
            evidence,
            missing,
            rule=rules["convection.srh"],
            field_name="srh",
            source_field=fields["srh"],
            values=srh,
            lat=lat,
            lon=lon,
            signal="storm-relative helicity",
            value_formatter=_fmt("m2/s2"),
        )
    else:
        _append_point_rule(
            evidence,
            missing,
            rule=rules["convection.srh"],
            field_name="shr0-1km",
            source_field=fields["shr0-1km"],
            values=shear01,
            lat=lat,
            lon=lon,
            signal="0-1km shear proxy for low-level rotation",
            value_formatter=_fmt("m/s"),
        )

    score = _score_sum(evidence)
    return {
        "id": "point-evidence-convection-potential",
        "target_type": "convection_potential",
        "level": score_level(score, matrix),
        "score": score,
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _dynamic_lift_point_chain(
    fields: dict[str, NafpField],
    w700: np.ndarray | None,
    vorticity500: np.ndarray | None,
    div850: np.ndarray | None,
    div200: np.ndarray | None,
    div300: np.ndarray | None,
    pvadv300: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
    lat: float,
    lon: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    _append_point_rule(
        evidence,
        missing,
        rule=rules["dynamic_lift.w700"],
        field_name="w700",
        source_field=fields["w700"],
        values=w700,
        lat=lat,
        lon=lon,
        signal="700hPa upward motion",
        value_formatter=_fmt(),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["dynamic_lift.vorticity500"],
        field_name="vorticity500",
        source_field=fields["uv500"],
        values=vorticity500,
        lat=lat,
        lon=lon,
        signal="500hPa positive vorticity",
        value_formatter=_fmt("10^-5/s"),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["dynamic_lift.div850"],
        field_name="div850",
        source_field=fields["div850"],
        values=div850,
        lat=lat,
        lon=lon,
        signal="low-level convergence",
        value_formatter=_fmt(),
    )
    upper = div200 if div200 is not None else div300
    upper_key = "div200" if div200 is not None else "div300"
    _append_point_rule(
        evidence,
        missing,
        rule=rules["dynamic_lift.upper_divergence"],
        field_name=upper_key if upper is not None else "div200/div300",
        source_field=fields[upper_key],
        values=upper,
        lat=lat,
        lon=lon,
        signal="upper-level divergence",
        value_formatter=_fmt(),
    )
    _append_point_rule(
        evidence,
        missing,
        rule=rules["dynamic_lift.pvadv300"],
        field_name="pvadv300",
        source_field=fields["pvadv300"],
        values=pvadv300,
        lat=lat,
        lon=lon,
        signal="PV advection support",
        value_formatter=_fmt_abs(),
        score_transform=abs,
    )

    score = _score_sum(evidence)
    return {
        "id": "point-evidence-dynamic-lift-potential",
        "target_type": "dynamic_lift_potential",
        "level": score_level(score, matrix),
        "score": score,
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _phase_point_chain(
    fields: dict[str, NafpField],
    t2m: np.ndarray | None,
    tt850: np.ndarray | None,
    tt925: np.ndarray | None,
    tw0_height: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
    lat: float,
    lon: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    _, t2m_value = _append_point_rule(
        evidence,
        missing,
        rule=rules["phase.t2m"],
        field_name="t2m",
        source_field=fields["t2m"],
        values=_to_celsius(t2m) if t2m is not None else None,
        lat=lat,
        lon=lon,
        signal="2m temperature",
        value_formatter=_fmt("degC"),
    )
    _, tt850_value = _append_point_rule(
        evidence,
        missing,
        rule=rules["phase.tt850"],
        field_name="tt850",
        source_field=fields["tt850"],
        values=_to_celsius(tt850) if tt850 is not None else None,
        lat=lat,
        lon=lon,
        signal="850hPa temperature",
        value_formatter=_fmt("degC"),
    )
    _, tt925_value = _append_point_rule(
        evidence,
        missing,
        rule=rules["phase.tt925"],
        field_name="tt925",
        source_field=fields["tt925"],
        values=_to_celsius(tt925) if tt925 is not None else None,
        lat=lat,
        lon=lon,
        signal="925hPa temperature",
        value_formatter=_fmt("degC"),
    )
    _, tw0_value = _append_point_rule(
        evidence,
        missing,
        rule=rules["phase.tw0_height"],
        field_name="tw0_height",
        source_field=fields["tw0_height"],
        values=tw0_height,
        lat=lat,
        lon=lon,
        signal="wet-bulb zero height",
        value_formatter=_fmt("m"),
    )

    score = _score_sum(evidence)
    phase_type, diagnosis = _phase_label(t2m_value, tt850_value, tt925_value, tw0_value)
    return {
        "id": "point-evidence-precipitation-phase",
        "target_type": "precipitation_phase",
        "level": score_level(score, matrix),
        "phase_type": phase_type,
        "diagnosis": diagnosis,
        "score": score,
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def diagnose_point_evidence_chains(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    matrix: dict[str, Any],
    rules: dict[str, dict],
    lat: float,
    lon: float,
) -> list[dict[str, Any]]:
    q850 = _add_scalar_diagnostic(diagnostics, fields, "q850", "q")
    div850 = _add_scalar_diagnostic(diagnostics, fields, "div850", "div")
    w700 = _add_scalar_diagnostic(diagnostics, fields, "w700", "w")
    kindex = _add_scalar_diagnostic(diagnostics, fields, "kindex", "kindex")
    cape = _add_scalar_diagnostic(diagnostics, fields, "cape", "cape")
    cin = _add_scalar_diagnostic(diagnostics, fields, "cin", "cin")
    li = _add_scalar_diagnostic(diagnostics, fields, "li", "li")
    dcape = _add_scalar_diagnostic(diagnostics, fields, "dcape", "dcape")
    srh = _add_scalar_diagnostic(diagnostics, fields, "srh", "srh")
    rain6 = _add_scalar_diagnostic(diagnostics, fields, "rain6", "rain6")
    shear = _add_scalar_diagnostic(diagnostics, fields, "shr850-200", "shr850-200")
    shear01 = _add_scalar_diagnostic(diagnostics, fields, "shr0-1km", "shr0-1km")
    tcwv = _add_scalar_diagnostic(diagnostics, fields, "tcwv", "tcwv")
    div200 = _add_scalar_diagnostic(diagnostics, fields, "div200", "div")
    div300 = _add_scalar_diagnostic(diagnostics, fields, "div300", "div")
    pv300 = _add_scalar_diagnostic(diagnostics, fields, "pv300", "pv")
    pvadv300 = _add_scalar_diagnostic(diagnostics, fields, "pvadv300", "pvadv")
    tt850 = _add_scalar_diagnostic(diagnostics, fields, "tt850", "tt")
    tt925 = _add_scalar_diagnostic(diagnostics, fields, "tt925", "tt")
    t2m = _add_scalar_diagnostic(diagnostics, fields, "t2m", "t2m")
    tw0_height = _add_scalar_diagnostic(diagnostics, fields, "tw0_height", "tw0")
    moisture_flux, _moisture_flux_divergence = _moisture_flux_from_fields(fields, diagnostics)
    vorticity500 = _relative_vorticity_from_wind(fields, diagnostics, "uv500", "vorticity500")

    return [
        _heavy_rain_point_chain(
            fields,
            q850,
            moisture_flux,
            div850,
            w700,
            kindex,
            cape,
            rain6,
            tcwv,
            matrix,
            rules,
            lat,
            lon,
        ),
        _convection_point_chain(
            fields,
            cape,
            cin,
            kindex,
            shear,
            shear01,
            q850,
            div850,
            div200,
            div300,
            pv300,
            pvadv300,
            li,
            dcape,
            srh,
            matrix,
            rules,
            lat,
            lon,
        ),
        _dynamic_lift_point_chain(fields, w700, vorticity500, div850, div200, div300, pvadv300, matrix, rules, lat, lon),
        _phase_point_chain(fields, t2m, tt850, tt925, tw0_height, matrix, rules, lat, lon),
    ]


def _score_summaries(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for chain in chains:
        item = {
            "target_type": chain["target_type"],
            "level": chain["level"],
            "score": chain["score"],
            "dominant_evidence": chain.get("dominant_evidence") or [],
            "missing_evidence": chain.get("missing_evidence") or [],
        }
        if "phase_type" in chain:
            item["phase_type"] = chain["phase_type"]
            item["diagnosis"] = chain.get("diagnosis")
        summaries.append(item)
    return summaries


def _point_score_grid_sample(
    source_grid: str,
    *,
    root: str | Path | None,
    run_time: str | datetime | None,
    forecast_hour: int | None,
    lat: float | None,
    lon: float | None,
) -> dict[str, Any] | None:
    if root is None or run_time is None or forecast_hour is None or lat is None or lon is None:
        return None
    try:
        layer = load_nafp_layer(
            source_grid,
            root=root,
            run_time=parse_run_time(run_time).isoformat(),
            forecast_hour=int(forecast_hour),
        )
    except Exception as exc:
        return {
            "score_source": "evidence_chain_fallback",
            "score_error": str(exc),
        }
    score, sample_point = _sample_value(layer["values"], layer["lat"], layer["lon"], lat, lon)
    if score is None:
        return None
    return {
        "score": round(float(score), 3),
        "score_source": "source_grid",
        "sample_method": "nearest_grid_point",
        "sample_point": sample_point,
    }


def point_risk_diagnoses_from_chains(
    evidence_chains: list[dict[str, Any]],
    *,
    root: str | Path | None = None,
    run_time: str | datetime | None = None,
    forecast_hour: int | None = None,
    lat: float | None = None,
    lon: float | None = None,
    threshold_matrix: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    chains = {chain.get("target_type"): chain for chain in evidence_chains}
    diagnoses = []
    for source_target, hazard_types in NAFP_RISK_CHAIN_HAZARDS.items():
        chain = chains.get(source_target)
        if not chain:
            continue
        for hazard_type in hazard_types:
            metadata = hazard_metadata(hazard_type)
            source_grid = risk_grid_for_hazard(hazard_type)
            score_info = _point_score_grid_sample(
                source_grid,
                root=root,
                run_time=run_time,
                forecast_hour=forecast_hour,
                lat=lat,
                lon=lon,
            )
            score = chain.get("score")
            level = chain.get("level")
            if score_info and "score" in score_info:
                score = score_info["score"]
                level = score_level(float(score), threshold_matrix or load_threshold_matrix())
            diagnoses.append(
                {
                    "risk_id": f"point-risk-{hazard_type}",
                    "hazard_type": hazard_type,
                    "risk_domain": metadata["risk_domain"],
                    "label": metadata["label"],
                    "mechanism_tags": metadata["mechanism_tags"],
                    "source_grid": source_grid,
                    "risk_level": level,
                    "level": level,
                    "score": score,
                    "source_chain_ids": [source_target],
                    "dominant_evidence": chain.get("dominant_evidence") or [],
                    **(score_info or {}),
                }
            )
    return diagnoses


def _build_point_summary(point: dict[str, Any], chains: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    nearest = point["nearest_grid_point"]
    parts = [
        f"点位({point['requested']['lat']:.2f}, {point['requested']['lon']:.2f})按最近格点"
        f"({nearest['lat']:.2f}, {nearest['lon']:.2f})诊断。"
    ]
    for chain in chains:
        parts.append(f"{chain['target_type']}为{chain['level']}，评分{chain['score']:.2f}。")
    if missing:
        parts.append(f"缺少{len(missing)}个可选证据场，已在missing_fields中列出。")
    return "".join(parts)


def diagnose_nafp_point(
    root: str | Path = NAFP_SAMPLE_ROOT,
    run_time: str | datetime = "2026-06-17T20:00:00",
    forecast_hour: int = 24,
    *,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    fields, missing = load_field_bundle(root, rt, forecast_hour)
    gh = field_array(fields["gh500"], "gh")
    if gh is None:
        raise FileNotFoundError("gh500")

    threshold_matrix = load_threshold_matrix()
    rules = threshold_entries_by_id(threshold_matrix)
    diagnostics = {"gh500": {**finite_stats(gh), "source_path": fields["gh500"].source_path}}
    point = {
        "requested": {"lat": _round_coord(lat), "lon": _round_coord(lon)},
        "sample_method": "nearest_grid_point",
        "nearest_grid_point": nearest_grid_point(fields["gh500"].lat, fields["gh500"].lon, lat, lon),
    }
    evidence_chains = diagnose_point_evidence_chains(fields, diagnostics, threshold_matrix, rules, lat, lon)
    diagnosis_conclusions = conclusions_from_chains(evidence_chains)
    risk_diagnoses = point_risk_diagnoses_from_chains(
        evidence_chains,
        root=root,
        run_time=rt,
        forecast_hour=forecast_hour,
        lat=lat,
        lon=lon,
        threshold_matrix=threshold_matrix,
    )
    valid_time = rt + timedelta(hours=int(forecast_hour))
    return {
        "run_time": rt.isoformat(),
        "forecast_hour": int(forecast_hour),
        "valid_time": valid_time.isoformat(),
        "threshold_matrix": {
            "matrix_id": threshold_matrix["matrix_id"],
            "algorithm_id": threshold_matrix["algorithm_id"],
            "status": threshold_matrix["status"],
            "updated_at": threshold_matrix.get("updated_at"),
            "updated_by": threshold_matrix.get("updated_by"),
        },
        "domain": _domain_from_field(fields["gh500"]),
        "point": point,
        "scores": _score_summaries(evidence_chains),
        "diagnostics": diagnostics,
        "evidence_chains": evidence_chains,
        "diagnosis_conclusions": diagnosis_conclusions,
        "risk_diagnoses": risk_diagnoses,
        "missing_fields": missing,
        "summary": _build_point_summary(point, evidence_chains, missing),
    }
