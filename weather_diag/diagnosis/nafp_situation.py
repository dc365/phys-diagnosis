from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from weather_diag.config import load_thresholds
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT, NafpField, load_nafp_field, parse_run_time
from weather_diag.diagnosis.algorithm_rules import (
    load_threshold_matrix,
    score_level as matrix_score_level,
    threshold_entries_by_id,
)
from weather_diag.diagnosis.conclusions import conclusions_from_chains
from weather_diag.diagnosis.nafp_layers import load_nafp_layer, nafp_multi_hazard_score_details
from weather_diag.diagnosis.risk_taxonomy import HAZARD_TYPES, hazard_metadata, risk_grid_for_hazard
from weather_diag.diagnosis.system_links import attach_chain_supporting_systems, supporting_system_links
from weather_diag.diagnostics.grid import (
    component_axis_line,
    derivatives_lonlat,
    geometry_bounds,
    mask_to_bbox_features,
    smooth_polygon_geometry,
)
from weather_diag.features.convergence import ranked_mask_items, smooth_field
from weather_diag.features.front import front_axis_components, front_candidate_fields
from weather_diag.features.pressure import detect_high_low
from weather_diag.features.transport_objects import ranked_transport_components
from weather_diag.features.trough_ridge import trough_ridge_axis_candidates


DEFAULT_OPTIONAL_FIELDS = [
    ("seap", "999", "mslp"),
    ("uv", "500", "uv500"),
    ("uv", "850", "uv850"),
    ("q", "850", "q850"),
    ("rh", "850", "rh850"),
    ("rh", "700", "rh700"),
    ("rh", "500", "rh500"),
    ("div", "850", "div850"),
    ("tt", "850", "tt850"),
    ("tt", "700", "tt700"),
    ("tt", "500", "tt500"),
    ("ttadv", "850", "ttadv850"),
    ("gh", "700", "gh700"),
    ("div", "200", "div200"),
    ("div", "300", "div300"),
    ("pv", "300", "pv300"),
    ("pvadv", "300", "pvadv300"),
    ("w", "700", "w700"),
    ("kindex", "999", "kindex"),
    ("cape", "999", "cape"),
    ("cin", "999", "cin"),
    ("tcwv", "999", "tcwv"),
    ("td2", "999", "td2m"),
    ("rain6", "999", "rain6"),
    ("rain3", "999", "rain3"),
    ("rainmax3", "999", "rainmax3"),
    ("rain24", "999", "rain24"),
    ("shr850-200", "999", "shr850-200"),
    ("shr6km", "999", "shr6km"),
    ("uv", "925", "uv925"),
    ("tt", "925", "tt925"),
    ("li", "999", "li"),
    ("si", "999", "si"),
    ("bli", "999", "bli"),
    ("dcape", "999", "dcape"),
    ("srh", "999", "srh"),
    ("shr1km", "999", "shr0-1km"),
    ("lcl", "999", "lcl"),
    ("deg0l", "999", "deg0l"),
    ("t2m", "999", "t2m"),
    ("10u", "999", "u10"),
    ("10v", "999", "v10"),
    ("tw0", "999", "tw0_height"),
]


PRIMARY_SYSTEM_LIMITS = {
    "subtropical_high": 1,
    "high": 4,
    "low": 4,
    "low_pressure_convergence": 2,
    "high_pressure_divergence": 2,
    "trough_candidate": 3,
    "ridge_candidate": 3,
    "low_level_jet": 3,
    "moisture_transport": 3,
    "moisture_convergence": 3,
    "low_level_convergence": 3,
    "upper_divergence": 3,
    "front_candidate": 3,
}


SYSTEM_DISPLAY_PRIORITY = {
    "subtropical_high": 10,
    "low": 20,
    "high": 21,
    "low_pressure_convergence": 30,
    "high_pressure_divergence": 31,
    "trough_candidate": 40,
    "ridge_candidate": 41,
    "front_candidate": 50,
    "low_level_jet": 60,
    "moisture_transport": 61,
    "moisture_convergence": 62,
    "low_level_convergence": 63,
    "upper_divergence": 64,
}


DYNAMIC_CONFIDENCE_SYSTEM_TYPES = {
    "low_pressure_convergence",
    "high_pressure_divergence",
    "trough_candidate",
    "ridge_candidate",
    "front_candidate",
    "moisture_transport",
    "moisture_convergence",
    "low_level_convergence",
    "upper_divergence",
}


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


def score_level(score: float, matrix: dict[str, Any]) -> str:
    return matrix_score_level(score, matrix)


def _rule_enabled(rule: dict[str, Any]) -> bool:
    return bool(rule.get("enabled", True))


def _rule_float(rule: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = rule.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _clip01(value: float) -> float:
    return float(min(max(value, 0.0), 1.0))


def _normalized_score(raw_value: float, rule: dict[str, Any]) -> float:
    threshold = _rule_float(rule, "threshold", 0.0)
    scale = _rule_float(rule, "scale", 1.0)
    operator = str(rule.get("operator") or "ratio")
    if scale <= 0:
        scale = 1.0
    if operator in {"ratio", "ramp"}:
        return _clip01((raw_value - threshold) / scale)
    if operator == "negative_ratio":
        return _clip01((threshold - raw_value) / scale)
    if operator == "inverse_abs_ratio":
        return _clip01((threshold - abs(raw_value)) / scale)
    if operator == ">=":
        return 1.0 if raw_value >= threshold else 0.0
    if operator == "<=":
        return 1.0 if raw_value <= threshold else 0.0
    return 0.0


def _evidence(
    field_name: str,
    field: NafpField,
    signal: str,
    value: str,
    rule: dict[str, Any],
    raw_value: float,
    normalized_score: float,
) -> dict[str, Any]:
    normalized = round(float(normalized_score), 6)
    weight = _rule_float(rule, "weight", 0.0)
    contribution = round(normalized * weight, 6)
    return {
        "entry_id": rule["entry_id"],
        "field": field_name,
        "signal": signal,
        "value": value,
        "statistic": rule.get("statistic"),
        "operator": rule.get("operator"),
        "threshold": rule.get("threshold"),
        "scale": rule.get("scale"),
        "raw_value": round(float(raw_value), 6),
        "normalized_score": normalized,
        "weight": weight,
        "contribution": contribution,
        "source_path": field.source_path,
        "unit": rule.get("unit"),
    }


def _system_evidence(
    field_name: str,
    field: NafpField,
    signal: str,
    value: str,
    rule: dict[str, Any],
    raw_value: float,
) -> dict[str, Any]:
    return {
        "entry_id": rule["entry_id"],
        "field": field_name,
        "signal": signal,
        "value": value,
        "statistic": rule.get("statistic"),
        "operator": rule.get("operator"),
        "threshold": rule.get("threshold"),
        "scale": rule.get("scale"),
        "raw_value": round(float(raw_value), 6),
        "normalized_score": None,
        "weight": rule.get("weight"),
        "contribution": None,
        "source_path": field.source_path,
        "unit": rule.get("unit"),
    }


def _derived_system_evidence(
    field_name: str,
    signal: str,
    value: str,
    rule: dict[str, Any],
    raw_value: float,
    source_paths: list[str],
) -> dict[str, Any]:
    return {
        "entry_id": rule["entry_id"],
        "field": field_name,
        "signal": signal,
        "value": value,
        "statistic": rule.get("statistic"),
        "operator": rule.get("operator"),
        "threshold": rule.get("threshold"),
        "scale": rule.get("scale"),
        "raw_value": round(float(raw_value), 6),
        "normalized_score": None,
        "weight": rule.get("weight"),
        "contribution": None,
        "source_path": source_paths[0] if source_paths else "",
        "source_paths": source_paths,
        "unit": rule.get("unit"),
    }


def _append_rule_evidence(
    evidence: list[dict[str, Any]],
    field_name: str,
    field: NafpField,
    signal: str,
    value: str,
    rule: dict[str, Any],
    raw_value: float,
) -> float:
    if not _rule_enabled(rule):
        return 0.0
    item = _evidence(
        field_name=field_name,
        field=field,
        signal=signal,
        value=value,
        rule=rule,
        raw_value=raw_value,
        normalized_score=_normalized_score(raw_value, rule),
    )
    evidence.append(item)
    return float(item["contribution"])


def _append_missing_if_enabled(missing: list[str], rule: dict[str, Any], field_name: str) -> None:
    if _rule_enabled(rule):
        missing.append(field_name)


def _dominant_evidence(evidence: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in evidence
        if item.get("contribution") is not None and float(item.get("contribution") or 0.0) > 0
    ]
    candidates.sort(key=lambda item: float(item.get("contribution") or 0.0), reverse=True)
    return [
        {
            "entry_id": item["entry_id"],
            "field": item["field"],
            "signal": item["signal"],
            "value": item["value"],
            "normalized_score": item["normalized_score"],
            "weight": item["weight"],
            "contribution": item["contribution"],
        }
        for item in candidates[:limit]
    ]


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


def _wind_components(fields: dict[str, NafpField], key: str) -> tuple[np.ndarray, np.ndarray] | None:
    field = fields[key]
    if not field.exists or "u" not in field.values or "v" not in field.values:
        return None
    return field.values["u"], field.values["v"]


def _to_celsius(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if np.nanmedian(arr) > 150:
        return arr - 273.15
    return arr


def _moisture_flux_from_fields(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    wind = _wind_components(fields, "uv850")
    q850 = field_array(fields["q850"], "q")
    if wind is None or q850 is None:
        return None, None
    u850, v850 = wind
    uv850_speed = np.hypot(u850, v850)
    if "uv850_speed" not in diagnostics:
        diagnostics["uv850_speed"] = {**finite_stats(uv850_speed), "source_path": fields["uv850"].source_path}
    moisture_flux = uv850_speed * q850
    diagnostics["moisture_flux850"] = {
        **finite_stats(moisture_flux),
        "source_paths": [fields["uv850"].source_path, fields["q850"].source_path],
    }
    dqu_dx, _ = derivatives_lonlat(q850 * u850, fields["q850"].lat, fields["q850"].lon)
    _, dqv_dy = derivatives_lonlat(q850 * v850, fields["q850"].lat, fields["q850"].lon)
    flux_divergence = (dqu_dx + dqv_dy) * 100000.0
    diagnostics["moisture_flux_divergence850"] = {
        **finite_stats(flux_divergence),
        "source_paths": [fields["uv850"].source_path, fields["q850"].source_path],
        "unit": "scaled",
    }
    return moisture_flux, flux_divergence


def _relative_vorticity_from_wind(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    key: str,
    out_key: str,
) -> np.ndarray | None:
    wind = _wind_components(fields, key)
    if wind is None:
        return None
    u, v = wind
    dvdx, _ = derivatives_lonlat(v, fields[key].lat, fields[key].lon)
    _, dudy = derivatives_lonlat(u, fields[key].lat, fields[key].lon)
    vorticity = (dvdx - dudy) * 100000.0
    diagnostics[out_key] = {
        **finite_stats(vorticity),
        "source_path": fields[key].source_path,
        "unit": "10^-5/s",
    }
    return vorticity


def _polygon_geometry_from_component(
    item: dict[str, Any],
    *,
    smooth_boundary: bool = False,
    boundary_smooth_km: float = 90.0,
    boundary_simplify_km: float = 30.0,
    reference_lat: float | None = None,
) -> dict[str, Any]:
    geometry = item["geometry"]
    if smooth_boundary:
        if reference_lat is None:
            reference_lat = float(item.get("centroid", [0.0, 25.0])[1])
        geometry = smooth_polygon_geometry(
            geometry,
            reference_lat=reference_lat,
            smooth_km=boundary_smooth_km,
            simplify_km=boundary_simplify_km,
        )
    return {
        "type": "polygon",
        "bbox": geometry_bounds(geometry),
        "source_bbox": item.get("bbox"),
        "coordinates": geometry["coordinates"],
        "geojson_type": geometry["type"],
        "boundary_smoothed": bool(smooth_boundary),
        "boundary_smooth_km": float(boundary_smooth_km) if smooth_boundary else 0.0,
        "boundary_simplify_km": float(boundary_simplify_km) if smooth_boundary else 0.0,
    }


def _line_geometry_from_component(item: dict[str, Any], lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    return component_axis_line(item, lat, lon)


def _component_area_km2(item: dict[str, Any], lat: np.ndarray, lon: np.ndarray) -> float:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    dy = float(np.nanmedian(np.abs(np.diff(lat_arr)))) * 111.32 if lat_arr.size > 1 else 111.32
    dx_deg = float(np.nanmedian(np.abs(np.diff(lon_arr)))) if lon_arr.size > 1 else 1.0
    lat_ref = float(np.nanmedian(lat_arr)) if lat_arr.size else 0.0
    dx = dx_deg * 111.32 * max(float(np.cos(np.deg2rad(lat_ref))), 0.2)
    return float(item.get("point_count", 0)) * max(dx, 1.0) * max(dy, 1.0)


def _line_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        lat_mid = (float(lat0) + float(lat1)) / 2.0
        dx = (float(lon1) - float(lon0)) * 111.32 * max(float(np.cos(np.deg2rad(lat_mid))), 0.2)
        dy = (float(lat1) - float(lat0)) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _divergence_absolute_threshold(values: np.ndarray, default_s1: float = 1.0e-5) -> float:
    valid = np.abs(np.asarray(values, dtype=float)[np.isfinite(values)])
    if valid.size == 0:
        return default_s1
    # Some NAFP diagnostic layers are scaled by 1e5. Use scaled absolute thresholds when values are O(1).
    return default_s1 * 100000.0 if float(np.nanpercentile(valid, 95)) > 0.01 else default_s1


def _apply_binary_morphology(mask: np.ndarray, *, closing_iter: int = 1, opening_iter: int = 0) -> np.ndarray:
    out = np.asarray(mask, dtype=bool)
    structure = np.ones((3, 3), dtype=bool)
    if opening_iter > 0:
        out = ndimage.binary_opening(out, structure=structure, iterations=opening_iter)
    if closing_iter > 0:
        out = ndimage.binary_closing(out, structure=structure, iterations=closing_iter)
    return out


def _fallback_domain_region(field: NafpField) -> dict[str, Any]:
    lon_min = float(np.nanmin(field.lon))
    lon_max = float(np.nanmax(field.lon))
    lat_min = float(np.nanmin(field.lat))
    lat_max = float(np.nanmax(field.lat))
    return {
        "type": "polygon",
        "bbox": [lon_min, lat_min, lon_max, lat_max],
        "coordinates": [[
            [lon_min, lat_min],
            [lon_max, lat_min],
            [lon_max, lat_max],
            [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
        "geojson_type": "Polygon",
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _geometry_extent_metric(system: dict[str, Any]) -> float:
    geometry = system.get("geometry") or {}
    geometry_type = geometry.get("type")
    if geometry_type == "point":
        pressure_difference = _safe_float(system.get("pressure_difference_hpa"))
        closed_count = _safe_float(system.get("closed_contour_count"))
        closed_area = _safe_float(system.get("closed_area_grid_points"))
        return pressure_difference * 10.0 + closed_count * 5.0 + closed_area * 0.05
    if geometry_type == "line":
        return float(len(geometry.get("coordinates") or []))
    bbox = geometry.get("bbox") or []
    if len(bbox) == 4:
        lon_min, lat_min, lon_max, lat_max = [_safe_float(value) for value in bbox]
        return abs(lon_max - lon_min) * abs(lat_max - lat_min)
    return 0.0


def _connected_point_metric(system: dict[str, Any]) -> float:
    values = []
    for item in system.get("evidence") or []:
        signal = str(item.get("signal") or "")
        value_text = str(item.get("value") or "")
        if "connected" in signal or "point_count" in value_text:
            values.append(_safe_float(item.get("raw_value")))
    return max(values) if values else 0.0


def _system_salience_metrics(system: dict[str, Any]) -> dict[str, float]:
    evidence_count = len(system.get("evidence") or [])
    return {
        "confidence": _clip01(_safe_float(system.get("confidence"), 0.5)),
        "extent": max(_geometry_extent_metric(system), _connected_point_metric(system)),
        "support": _clip01(evidence_count / 5.0),
    }


def _annotate_system_display_metadata(systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[int, dict[str, Any], dict[str, float]]]] = {}
    for original_index, system in enumerate(systems):
        system_type = str(system.get("type") or system.get("feature_type") or "unknown")
        grouped.setdefault(system_type, []).append((original_index, system, _system_salience_metrics(system)))

    annotated: list[dict[str, Any]] = []
    for system_type, entries in grouped.items():
        max_extent = max((metrics["extent"] for _, _, metrics in entries), default=0.0)
        scored_entries = []
        for original_index, system, metrics in entries:
            extent_score = metrics["extent"] / max_extent if max_extent > 0 else 0.0
            salience = _clip01(metrics["confidence"] * 0.58 + extent_score * 0.28 + metrics["support"] * 0.14)
            system["salience_score"] = round(salience, 4)
            scored_entries.append((original_index, system, metrics["confidence"], metrics["extent"]))

        scored_entries.sort(
            key=lambda entry: (
                _safe_float(entry[1].get("salience_score")),
                entry[2],
                entry[3],
                -entry[0],
            ),
            reverse=True,
        )
        primary_limit = PRIMARY_SYSTEM_LIMITS.get(system_type, 3)
        for type_rank, (_, system, _, _) in enumerate(scored_entries, start=1):
            system["type_rank"] = type_rank
            system["primary"] = type_rank <= primary_limit
            if system_type in DYNAMIC_CONFIDENCE_SYSTEM_TYPES:
                system["base_confidence"] = system.get("confidence")
                salience = _safe_float(system.get("salience_score"), 0.5)
                confidence = 0.48 + salience * 0.42 - (type_rank - 1) * 0.015
                system["confidence"] = round(_clip01(max(0.5, min(0.9, confidence))), 2)
            annotated.append(system)

    annotated.sort(
        key=lambda system: (
            0 if system.get("primary") else 1,
            SYSTEM_DISPLAY_PRIORITY.get(str(system.get("type") or ""), 999),
            -_safe_float(system.get("salience_score")),
            int(system.get("type_rank") or 0),
        )
    )
    for display_rank, system in enumerate(annotated, start=1):
        system["display_rank"] = display_rank
    return annotated


def _point_from_index(lat: np.ndarray, lon: np.ndarray, y: int, x: int, value: float) -> dict[str, float]:
    return {
        "lon": round(float(lon[int(x)]), 3),
        "lat": round(float(lat[int(y)]), 3),
        "value": round(float(value), 3),
    }


def _subtropical_high_metrics(
    item: dict[str, Any],
    gh: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    ys, xs = item["indices"]
    values = gh[ys, xs]
    max_pos = int(np.nanargmax(values))
    center_y = int(ys[max_pos])
    center_x = int(xs[max_pos])

    west_lon = float(np.nanmin(lon[xs]))
    west_candidates = np.where(np.isclose(lon[xs], west_lon))[0]
    if west_candidates.size:
        west_values = values[west_candidates]
        west_choice = int(west_candidates[int(np.nanargmax(west_values))])
    else:
        west_choice = max_pos
    ridge_y = int(ys[west_choice])
    ridge_x = int(xs[west_choice])

    lon_span = float(np.nanmax(lon[xs]) - np.nanmin(lon[xs]))
    lat_span = float(np.nanmax(lat[ys]) - np.nanmin(lat[ys]))
    if lon_span >= lat_span * 1.4:
        orientation = "zonal"
    elif lat_span >= lon_span * 1.4:
        orientation = "meridional"
    else:
        orientation = "compact"

    return {
        "center": _point_from_index(lat, lon, center_y, center_x, float(gh[center_y, center_x])),
        "ridge_point": _point_from_index(lat, lon, ridge_y, ridge_x, float(gh[ridge_y, ridge_x])),
        "north_boundary_lat": round(float(np.nanmax(lat[ys])), 3),
        "south_boundary_lat": round(float(np.nanmin(lat[ys])), 3),
        "west_boundary_lon": round(float(np.nanmin(lon[xs])), 3),
        "east_boundary_lon": round(float(np.nanmax(lon[xs])), 3),
        "area_grid_points": int(ys.size),
        "max_height": round(float(np.nanmax(values)), 3),
        "mean_height": round(float(np.nanmean(values)), 3),
        "threshold_height": round(float(threshold), 3),
        "axis_orientation": orientation,
        "lon_span": round(lon_span, 3),
        "lat_span": round(lat_span, 3),
    }


def _subtropical_high_evidence(
    field: NafpField,
    metrics: dict[str, Any],
    min_points_rule: dict[str, Any],
) -> list[dict[str, Any]]:
    source_paths = [field.source_path]
    return [
        _derived_system_evidence(
            "gh500",
            "subtropical high connected area extent",
            f"area_grid_points={metrics['area_grid_points']}, min_points={_rule_float(min_points_rule, 'threshold', 20.0):g}",
            {
                "entry_id": "system.subtropical_high.area_extent",
                "statistic": "area_grid_points",
                "operator": ">=",
                "threshold": min_points_rule.get("threshold"),
                "scale": None,
                "weight": None,
                "unit": "grid",
            },
            float(metrics["area_grid_points"]),
            source_paths,
        ),
        _derived_system_evidence(
            "gh500",
            "subtropical high westward ridge point",
            f"lon={metrics['ridge_point']['lon']:.3f}, lat={metrics['ridge_point']['lat']:.3f}, height={metrics['ridge_point']['value']:.2f}",
            {
                "entry_id": "system.subtropical_high.ridge_point",
                "statistic": "westmost_high_value_point",
                "operator": None,
                "threshold": None,
                "scale": None,
                "weight": None,
                "unit": "degree",
            },
            float(metrics["ridge_point"]["lon"]),
            source_paths,
        ),
        _derived_system_evidence(
            "gh500",
            "subtropical high northern boundary",
            f"north_boundary={metrics['north_boundary_lat']:.3f}, south_boundary={metrics['south_boundary_lat']:.3f}",
            {
                "entry_id": "system.subtropical_high.north_boundary",
                "statistic": "north_boundary_lat",
                "operator": None,
                "threshold": None,
                "scale": None,
                "weight": None,
                "unit": "degree",
            },
            float(metrics["north_boundary_lat"]),
            source_paths,
        ),
    ]


def _axis_orientation_label(value: str) -> str:
    return {
        "zonal": "纬向带状",
        "meridional": "经向伸展",
        "compact": "紧凑型",
    }.get(value, value)


def _front_candidate_systems(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    tt850 = field_array(fields["tt850"], "tt")
    if tt850 is None:
        return []
    div850 = field_array(fields["div850"], "div")
    ttadv850 = field_array(fields["ttadv850"], "ttadv")
    rh850 = field_array(fields["rh850"], "rh")
    wind850 = _wind_components(fields, "uv850")
    u850, v850 = wind850 if wind850 is not None else (None, None)
    tt_field = fields["tt850"]
    diagnostics["tt850"] = {**finite_stats(tt850), "source_path": tt_field.source_path}

    gradient_rule = rules["system.front_candidate.tt850_gradient_percentile"]
    score_rule = rules["system.front_candidate.score_percentile"]
    min_points_rule = rules["system.front_candidate.min_points"]
    max_objects_rule = rules["system.front_candidate.max_objects"]
    if not _rule_enabled(gradient_rule) or not _rule_enabled(score_rule):
        return []

    thresholds = {
        "front_candidate": {
            "temp_gradient_percentile": _rule_float(gradient_rule, "threshold", 80.0),
            "score_percentile": _rule_float(score_rule, "threshold", 82.0),
            "dynamic_support_percentile": _rule_float(rules["system.front_candidate.dynamic_support_percentile"], "threshold", 70.0),
            "min_support_components": int(_rule_float(rules["system.front_candidate.min_support_components"], "threshold", 1.0)),
            "min_area_grid_points": int(_rule_float(min_points_rule, "threshold", 10.0)),
            "output_geometry": "axis",
        }
    }
    derived = front_candidate_fields(
        tt850,
        div850,
        ttadv850,
        tt_field.lat,
        tt_field.lon,
        thresholds,
        u850=u850,
        v850=v850,
        rh850=rh850,
    )
    gradient_100km = derived["gradient"] * 100000.0
    gradient_threshold = float(derived["gradient_threshold"] * 100000.0)
    score_threshold = float(derived["score_threshold"])
    diagnostics["tt850_gradient"] = {**finite_stats(gradient_100km), "source_path": tt_field.source_path, "unit": "degC/100km"}
    diagnostics["front_candidate_score"] = finite_stats(derived["score"])
    diagnostics["frontogenesis850"] = {
        **finite_stats(derived["frontogenesis"]),
        "source_paths": [fields["tt850"].source_path, fields["uv850"].source_path] if fields["uv850"].exists else [fields["tt850"].source_path],
    }
    diagnostics["front_deformation850"] = {
        **finite_stats(derived["wind_deformation"]),
        "source_path": fields["uv850"].source_path if fields["uv850"].exists else "",
    }

    source_paths = [tt_field.source_path]
    for key in ["uv850", "div850", "ttadv850", "rh850"]:
        if fields[key].exists:
            source_paths.append(fields[key].source_path)

    systems = []
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    components = front_axis_components(
        derived,
        tt_field.lat,
        tt_field.lon,
        min_points=min_points,
        max_objects=max_objects,
        thresholds=thresholds,
    )
    for idx, component in enumerate(components, start=1):
        item = component["item"]
        line = component["line"]
        classification = component.get("classification") or {}
        front_type_label = classification.get("front_type_label") or component.get("front_type_label") or "锋面候选"
        front_type_confidence = classification.get("front_type_confidence")
        base_confidence = 0.66 if wind850 is not None else 0.58
        confidence = base_confidence
        if isinstance(front_type_confidence, (int, float)) and np.isfinite(front_type_confidence):
            confidence = float(np.clip(base_confidence + 0.12 * (float(front_type_confidence) - 0.5), 0.45, 0.85))
        evidence = [
            _system_evidence(
                "tt850",
                tt_field,
                "temperature gradient",
                f"gradient_p{_rule_float(gradient_rule, 'threshold', 80.0):g}={gradient_threshold:.3f} degC/100km",
                gradient_rule,
                gradient_threshold,
            ),
            _derived_system_evidence(
                "front_candidate_score",
                "front candidate composite score",
                f"score_p{_rule_float(score_rule, 'threshold', 82.0):g}={score_threshold:.3f}",
                score_rule,
                score_threshold,
                source_paths,
            ),
            _derived_system_evidence(
                "front_candidate_score",
                "front candidate axis extraction",
                f"axis_point_count={len(line.get('coordinates') or [])}, source_area_points={item['point_count']}",
                min_points_rule,
                float(item["point_count"]),
                source_paths,
            ),
            _derived_system_evidence(
                "front_candidate_score",
                "front candidate output rank",
                f"rank={idx}, max_objects={max_objects}",
                max_objects_rule,
                float(idx),
                source_paths,
            ),
        ]
        if wind850 is not None:
            dynamic_thresholds = [
                value
                for value in [derived["frontogenesis_threshold"], derived["wind_deformation_threshold"]]
                if np.isfinite(value)
            ]
            dynamic_raw = max(dynamic_thresholds) if dynamic_thresholds else 0.0
            evidence.insert(
                2,
                _derived_system_evidence(
                    "frontogenesis850",
                    "dynamic frontal support",
                    f"frontogenesis_p{_rule_float(rules['system.front_candidate.dynamic_support_percentile'], 'threshold', 70.0):g}={derived['frontogenesis_threshold']:.6g}, deformation_p{_rule_float(rules['system.front_candidate.dynamic_support_percentile'], 'threshold', 70.0):g}={derived['wind_deformation_threshold']:.6g}",
                    rules["system.front_candidate.dynamic_support_percentile"],
                    float(dynamic_raw),
                    source_paths,
                ),
            )
            evidence.insert(
                3,
                _derived_system_evidence(
                    "front_support_count",
                    "front dynamic support component count",
                    f"support_count_max={int(np.nanmax(derived['support_count']))}, min_support={int(_rule_float(rules['system.front_candidate.min_support_components'], 'threshold', 1.0))}",
                    rules["system.front_candidate.min_support_components"],
                    float(np.nanmax(derived["support_count"])),
                    source_paths,
                ),
            )
        systems.append(
            {
                "id": f"system-front-candidate-850-{idx}",
                "type": "front_candidate",
                "feature_type": "front_candidate",
                "name": f"850hPa {front_type_label}轴线",
                "level": "850",
                "geometry": {
                    "type": "line",
                    "coordinates": line.get("coordinates") or [],
                    "bbox": line.get("bbox"),
                },
                "source_area_bbox": item.get("bbox"),
                "source_area_point_count": item.get("point_count"),
                "axis_length_km": round(_line_length_km(line.get("coordinates") or []), 1),
                "front_type": classification.get("front_type") or component.get("front_type") or "front_candidate",
                "front_type_label": front_type_label,
                "front_motion": classification.get("front_motion") or component.get("front_motion") or "undetermined",
                "front_motion_label": classification.get("front_motion_label") or "",
                "front_type_confidence": front_type_confidence,
                "cross_front_wind_mean_ms": classification.get("cross_front_wind_mean_ms"),
                "cross_front_wind_abs_mean_ms": classification.get("cross_front_wind_abs_mean_ms"),
                "cold_front_ratio": classification.get("cold_front_ratio"),
                "warm_front_ratio": classification.get("warm_front_ratio"),
                "stationary_front_ratio": classification.get("stationary_front_ratio"),
                "temperature_advection_mean": classification.get("temperature_advection_mean"),
                "temperature_advection_source": classification.get("temperature_advection_source"),
                "classification_reason": classification.get("classification_reason") or "",
                "confidence": round(confidence, 2),
                "diagnosis": classification.get("classification_reason")
                or "850hPa 温度梯度、风场形变、锋生函数、低层辐合和温度平流综合识别锋面候选区，并抽取为锋面轴线。",
                "evidence": evidence,
            }
        )
    return systems

def _low_level_jet_systems(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    rules: dict[str, dict],
    moisture_flux: np.ndarray | None,
) -> list[dict[str, Any]]:
    wind = _wind_components(fields, "uv850")
    if wind is None:
        return []
    u850, v850 = wind
    speed = np.hypot(u850, v850)
    diagnostics["uv850_speed"] = {**finite_stats(speed), "source_path": fields["uv850"].source_path}

    wind_rule = rules["system.low_level_jet.wind_speed_min"]
    flux_rule = rules["system.low_level_jet.moisture_flux_percentile"]
    min_points_rule = rules["system.low_level_jet.min_points"]
    coherence_rule = rules["system.low_level_jet.min_direction_coherence"]
    max_objects_rule = rules["system.low_level_jet.max_objects"]
    if not _rule_enabled(wind_rule):
        return []
    wind_min = _rule_float(wind_rule, "threshold", 10.0)
    min_points = int(_rule_float(min_points_rule, "threshold", 8.0))
    min_coherence = _rule_float(coherence_rule, "threshold", 0.65)
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    mask = speed >= wind_min
    source_paths = [fields["uv850"].source_path]
    flux_threshold = None
    if moisture_flux is not None and _rule_enabled(flux_rule):
        flux_percentile = _rule_float(flux_rule, "threshold", 70.0)
        flux_threshold = float(np.nanpercentile(moisture_flux, flux_percentile))
        mask &= moisture_flux >= flux_threshold
        source_paths.append(fields["q850"].source_path)

    systems = []
    components = ranked_transport_components(
        mask,
        fields["uv850"].lat,
        fields["uv850"].lon,
        speed,
        min_points=min_points,
        max_objects=max_objects,
        u=u850,
        v=v850,
        min_direction_coherence=min_coherence,
    )
    for idx, component in enumerate(components, start=1):
        item = component["item"]
        max_speed = float(component["max_value"])
        evidence = [
            _system_evidence(
                "uv850_speed",
                fields["uv850"],
                "850hPa wind speed maximum",
                f"max={max_speed:.2f} m/s, threshold={wind_min:.2f}",
                wind_rule,
                max_speed,
            )
        ]
        evidence.append(
            _derived_system_evidence(
                "uv850",
                "low-level jet wind direction coherence",
                f"coherence={component['direction_coherence']:.3f}, threshold={min_coherence:.2f}",
                coherence_rule,
                float(component["direction_coherence"] or 0.0),
                source_paths,
            )
        )
        if flux_threshold is not None:
            evidence.append(
                _derived_system_evidence(
                    "moisture_flux850",
                    "low-level jet moisture flux support",
                    f"p{_rule_float(flux_rule, 'threshold', 70.0):g}={flux_threshold:.2f}",
                    flux_rule,
                    flux_threshold,
                    source_paths,
                )
            )
        evidence.append(
            _derived_system_evidence(
                "uv850_speed",
                "low-level jet connected area",
                f"point_count={item['point_count']}, min_points={min_points}",
                min_points_rule,
                float(item["point_count"]),
                source_paths,
            )
        )
        evidence.append(
            _derived_system_evidence(
                "uv850_speed",
                "low-level jet output rank",
                f"rank={idx}, max_objects={max_objects}",
                max_objects_rule,
                float(idx),
                source_paths,
            )
        )
        systems.append(
            {
                "id": f"system-low-level-jet-850-{idx}",
                "type": "low_level_jet",
                "feature_type": "low_level_jet",
                "name": "850hPa 低空急流候选",
                "level": "850",
                "geometry": {
                    "type": "line",
                    "coordinates": component["line"]["coordinates"],
                    "bbox": component["line"]["bbox"],
                },
                "axis_method": component.get("axis_method"),
                "axis_length_km": round(float(component.get("axis_length_km", _line_length_km(component["line"].get("coordinates") or []))), 1),
                "source_area_km2": round(float(component.get("area_km2", _component_area_km2(item, fields["uv850"].lat, fields["uv850"].lon))), 1),
                "confidence": round(min(0.9, 0.55 + max(0.0, max_speed - wind_min) / max(wind_min, 1.0) * 0.2), 2),
                "diagnosis": "850hPa 低空急流：低层风速高值、水汽通量高值和风向一致性共同指示暖湿输送急流轴。",
                "evidence": evidence,
            }
        )
    return systems


def _moisture_transport_systems(
    fields: dict[str, NafpField],
    rules: dict[str, dict],
    moisture_flux: np.ndarray | None,
) -> list[dict[str, Any]]:
    if moisture_flux is None:
        return []
    flux_rule = rules["system.moisture_transport.flux_percentile"]
    min_points_rule = rules["system.moisture_transport.min_points"]
    coherence_rule = rules["system.moisture_transport.min_direction_coherence"]
    max_objects_rule = rules["system.moisture_transport.max_objects"]
    if not _rule_enabled(flux_rule):
        return []
    percentile = _rule_float(flux_rule, "threshold", 75.0)
    threshold = float(np.nanpercentile(moisture_flux, percentile))
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    min_coherence = _rule_float(coherence_rule, "threshold", 0.65)
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    mask = moisture_flux >= threshold
    source_paths = [fields["uv850"].source_path, fields["q850"].source_path]
    wind = _wind_components(fields, "uv850")
    u850, v850 = wind if wind is not None else (None, None)
    systems = []
    components = ranked_transport_components(
        mask,
        fields["q850"].lat,
        fields["q850"].lon,
        moisture_flux,
        min_points=min_points,
        max_objects=max_objects,
        u=u850,
        v=v850,
        min_direction_coherence=min_coherence if wind is not None else 0.0,
    )
    for idx, component in enumerate(components, start=1):
        item = component["item"]
        max_flux = float(component["max_value"])
        systems.append(
            {
                "id": f"system-moisture-transport-850-{idx}",
                "type": "moisture_transport",
                "feature_type": "moisture_transport",
                "name": "850hPa 水汽输送带候选",
                "level": "850",
                "geometry": {
                    "type": "line",
                    "coordinates": component["line"]["coordinates"],
                    "bbox": component["line"]["bbox"],
                },
                "axis_method": component.get("axis_method"),
                "axis_length_km": round(float(component.get("axis_length_km", _line_length_km(component["line"].get("coordinates") or []))), 1),
                "source_area_km2": round(float(component.get("area_km2", _component_area_km2(item, fields["q850"].lat, fields["q850"].lon))), 1),
                "confidence": 0.72 if wind is not None else 0.66,
                "diagnosis": "850hPa 水汽输送带：水汽通量高值呈连续轴带，风向一致性支持暖湿输送通道。",
                "evidence": [
                    _derived_system_evidence(
                        "moisture_flux850",
                        "moisture flux high percentile",
                        f"p{percentile:g}={threshold:.2f}, max={max_flux:.2f}",
                        flux_rule,
                        max_flux,
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "uv850",
                        "moisture transport wind direction coherence",
                        f"coherence={(component['direction_coherence'] or 0.0):.3f}, threshold={min_coherence:.2f}",
                        coherence_rule,
                        float(component["direction_coherence"] or 0.0),
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "moisture_flux850",
                        "moisture transport connected area",
                        f"point_count={item['point_count']}, min_points={min_points}",
                        min_points_rule,
                        float(item["point_count"]),
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "moisture_flux850",
                        "moisture transport output rank",
                        f"rank={idx}, max_objects={max_objects}",
                        max_objects_rule,
                        float(idx),
                        source_paths,
                    ),
                ],
            }
        )
    return systems


def _moisture_convergence_systems(
    fields: dict[str, NafpField],
    rules: dict[str, dict],
    moisture_flux: np.ndarray | None,
    flux_divergence: np.ndarray | None,
) -> list[dict[str, Any]]:
    if moisture_flux is None or flux_divergence is None:
        return []
    div_rule = rules["system.moisture_convergence.flux_divergence_percentile"]
    flux_rule = rules["system.moisture_convergence.moisture_flux_percentile"]
    min_points_rule = rules["system.moisture_convergence.min_points"]
    smooth_rule = rules["system.moisture_convergence.smoothing_sigma_grid"]
    max_objects_rule = rules["system.moisture_convergence.max_objects"]
    if not _rule_enabled(div_rule):
        return []
    div_percentile = _rule_float(div_rule, "threshold", 10.0)
    sigma = _rule_float(smooth_rule, "threshold", 1.0)
    smoothed_divergence = smooth_field(flux_divergence, sigma)
    div_threshold = float(np.nanpercentile(smoothed_divergence, div_percentile))
    mask = smoothed_divergence <= div_threshold
    flux_threshold = None
    if _rule_enabled(flux_rule):
        flux_percentile = _rule_float(flux_rule, "threshold", 55.0)
        flux_threshold = float(np.nanpercentile(moisture_flux, flux_percentile))
        mask &= moisture_flux >= flux_threshold
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    source_paths = [fields["uv850"].source_path, fields["q850"].source_path]
    systems = []
    items = ranked_mask_items(
        mask,
        fields["q850"].lat,
        fields["q850"].lon,
        min_points=min_points,
        max_objects=max_objects,
        primary_value=smoothed_divergence,
        descending=False,
    )
    for idx, item in enumerate(items, start=1):
        ys, xs = item["indices"]
        mean_div = float(np.nanmean(smoothed_divergence[ys, xs]))
        raw_mean_div = float(np.nanmean(flux_divergence[ys, xs]))
        evidence = [
            _derived_system_evidence(
                "moisture_flux_divergence850",
                "smoothed water vapor flux convergence",
                f"smoothed_mean={mean_div:.2f}, raw_mean={raw_mean_div:.2f}, p{div_percentile:g}={div_threshold:.2f}",
                div_rule,
                mean_div,
                source_paths,
            ),
            _derived_system_evidence(
                "moisture_flux_divergence850_smoothed",
                "moisture convergence smoothing scale",
                f"sigma_grid={sigma:g}",
                smooth_rule,
                sigma,
                source_paths,
            )
        ]
        if flux_threshold is not None:
            evidence.append(
                _derived_system_evidence(
                    "moisture_flux850",
                    "moisture supply for convergence",
                    f"p{_rule_float(flux_rule, 'threshold', 55.0):g}={flux_threshold:.2f}",
                    flux_rule,
                    flux_threshold,
                    source_paths,
                )
            )
        evidence.append(
            _derived_system_evidence(
                "moisture_flux_divergence850",
                "moisture convergence connected area",
                f"point_count={item['point_count']}, min_points={min_points}",
                min_points_rule,
                float(item["point_count"]),
                source_paths,
            )
        )
        evidence.append(
            _derived_system_evidence(
                "moisture_flux_divergence850",
                "moisture convergence output rank",
                f"rank={idx}, max_objects={max_objects}",
                max_objects_rule,
                float(idx),
                source_paths,
            )
        )
        systems.append(
            {
                "id": f"system-moisture-convergence-850-{idx}",
                "type": "moisture_convergence",
                "feature_type": "moisture_convergence",
                "name": "850hPa 水汽辐合区候选",
                "level": "850",
                "geometry": _polygon_geometry_from_component(item),
                "confidence": 0.68,
                "diagnosis": "850hPa 水汽辐合区：平滑后水汽通量散度为低值且水汽输送较强，提示主要水汽堆积区。",
                "evidence": evidence,
            }
        )
    return systems


def _low_level_convergence_systems(
    fields: dict[str, NafpField],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    div850 = field_array(fields["div850"], "div")
    if div850 is None:
        return []
    div_rule = rules["system.low_level_convergence.div850_percentile"]
    min_points_rule = rules["system.low_level_convergence.min_points"]
    smooth_rule = rules["system.low_level_convergence.smoothing_sigma_grid"]
    max_objects_rule = rules["system.low_level_convergence.max_objects"]
    if not _rule_enabled(div_rule):
        return []
    percentile = _rule_float(div_rule, "threshold", 10.0)
    sigma = _rule_float(smooth_rule, "threshold", 1.0)
    smoothed_div850 = smooth_field(div850, sigma)
    percentile_threshold = float(np.nanpercentile(smoothed_div850, percentile))
    absolute_threshold = -_divergence_absolute_threshold(smoothed_div850)
    threshold = min(percentile_threshold, absolute_threshold)
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    min_area_km2 = max(0.0, min_points * _component_area_km2({"point_count": 1}, fields["div850"].lat, fields["div850"].lon))
    mask = smoothed_div850 <= threshold
    wind850 = _wind_components(fields, "uv850")
    source_paths = [fields["div850"].source_path]
    if wind850 is not None:
        u850, v850 = wind850
        dudx, _ = derivatives_lonlat(u850, fields["uv850"].lat, fields["uv850"].lon)
        _, dvdy = derivatives_lonlat(v850, fields["uv850"].lat, fields["uv850"].lon)
        vector_div850 = smooth_field((dudx + dvdy) * 100000.0, sigma)
        vector_abs = _divergence_absolute_threshold(vector_div850)
        mask &= vector_div850 <= -0.25 * vector_abs
        source_paths.append(fields["uv850"].source_path)
    mask = _apply_binary_morphology(mask, closing_iter=1, opening_iter=0)
    systems = []
    items = ranked_mask_items(
        mask,
        fields["div850"].lat,
        fields["div850"].lon,
        min_points=min_points,
        max_objects=max_objects,
        primary_value=smoothed_div850,
        descending=False,
        min_mean_strength=abs(absolute_threshold) * 0.35,
        min_max_strength=abs(absolute_threshold),
        min_area_km2=min_area_km2,
    )
    for idx, item in enumerate(items, start=1):
        ys, xs = item["indices"]
        mean_div = float(np.nanmean(smoothed_div850[ys, xs]))
        raw_mean_div = float(np.nanmean(div850[ys, xs]))
        systems.append(
            {
                "id": f"system-low-level-convergence-850-{idx}",
                "type": "low_level_convergence",
                "feature_type": "low_level_convergence",
                "name": "850hPa 低层辐合区",
                "level": "850",
                "geometry": _polygon_geometry_from_component(item),
                "area_km2": round(float(item.get("area_km2", _component_area_km2(item, fields["div850"].lat, fields["div850"].lon))), 1),
                "mean_strength": round(float(item.get("mean_strength", abs(mean_div))), 6),
                "max_strength": round(float(item.get("max_strength", abs(np.nanmin(smoothed_div850[ys, xs])))), 6),
                "threshold_value": threshold,
                "percentile_threshold": percentile_threshold,
                "absolute_threshold": absolute_threshold,
                "confidence": 0.70 if wind850 is not None else 0.63,
                "diagnosis": "850hPa 低层辐合区：平滑后散度低值同时满足绝对强度与分位约束，并进行形态学和面积过滤以减少弱场误报。",
                "evidence": [
                    _system_evidence(
                        "div850",
                        fields["div850"],
                        "smoothed low-level convergence absolute and percentile threshold",
                        f"smoothed_mean={mean_div:.2f}, raw_mean={raw_mean_div:.2f}, threshold={threshold:.2f}, p{percentile:g}={percentile_threshold:.2f}, absolute={absolute_threshold:.2f}",
                        div_rule,
                        mean_div,
                    ),
                    _derived_system_evidence(
                        "div850_smoothed",
                        "low-level convergence smoothing and morphology",
                        f"sigma_grid={sigma:g}, morphology=closing(1), min_area_km2={min_area_km2:.0f}",
                        smooth_rule,
                        sigma,
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "div850",
                        "low-level convergence connected area",
                        f"point_count={item['point_count']}, area_km2={float(item.get('area_km2', 0.0)):.0f}, min_points={min_points}",
                        min_points_rule,
                        float(item["point_count"]),
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "div850",
                        "low-level convergence output rank",
                        f"rank={idx}, max_objects={max_objects}",
                        max_objects_rule,
                        float(idx),
                        source_paths,
                    ),
                ],
            }
        )
    return systems

def _upper_divergence_systems(
    fields: dict[str, NafpField],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    div_rule = rules["system.upper_divergence.divergence_percentile"]
    min_points_rule = rules["system.upper_divergence.min_points"]
    smooth_rule = rules["system.upper_divergence.smoothing_sigma_grid"]
    max_objects_rule = rules["system.upper_divergence.max_objects"]
    if not _rule_enabled(div_rule):
        return []
    percentile = _rule_float(div_rule, "threshold", 90.0)
    sigma = _rule_float(smooth_rule, "threshold", 1.0)
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    candidates: list[dict[str, Any]] = []
    for key, level in [("div200", "200"), ("div300", "300")]:
        div = field_array(fields[key], "div")
        if div is None:
            continue
        smoothed_div = smooth_field(div, sigma)
        percentile_threshold = float(np.nanpercentile(smoothed_div, percentile))
        absolute_threshold = _divergence_absolute_threshold(smoothed_div)
        threshold = max(percentile_threshold, absolute_threshold)
        min_area_km2 = max(0.0, min_points * _component_area_km2({"point_count": 1}, fields[key].lat, fields[key].lon))
        mask = _apply_binary_morphology(smoothed_div >= threshold, closing_iter=1, opening_iter=0)
        items = ranked_mask_items(
            mask,
            fields[key].lat,
            fields[key].lon,
            min_points=min_points,
            max_objects=max_objects,
            primary_value=smoothed_div,
            descending=True,
            min_mean_strength=absolute_threshold * 0.35,
            min_max_strength=absolute_threshold,
            min_area_km2=min_area_km2,
        )
        for item in items:
            ys, xs = item["indices"]
            candidates.append(
                {
                    "key": key,
                    "level": level,
                    "field": fields[key],
                    "item": item,
                    "smoothed_div": smoothed_div,
                    "raw_div": div,
                    "threshold": threshold,
                    "percentile_threshold": percentile_threshold,
                    "absolute_threshold": absolute_threshold,
                    "mean_div": float(np.nanmean(smoothed_div[ys, xs])),
                    "raw_mean_div": float(np.nanmean(div[ys, xs])),
                    "point_count": item["point_count"],
                    "area_km2": float(item.get("area_km2", _component_area_km2(item, fields[key].lat, fields[key].lon))),
                    "max_strength": float(item.get("max_strength", np.nanmax(smoothed_div[ys, xs]))),
                }
            )
    candidates.sort(key=lambda candidate: (candidate["max_strength"], candidate["area_km2"], candidate["mean_div"]), reverse=True)
    systems = []
    for idx, candidate in enumerate(candidates[:max_objects], start=1):
        key = candidate["key"]
        level = candidate["level"]
        field = candidate["field"]
        item = candidate["item"]
        mean_div = candidate["mean_div"]
        raw_mean_div = candidate["raw_mean_div"]
        threshold = candidate["threshold"]
        systems.append(
            {
                "id": f"system-upper-divergence-{level}-{idx}",
                "type": "upper_divergence",
                "feature_type": "upper_divergence",
                "name": f"{level}hPa 高空辐散区",
                "level": level,
                "geometry": _polygon_geometry_from_component(item),
                "area_km2": round(float(candidate["area_km2"]), 1),
                "mean_strength": round(float(item.get("mean_strength", mean_div)), 6),
                "max_strength": round(float(candidate["max_strength"]), 6),
                "threshold_value": threshold,
                "percentile_threshold": candidate["percentile_threshold"],
                "absolute_threshold": candidate["absolute_threshold"],
                "confidence": 0.68,
                "diagnosis": f"{level}hPa 高空辐散区：平滑后高空正散度高值同时满足绝对强度与分位约束，有利于下方补偿上升。",
                "evidence": [
                    _system_evidence(
                        key,
                        field,
                        "smoothed upper-level divergence absolute and percentile threshold",
                        f"smoothed_mean={mean_div:.2f}, raw_mean={raw_mean_div:.2f}, threshold={threshold:.2f}, p{percentile:g}={candidate['percentile_threshold']:.2f}, absolute={candidate['absolute_threshold']:.2f}",
                        div_rule,
                        mean_div,
                    ),
                    _derived_system_evidence(
                        f"{key}_smoothed",
                        "upper-level divergence smoothing and morphology",
                        f"sigma_grid={sigma:g}, morphology=closing(1)",
                        smooth_rule,
                        sigma,
                        [field.source_path],
                    ),
                    _derived_system_evidence(
                        key,
                        "upper-level divergence connected area",
                        f"point_count={item['point_count']}, area_km2={candidate['area_km2']:.0f}, min_points={min_points}",
                        min_points_rule,
                        float(item["point_count"]),
                        [field.source_path],
                    ),
                    _derived_system_evidence(
                        key,
                        "upper-level divergence output rank",
                        f"rank={idx}, max_objects={max_objects}",
                        max_objects_rule,
                        float(idx),
                        [field.source_path],
                    ),
                ],
            }
        )
    return systems

def _trough_ridge_axis_systems(
    fields: dict[str, NafpField],
    anomaly: np.ndarray,
    rules: dict[str, dict],
    vorticity500: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    axis_rule = rules["system.trough_ridge.axis_anomaly_percentile"]
    curvature_rule = rules["system.trough_ridge.curvature_percentile"]
    min_points_rule = rules["system.trough_ridge.min_points_per_line"]
    max_lines_rule = rules["system.trough_ridge.max_lines"]
    if not _rule_enabled(axis_rule):
        return []

    gh_field = fields["gh500"]
    percentile = _rule_float(axis_rule, "threshold", 20.0)
    curvature_percentile = _rule_float(curvature_rule, "threshold", 55.0)
    min_points = int(_rule_float(min_points_rule, "threshold", 4.0))
    max_lines = int(_rule_float(max_lines_rule, "threshold", 8.0))
    source_paths = [gh_field.source_path]
    if vorticity500 is not None and fields["uv500"].exists:
        source_paths.append(fields["uv500"].source_path)
    systems = []
    for mode, system_type, label in [
        ("trough", "trough_candidate", "槽线"),
        ("ridge", "ridge_candidate", "脊线"),
    ]:
        candidates = trough_ridge_axis_candidates(
            anomaly,
            gh_field.lat,
            gh_field.lon,
            mode=mode,
            percentile=percentile,
            min_points=min_points,
            max_lines=max_lines,
            curvature_percentile=curvature_percentile,
            vorticity=vorticity500,
        )
        percentile_label = percentile if mode == "trough" else 100.0 - percentile
        for candidate in candidates:
            evidence = [
                _system_evidence(
                    "gh500_anomaly",
                    gh_field,
                    "curvature-supported height anomaly axis",
                    f"axis_p{percentile_label:g}={candidate['threshold_value']:.2f}",
                    axis_rule,
                    float(candidate["threshold_value"]),
                ),
                _derived_system_evidence(
                    "gh500_curvature",
                    "height curvature support",
                    f"mean={candidate['curvature_mean']:.3f}, p{curvature_percentile:g}={candidate['curvature_threshold']:.3f}",
                    curvature_rule,
                    float(candidate["curvature_mean"]),
                    [gh_field.source_path],
                ),
                _derived_system_evidence(
                    "gh500_anomaly",
                    "axis connected point count",
                    f"point_count={candidate['point_count']}, min_points={min_points}",
                    min_points_rule,
                    float(candidate["point_count"]),
                    [gh_field.source_path],
                ),
                _derived_system_evidence(
                    "gh500_anomaly",
                    "axis rank within output limit",
                    f"rank={candidate['rank']}, max_lines={max_lines}",
                    max_lines_rule,
                    float(candidate["rank"]),
                    [gh_field.source_path],
                ),
            ]
            if candidate["vorticity_support_mean"] is not None:
                evidence.append(
                    _derived_system_evidence(
                        "vorticity500",
                        "relative vorticity sign support",
                        f"support_mean={candidate['vorticity_support_mean']:.3f}",
                        rules["system.trough_ridge.vorticity_support"],
                        float(candidate["vorticity_support_mean"]),
                        source_paths,
                    )
                )
            systems.append(
                {
                    "id": f"system-{mode}-axis-500-{candidate['rank']}",
                    "type": system_type,
                    "feature_type": system_type,
                    "name": f"500hPa {label}轴线",
                    "level": "500",
                    "geometry": {
                        "type": "line",
                        "coordinates": candidate["coordinates"],
                    },
                    "confidence": 0.70 if "curvature" in str(candidate.get("method", "")) else 0.60,
                    "diagnosis": f"500hPa 位势高度距平尾部、等高线曲率和涡度符号支撑共同识别{label}轴线。",
                    "method": candidate["method"],
                    "evidence": evidence,
                }
            )
    return systems


def _surface_pressure_center_evidence(
    field: NafpField,
    props: dict[str, Any],
) -> list[dict[str, Any]]:
    center_value = float(props.get("value") or 0.0)
    closed_count = int(props.get("closed_contour_count") or 0)
    pressure_difference = float(props.get("pressure_difference_hpa") or 0.0)
    outer_contour = props.get("outer_closed_contour_hpa")
    return [
        {
            "entry_id": f"system.surface_pressure_center.{props.get('feature_type')}",
            "field": "mslp",
            "signal": "surface pressure local extremum",
            "value": f"center={center_value:.2f} hPa",
            "statistic": "local_extremum",
            "operator": "closed_isobar",
            "threshold": None,
            "scale": None,
            "raw_value": round(center_value, 6),
            "normalized_score": None,
            "weight": None,
            "contribution": None,
            "source_path": field.source_path,
            "unit": "hPa",
        },
        {
            "entry_id": "system.surface_pressure_center.closed_contours",
            "field": "mslp",
            "signal": "closed sea-level pressure contours",
            "value": f"closed_contours={closed_count}, outer={outer_contour} hPa",
            "statistic": "closed_contour_count",
            "operator": ">=",
            "threshold": None,
            "scale": None,
            "raw_value": float(closed_count),
            "normalized_score": None,
            "weight": None,
            "contribution": None,
            "source_path": field.source_path,
            "unit": "count",
        },
        {
            "entry_id": "system.surface_pressure_center.closed_area",
            "field": "mslp",
            "signal": "outer closed contour area",
            "value": f"closed_area_km2={float(props.get('closed_area_km2') or 0.0):.0f}",
            "statistic": "closed_area_km2",
            "operator": ">=",
            "threshold": None,
            "scale": None,
            "raw_value": float(props.get("closed_area_km2") or 0.0),
            "normalized_score": None,
            "weight": None,
            "contribution": None,
            "source_path": field.source_path,
            "unit": "km2",
        },
        {
            "entry_id": "system.surface_pressure_center.pressure_difference",
            "field": "mslp",
            "signal": "center to outer closed contour pressure difference",
            "value": f"pressure_difference={pressure_difference:.2f} hPa",
            "statistic": "pressure_difference_hpa",
            "operator": ">=",
            "threshold": None,
            "scale": None,
            "raw_value": round(pressure_difference, 6),
            "normalized_score": None,
            "weight": None,
            "contribution": None,
            "source_path": field.source_path,
            "unit": "hPa",
        },
    ]


def _surface_pressure_center_systems(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    field = fields.get("mslp")
    if field is None:
        return []
    mslp = field_array(field, "seap")
    if mslp is None or not np.isfinite(mslp).any():
        return []
    diagnostics["mslp"] = {**finite_stats(mslp), "source_path": field.source_path}

    systems: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for feature in detect_high_low(mslp, field.lat, field.lon, load_thresholds()):
        props = feature.get("properties") or {}
        feature_type = str(props.get("feature_type") or "")
        if feature_type not in {"high", "low"}:
            continue
        coordinates = feature.get("geometry", {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        lon, lat = float(coordinates[0]), float(coordinates[1])
        type_counts[feature_type] = type_counts.get(feature_type, 0) + 1
        rank = type_counts[feature_type]
        name = "海平面高压中心" if feature_type == "high" else "海平面低压中心"
        extremum_name = "高值" if feature_type == "high" else "低值"
        systems.append(
            {
                "id": f"system-surface-pressure-{feature_type}-{rank:03d}",
                "type": feature_type,
                "feature_type": feature_type,
                "name": name,
                "label": props.get("label"),
                "level": "mslp",
                "geometry": {
                    "type": "point",
                    "coordinates": [lon, lat],
                    "bbox": [lon, lat, lon, lat],
                },
                "value": props.get("value"),
                "unit": props.get("unit") or "hPa",
                "confidence": props.get("confidence"),
                "closed_contour_count": props.get("closed_contour_count"),
                "outer_closed_contour_hpa": props.get("outer_closed_contour_hpa"),
                "pressure_difference_hpa": props.get("pressure_difference_hpa"),
                "closed_area_grid_points": props.get("closed_area_grid_points"),
                "closed_area_km2": props.get("closed_area_km2"),
                "diagnosis": f"{name}由海平面气压局地{extremum_name}和闭合等压线共同识别，并使用物理距离/面积阈值过滤小尺度伪中心。",
                "evidence": _surface_pressure_center_evidence(field, props),
            }
        )
    return systems


def _pressure_center_systems(
    fields: dict[str, NafpField],
    anomaly: np.ndarray,
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    div850 = field_array(fields["div850"], "div")
    if div850 is None or not np.isfinite(div850).any():
        return []

    gh_field = fields["gh500"]
    div_field = fields["div850"]
    min_points_rule = rules["system.pressure_center.min_points"]
    max_centers_rule = rules["system.pressure_center.max_centers"]
    min_points = int(_rule_float(min_points_rule, "threshold", 12.0))
    max_centers = max(1, int(_rule_float(max_centers_rule, "threshold", 6.0)))
    source_paths = [gh_field.source_path, div_field.source_path]

    specs = [
        {
            "system_type": "low_pressure_convergence",
            "label": "低压辐合",
            "name": "500hPa 低压辐合候选区",
            "height_signal": "height negative anomaly",
            "div_signal": "low-level convergence",
            "height_rule": rules["system.low_pressure.gh500_anomaly_percentile"],
            "div_rule": rules["system.low_pressure.div850_convergence_percentile"],
            "height_mask": lambda value, cutoff: value <= cutoff,
            "div_mask": lambda value, cutoff: value <= cutoff,
            "height_fallback": 20.0,
            "div_fallback": 10.0,
        },
        {
            "system_type": "high_pressure_divergence",
            "label": "高压辐散",
            "name": "500hPa 高压辐散候选区",
            "height_signal": "height positive anomaly",
            "div_signal": "low-level divergence",
            "height_rule": rules["system.high_pressure.gh500_anomaly_percentile"],
            "div_rule": rules["system.high_pressure.div850_divergence_percentile"],
            "height_mask": lambda value, cutoff: value >= cutoff,
            "div_mask": lambda value, cutoff: value >= cutoff,
            "height_fallback": 80.0,
            "div_fallback": 90.0,
        },
    ]

    systems: list[dict[str, Any]] = []
    for spec in specs:
        height_rule = spec["height_rule"]
        div_rule = spec["div_rule"]
        if not _rule_enabled(height_rule) or not _rule_enabled(div_rule):
            continue
        height_percentile = _rule_float(height_rule, "threshold", spec["height_fallback"])
        div_percentile = _rule_float(div_rule, "threshold", spec["div_fallback"])
        height_cutoff = float(np.nanpercentile(anomaly, height_percentile))
        div_cutoff = float(np.nanpercentile(div850, div_percentile))
        mask = spec["height_mask"](anomaly, height_cutoff) & spec["div_mask"](div850, div_cutoff)
        features = mask_to_bbox_features(mask, gh_field.lat, gh_field.lon, min_points=min_points)
        features.sort(key=lambda item: item["point_count"], reverse=True)
        for idx, item in enumerate(features[:max_centers], start=1):
            ys, xs = item["indices"]
            height_mean = float(np.nanmean(anomaly[ys, xs]))
            div_mean = float(np.nanmean(div850[ys, xs]))
            systems.append(
                {
                    "id": f"system-{spec['system_type']}-500-850-{idx}",
                    "type": spec["system_type"],
                    "feature_type": spec["system_type"],
                    "name": spec["name"],
                    "level": "500/850",
                    "geometry": _polygon_geometry_from_component(item),
                    "confidence": 0.62,
                    "diagnosis": f"{spec['label']}由 500hPa 位势高度距平中心与 850hPa 低层{'辐合' if spec['system_type'].startswith('low') else '辐散'}共同识别。",
                    "evidence": [
                        _system_evidence(
                            "gh500_anomaly",
                            gh_field,
                            spec["height_signal"],
                            f"mean={height_mean:.2f}, p{height_percentile:g}={height_cutoff:.2f}",
                            height_rule,
                            height_mean,
                        ),
                        _system_evidence(
                            "div850",
                            div_field,
                            spec["div_signal"],
                            f"mean={div_mean:.2f}, p{div_percentile:g}={div_cutoff:.2f}",
                            div_rule,
                            div_mean,
                        ),
                        _derived_system_evidence(
                            "pressure_center_mask",
                            "pressure center connected area",
                            f"point_count={item['point_count']}, min_points={min_points}",
                            min_points_rule,
                            float(item["point_count"]),
                            source_paths,
                        ),
                        _derived_system_evidence(
                            "pressure_center_mask",
                            "pressure center output rank",
                            f"rank={idx}, max_centers={max_centers}",
                            max_centers_rule,
                            float(idx),
                            source_paths,
                        ),
                    ],
                }
            )
    return systems


def diagnose_systems(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = []
    gh_field = fields["gh500"]
    gh = field_array(gh_field, "gh")
    if gh is None:
        return systems
    lat, lon = gh_field.lat, gh_field.lon

    gh_max = float(np.nanmax(gh))
    height_rule = rules["system.subtropical_high.gh500_dam"] if gh_max < 1000 else rules["system.subtropical_high.gh500_gpm"]
    min_points_rule = rules["system.subtropical_high.min_points"]
    threshold = _rule_float(height_rule, "threshold", 588.0 if gh_max < 1000 else 5880.0)
    min_points = int(_rule_float(min_points_rule, "threshold", 20.0))
    subtropical_feature = None
    if _rule_enabled(height_rule):
        subtropical_mask = largest_component(gh >= threshold, min_points=min_points)
        subtropical_features = mask_to_bbox_features(subtropical_mask, lat, lon, min_points=min_points)
        subtropical_feature = subtropical_features[0] if subtropical_features else None
    if subtropical_feature:
        subtropical_metrics = _subtropical_high_metrics(subtropical_feature, gh, lat, lon, threshold)
        threshold_evidence = _system_evidence(
            "gh500",
            gh_field,
            "height threshold area",
            f"max={gh_max:.2f}, threshold={threshold:g}, min_points={min_points}",
            height_rule,
            gh_max,
        )
        systems.append(
            {
                "id": "system-subtropical-high-500",
                "type": "subtropical_high",
                "feature_type": "subtropical_high",
                "name": "500hPa 副热带高压",
                "level": "500",
                "boundary_smoothed": True,
                "boundary_smooth_km": 90.0,
                "boundary_simplify_km": 30.0,
                "geometry": _polygon_geometry_from_component(
                    subtropical_feature,
                    smooth_boundary=True,
                    boundary_smooth_km=90.0,
                    boundary_simplify_km=30.0,
                ),
                "confidence": round(min(0.9, 0.72 + max(0.0, subtropical_metrics["mean_height"] - threshold) / max(threshold, 1.0) * 4.0), 2),
                "diagnosis": (
                    f"500hPa {threshold:g} 高度区连续成片，西伸脊点位于 "
                    f"{subtropical_metrics['ridge_point']['lon']:.1f}E/{subtropical_metrics['ridge_point']['lat']:.1f}N，"
                    f"北界约 {subtropical_metrics['north_boundary_lat']:.1f}N，"
                    f"主体呈{_axis_orientation_label(subtropical_metrics['axis_orientation'])}分布。"
                ),
                "evidence": [
                    threshold_evidence,
                    *_subtropical_high_evidence(gh_field, subtropical_metrics, min_points_rule),
                ],
                **subtropical_metrics,
            }
        )

    zonal_mean = np.nanmean(gh, axis=1, keepdims=True)
    anomaly = gh - zonal_mean
    diagnostics["gh500_anomaly"] = finite_stats(anomaly)
    vorticity500 = _relative_vorticity_from_wind(fields, diagnostics, "uv500", "vorticity500")
    moisture_flux, flux_divergence = _moisture_flux_from_fields(fields, diagnostics)
    systems.extend(_surface_pressure_center_systems(fields, diagnostics))
    systems.extend(_pressure_center_systems(fields, anomaly, rules))
    systems.extend(_trough_ridge_axis_systems(fields, anomaly, rules, vorticity500=vorticity500))
    systems.extend(_low_level_jet_systems(fields, diagnostics, rules, moisture_flux))
    systems.extend(_moisture_transport_systems(fields, rules, moisture_flux))
    systems.extend(_moisture_convergence_systems(fields, rules, moisture_flux, flux_divergence))
    systems.extend(_low_level_convergence_systems(fields, rules))
    systems.extend(_upper_divergence_systems(fields, rules))
    systems.extend(_front_candidate_systems(fields, diagnostics, rules))
    return _annotate_system_display_metadata(systems)


def _risk_region_from_arrays(
    fields: dict[str, NafpField],
    arrays: list[np.ndarray | None],
    rules: dict[str, dict],
) -> dict[str, Any]:
    base_field = fields["gh500"]
    valid_arrays = [arr for arr in arrays if arr is not None and np.isfinite(arr).any()]
    if not valid_arrays:
        return _fallback_domain_region(base_field)
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
    percentile = _rule_float(rules["region.risk.percentile"], "threshold", 85.0)
    min_points = int(_rule_float(rules["region.risk.min_points"], "threshold", 16.0))
    mask = largest_component(risk >= np.nanpercentile(risk[np.isfinite(risk)], percentile), min_points=min_points)
    features = mask_to_bbox_features(mask, base_field.lat, base_field.lon, min_points=min_points)
    if not features:
        return _fallback_domain_region(base_field)
    return _polygon_geometry_from_component(features[0])


def diagnose_evidence_chains(
    fields: dict[str, NafpField],
    diagnostics: dict[str, Any],
    matrix: dict[str, Any],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    uv850_speed = _add_wind_diagnostic(diagnostics, fields, "uv850", "uv850_speed")
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
    moisture_flux, moisture_flux_divergence = _moisture_flux_from_fields(fields, diagnostics)
    vorticity500 = _relative_vorticity_from_wind(fields, diagnostics, "uv500", "vorticity500")

    chains = [
        _heavy_rain_chain(fields, q850, moisture_flux, div850, w700, kindex, cape, rain6, tcwv, matrix, rules),
        _convection_chain(
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
        ),
        _dynamic_lift_chain(fields, w700, vorticity500, div850, div200, div300, pvadv300, matrix, rules),
        _phase_chain(fields, t2m, tt850, tt925, tw0_height, matrix, rules),
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
    matrix: dict[str, Any],
    rules: dict[str, dict],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0
    rule = rules["heavy_rain.q850"]
    if q850 is not None:
        p75 = float(np.nanpercentile(q850, 75))
        score += _append_rule_evidence(evidence, "q850", fields["q850"], "low-level moisture", f"p75={p75:.2f} g/kg", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "q850")
    rule = rules["heavy_rain.tcwv"]
    if tcwv is not None:
        p75 = float(np.nanpercentile(tcwv, 75))
        score += _append_rule_evidence(evidence, "tcwv", fields["tcwv"], "column water vapor", f"p75={p75:.2f}", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "tcwv")
    rule = rules["heavy_rain.moisture_flux850"]
    if moisture_flux is not None:
        p90 = float(np.nanpercentile(moisture_flux, 90))
        score += _append_rule_evidence(evidence, "moisture_flux850", fields["uv850"], "moisture transport", f"p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "moisture_flux850")
    rule = rules["heavy_rain.div850"]
    if div850 is not None:
        min_div = float(np.nanpercentile(div850, 10))
        score += _append_rule_evidence(evidence, "div850", fields["div850"], "low-level convergence", f"p10={min_div:.2f}", rule, min_div)
    else:
        _append_missing_if_enabled(missing, rule, "div850")
    rule = rules["heavy_rain.w700"]
    if w700 is not None:
        min_w = float(np.nanpercentile(w700, 10))
        score += _append_rule_evidence(evidence, "w700", fields["w700"], "700hPa upward motion", f"p10={min_w:.2f}", rule, min_w)
    else:
        _append_missing_if_enabled(missing, rule, "w700")
    rule = rules["heavy_rain.kindex"]
    if kindex is not None:
        p75 = float(np.nanpercentile(kindex, 75))
        score += _append_rule_evidence(evidence, "kindex", fields["kindex"], "convective instability", f"p75={p75:.2f}", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "kindex")
    rule = rules["heavy_rain.cape"]
    if cape is not None:
        p75 = float(np.nanpercentile(cape, 75))
        score += _append_rule_evidence(evidence, "cape", fields["cape"], "CAPE support", f"p75={p75:.2f} J/kg", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "cape")
    rule = rules["heavy_rain.rain6"]
    if rain6 is not None:
        p90 = float(np.nanpercentile(rain6, 90))
        score += _append_rule_evidence(evidence, "rain6", fields["rain6"], "model 6h precipitation", f"p90={p90:.2f} mm", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "rain6")

    region = _risk_region_from_arrays(fields, [q850, moisture_flux, np.negative(div850) if div850 is not None else None, rain6], rules)
    return {
        "id": "evidence-heavy-rain-potential",
        "target_type": "heavy_rain_potential",
        "level": score_level(score, matrix),
        "region": region,
        "score": round(float(score), 3),
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _convection_chain(
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
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0
    rule = rules["convection.cape"]
    if cape is not None:
        p75 = float(np.nanpercentile(cape, 75))
        score += _append_rule_evidence(evidence, "cape", fields["cape"], "instability energy", f"p75={p75:.2f} J/kg", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "cape")
    rule = rules["convection.cin"]
    if cin is not None:
        p50 = float(np.nanpercentile(cin, 50))
        score += _append_rule_evidence(evidence, "cin", fields["cin"], "inhibition is not excessive", f"p50={p50:.2f} J/kg", rule, p50)
    else:
        _append_missing_if_enabled(missing, rule, "cin")
    rule = rules["convection.kindex"]
    if kindex is not None:
        p75 = float(np.nanpercentile(kindex, 75))
        score += _append_rule_evidence(evidence, "kindex", fields["kindex"], "thermodynamic instability", f"p75={p75:.2f}", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "kindex")
    rule = rules["convection.shr850_200"]
    if shear is not None:
        p75 = float(np.nanpercentile(shear, 75))
        score += _append_rule_evidence(evidence, "shr850-200", fields["shr850-200"], "deep-layer shear", f"p75={p75:.2f}", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "shr850-200")
    rule = rules["convection.q850"]
    if q850 is not None:
        p75 = float(np.nanpercentile(q850, 75))
        score += _append_rule_evidence(evidence, "q850", fields["q850"], "low-level moisture", f"p75={p75:.2f} g/kg", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "q850")
    rule = rules["convection.div850"]
    if div850 is not None:
        p10 = float(np.nanpercentile(div850, 10))
        score += _append_rule_evidence(evidence, "div850", fields["div850"], "low-level trigger", f"p10={p10:.2f}", rule, p10)
    else:
        _append_missing_if_enabled(missing, rule, "div850")
    upper = div200 if div200 is not None else div300
    upper_key = "div200" if div200 is not None else "div300"
    rule = rules["convection.upper_divergence"]
    if upper is not None:
        p90 = float(np.nanpercentile(upper, 90))
        score += _append_rule_evidence(evidence, upper_key, fields[upper_key], "upper-level divergence", f"p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "div200/div300")
    rule = rules["convection.pv300"]
    if pv300 is not None:
        p90 = float(np.nanpercentile(pv300, 90))
        score += _append_rule_evidence(evidence, "pv300", fields["pv300"], "upper-level PV support", f"p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "pv300")
    rule = rules["convection.pvadv300"]
    if pvadv300 is not None:
        p90 = float(np.nanpercentile(np.abs(pvadv300), 90))
        score += _append_rule_evidence(evidence, "pvadv300", fields["pvadv300"], "PV advection support", f"abs_p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "pvadv300")
    rule = rules["convection.li"]
    if li is not None:
        p25 = float(np.nanpercentile(li, 25))
        score += _append_rule_evidence(evidence, "li", fields["li"], "lifted index instability", f"p25={p25:.2f}", rule, p25)
    else:
        _append_missing_if_enabled(missing, rule, "li")
    rule = rules["convection.dcape"]
    if dcape is not None:
        p75 = float(np.nanpercentile(dcape, 75))
        score += _append_rule_evidence(evidence, "dcape", fields["dcape"], "downdraft CAPE", f"p75={p75:.2f} J/kg", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "dcape")
    rule = rules["convection.srh"]
    if srh is not None:
        p75 = float(np.nanpercentile(srh, 75))
        score += _append_rule_evidence(evidence, "srh", fields["srh"], "storm-relative helicity", f"p75={p75:.2f}", rule, p75)
    elif shear01 is not None:
        p75 = float(np.nanpercentile(shear01, 75))
        score += _append_rule_evidence(evidence, "shr0-1km", fields["shr0-1km"], "0-1km shear proxy for low-level rotation", f"p75={p75:.2f}", rule, p75)
    else:
        _append_missing_if_enabled(missing, rule, "srh/shr0-1km")

    region = _risk_region_from_arrays(fields, [cape, shear, q850, np.negative(div850) if div850 is not None else None], rules)
    return {
        "id": "evidence-convection-potential",
        "target_type": "convection_potential",
        "level": score_level(score, matrix),
        "region": region,
        "score": round(float(score), 3),
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _dynamic_lift_chain(
    fields: dict[str, NafpField],
    w700: np.ndarray | None,
    vorticity500: np.ndarray | None,
    div850: np.ndarray | None,
    div200: np.ndarray | None,
    div300: np.ndarray | None,
    pvadv300: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0

    rule = rules["dynamic_lift.w700"]
    if w700 is not None:
        p10 = float(np.nanpercentile(w700, 10))
        score += _append_rule_evidence(evidence, "w700", fields["w700"], "700hPa upward motion", f"p10={p10:.2f}", rule, p10)
    else:
        _append_missing_if_enabled(missing, rule, "w700")

    rule = rules["dynamic_lift.vorticity500"]
    if vorticity500 is not None:
        p90 = float(np.nanpercentile(vorticity500, 90))
        score += _append_rule_evidence(evidence, "vorticity500", fields["uv500"], "500hPa positive vorticity", f"p90={p90:.2f} 10^-5/s", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "vorticity500")

    rule = rules["dynamic_lift.div850"]
    if div850 is not None:
        p10 = float(np.nanpercentile(div850, 10))
        score += _append_rule_evidence(evidence, "div850", fields["div850"], "low-level convergence", f"p10={p10:.2f}", rule, p10)
    else:
        _append_missing_if_enabled(missing, rule, "div850")

    upper = div200 if div200 is not None else div300
    upper_key = "div200" if div200 is not None else "div300"
    rule = rules["dynamic_lift.upper_divergence"]
    if upper is not None:
        p90 = float(np.nanpercentile(upper, 90))
        score += _append_rule_evidence(evidence, upper_key, fields[upper_key], "upper-level divergence", f"p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "div200/div300")

    rule = rules["dynamic_lift.pvadv300"]
    if pvadv300 is not None:
        p90 = float(np.nanpercentile(np.abs(pvadv300), 90))
        score += _append_rule_evidence(evidence, "pvadv300", fields["pvadv300"], "PV advection support", f"abs_p90={p90:.2f}", rule, p90)
    else:
        _append_missing_if_enabled(missing, rule, "pvadv300")

    region = _risk_region_from_arrays(
        fields,
        [
            np.negative(w700) if w700 is not None else None,
            vorticity500,
            np.negative(div850) if div850 is not None else None,
            upper,
        ],
        rules,
    )
    return {
        "id": "evidence-dynamic-lift-potential",
        "target_type": "dynamic_lift_potential",
        "level": score_level(score, matrix),
        "region": region,
        "score": round(float(score), 3),
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


def _phase_label(
    t2m_c: float | None,
    tt850_c: float | None,
    tt925_c: float | None,
    tw0_height: float | None,
) -> tuple[str, str]:
    low_level_values = [value for value in [tt850_c, tt925_c] if value is not None]
    low_level_cold = low_level_values and max(low_level_values) <= 0.0
    low_level_warm = low_level_values and max(low_level_values) > 1.0
    near_surface_cold = t2m_c is not None and t2m_c <= 0.5
    near_surface_marginal = t2m_c is not None and -1.0 <= t2m_c <= 3.0
    low_tw0 = tw0_height is not None and tw0_height <= 600.0

    if low_level_cold and (near_surface_cold or (t2m_c is None and low_tw0)):
        return "snow", "低层温度整体低于冰点，近地面或湿球 0℃ 层支持降雪相态。"
    if near_surface_cold and low_level_warm:
        return "freezing_rain", "近地面接近或低于冰点但低层存在暖层，需警惕冻雨或过冷雨。"
    if near_surface_marginal or low_tw0:
        return "mixed", "近地面或湿球 0℃ 层处于临界范围，雨雪混合或相态转换可能性较高。"
    if t2m_c is None and tt850_c is None and tt925_c is None and tw0_height is None:
        return "unknown", "缺少相态所需温度和湿球层结证据，无法给出可靠初判。"
    return "rain", "低层温度条件整体偏暖，当前初判以降雨相态为主。"


def _phase_chain(
    fields: dict[str, NafpField],
    t2m: np.ndarray | None,
    tt850: np.ndarray | None,
    tt925: np.ndarray | None,
    tw0_height: np.ndarray | None,
    matrix: dict[str, Any],
    rules: dict[str, dict],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0.0

    t2m_value = None
    rule = rules["phase.t2m"]
    if t2m is not None:
        t2m_c = _to_celsius(t2m)
        t2m_value = float(np.nanpercentile(t2m_c, 50))
        score += _append_rule_evidence(evidence, "t2m", fields["t2m"], "2m temperature", f"p50={t2m_value:.2f} degC", rule, t2m_value)
    else:
        _append_missing_if_enabled(missing, rule, "t2m")

    tt850_value = None
    rule = rules["phase.tt850"]
    if tt850 is not None:
        tt850_c = _to_celsius(tt850)
        tt850_value = float(np.nanpercentile(tt850_c, 50))
        score += _append_rule_evidence(evidence, "tt850", fields["tt850"], "850hPa temperature", f"p50={tt850_value:.2f} degC", rule, tt850_value)
    else:
        _append_missing_if_enabled(missing, rule, "tt850")

    tt925_value = None
    rule = rules["phase.tt925"]
    if tt925 is not None:
        tt925_c = _to_celsius(tt925)
        tt925_value = float(np.nanpercentile(tt925_c, 50))
        score += _append_rule_evidence(evidence, "tt925", fields["tt925"], "925hPa temperature", f"p50={tt925_value:.2f} degC", rule, tt925_value)
    else:
        _append_missing_if_enabled(missing, rule, "tt925")

    tw0_value = None
    rule = rules["phase.tw0_height"]
    if tw0_height is not None:
        tw0_value = float(np.nanpercentile(tw0_height, 50))
        score += _append_rule_evidence(evidence, "tw0_height", fields["tw0_height"], "wet-bulb zero height", f"p50={tw0_value:.2f} m", rule, tw0_value)
    else:
        _append_missing_if_enabled(missing, rule, "tw0_height")

    phase_type, diagnosis = _phase_label(t2m_value, tt850_value, tt925_value, tw0_value)
    return {
        "id": "evidence-precipitation-phase",
        "target_type": "precipitation_phase",
        "level": score_level(score, matrix),
        "phase_type": phase_type,
        "diagnosis": diagnosis,
        "score": round(float(score), 3),
        "dominant_evidence": _dominant_evidence(evidence),
        "evidence": evidence,
        "missing_evidence": missing,
    }


SYSTEM_SUMMARY_LABELS = {
    "high": "海平面高压中心",
    "low": "海平面低压中心",
    "subtropical_high": "副高588区",
    "low_pressure_convergence": "低压辐合区",
    "high_pressure_divergence": "高压辐散区",
    "trough_candidate": "500hPa 槽线候选",
    "ridge_candidate": "500hPa 脊线候选",
    "low_level_jet": "850hPa 低空急流",
    "moisture_transport": "850hPa 水汽输送带",
    "moisture_convergence": "850hPa 水汽辐合区",
    "low_level_convergence": "850hPa 低层辐合区",
    "upper_divergence": "200/300hPa 高空辐散区",
    "front_candidate": "锋面候选区",
}

CHAIN_SUMMARY_LABELS = {
    "heavy_rain_potential": "强降水潜势",
    "convection_potential": "强对流潜势",
    "dynamic_lift_potential": "动力抬升潜势",
    "precipitation_phase": "降水相态",
}

LEVEL_SUMMARY_LABELS = {
    "very_high": "很高",
    "high": "高",
    "moderate": "中等",
    "medium": "中等",
    "low": "低",
    "very_low": "很低",
}


NAFP_RISK_CHAIN_HAZARDS = {
    "heavy_rain_potential": [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
    ],
    "convection_potential": [
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ],
}

RISK_SUPPORT_TARGET_TYPES = {
    "persistent_heavy_rain": "heavy_rain_potential",
    "short_duration_heavy_rain": "convection_potential",
    "thunderstorm_gale": "convection_potential",
    "hail": "convection_potential",
    "rotating_storm_or_supercell": "convection_potential",
    "severe_convection_composite": "convection_potential",
}


def _summary_label(labels: dict[str, str], value: str | None) -> str:
    if not value:
        return "未分类对象"
    return labels.get(value, value)


def _prepared_score_grid(layer: dict[str, Any]) -> np.ndarray | None:
    lat = np.asarray(layer["lat"], dtype=float)
    lon = np.asarray(layer["lon"], dtype=float)
    arr = np.asarray(layer["values"], dtype=float).squeeze()
    if arr.ndim != 2:
        return None
    if arr.shape == (lat.size, lon.size):
        return arr
    if arr.shape == (lon.size, lat.size):
        return arr.T
    return None


def _grid_subset_for_bbox(layer: dict[str, Any], bbox: list[float] | tuple[float, ...] | None) -> np.ndarray | None:
    if not bbox or len(bbox) != 4:
        return None
    arr = _prepared_score_grid(layer)
    if arr is None:
        return None
    lon_min, lat_min, lon_max, lat_max = [float(value) for value in bbox]
    lat = np.asarray(layer["lat"], dtype=float)
    lon = np.asarray(layer["lon"], dtype=float)
    lat_mask = (lat >= min(lat_min, lat_max)) & (lat <= max(lat_min, lat_max))
    lon_mask = (lon >= min(lon_min, lon_max)) & (lon <= max(lon_min, lon_max))
    if not lat_mask.any() or not lon_mask.any():
        return None
    subset = arr[np.ix_(lat_mask, lon_mask)]
    if subset.size == 0 or not np.isfinite(subset).any():
        return None
    return subset


def _score_grid_statistic(
    source_grid: str,
    *,
    root: str | Path | None,
    run_time: str | datetime | None,
    forecast_hour: int | None,
    region: dict[str, Any] | None,
    layer_cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if root is None or run_time is None or forecast_hour is None:
        return None
    try:
        layer = layer_cache.get(source_grid)
        if layer is None:
            layer = load_nafp_layer(
                source_grid,
                root=root,
                run_time=parse_run_time(run_time).isoformat(),
                forecast_hour=int(forecast_hour),
            )
            layer_cache[source_grid] = layer
    except Exception as exc:
        return {
            "score_source": "evidence_chain_fallback",
            "score_error": str(exc),
        }

    subset = _grid_subset_for_bbox(layer, (region or {}).get("bbox"))
    statistic = "bbox_max"
    if subset is None:
        subset = _prepared_score_grid(layer)
        statistic = "global_max"
    if subset is None or subset.size == 0 or not np.isfinite(subset).any():
        return None

    valid = subset[np.isfinite(subset)]
    return {
        "score": round(float(np.nanmax(valid)), 3),
        "score_statistic": statistic,
        "score_mean": round(float(np.nanmean(valid)), 3),
        "score_sample_count": int(valid.size),
        "score_source": "source_grid",
    }


def _layer_domain_region(layer: dict[str, Any]) -> dict[str, Any]:
    lat = np.asarray(layer["lat"], dtype=float)
    lon = np.asarray(layer["lon"], dtype=float)
    lon_min = float(np.nanmin(lon))
    lon_max = float(np.nanmax(lon))
    lat_min = float(np.nanmin(lat))
    lat_max = float(np.nanmax(lat))
    return {
        "type": "polygon",
        "bbox": [lon_min, lat_min, lon_max, lat_max],
        "coordinates": [[
            [lon_min, lat_min],
            [lon_max, lat_min],
            [lon_max, lat_max],
            [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
        "geojson_type": "Polygon",
    }


def _risk_region_from_grid(
    layer: dict[str, Any],
    hazard_type: str,
    thresholds: dict[str, Any],
) -> tuple[dict[str, Any], tuple[np.ndarray, np.ndarray] | None]:
    arr = _prepared_score_grid(layer)
    if arr is None or not np.isfinite(arr).any():
        return _layer_domain_region(layer), None

    metadata = hazard_metadata(hazard_type)
    cfg = thresholds.get(metadata["feature_type"], {})
    score_threshold = float(cfg.get("score_threshold", 0.6))
    min_points = max(1, int(cfg.get("min_area_grid_points", 8)))
    max_value = float(np.nanmax(arr))
    threshold = score_threshold if max_value >= score_threshold else max_value
    components = mask_to_bbox_features(arr >= threshold, layer["lat"], layer["lon"], min_points=min_points)
    if not components and min_points > 1:
        components = mask_to_bbox_features(arr >= threshold, layer["lat"], layer["lon"], min_points=1)
    if not components:
        components = mask_to_bbox_features(arr >= max_value, layer["lat"], layer["lon"], min_points=1)
    if not components:
        return _layer_domain_region(layer), None
    components.sort(
        key=lambda item: (
            float(np.nanmax(arr[item["indices"]])),
            float(np.nanmean(arr[item["indices"]])),
            item["point_count"],
        ),
        reverse=True,
    )
    item = components[0]
    return _polygon_geometry_from_component(item), item["indices"]


def _risk_factor_dominance(
    factor_details: dict[str, Any] | None,
    indices: tuple[np.ndarray, np.ndarray] | None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not factor_details or indices is None:
        return []
    ys, xs = indices
    out = []
    for factor, detail in factor_details.items():
        contribution_grid = detail.get("contribution")
        if contribution_grid is None:
            continue
        contribution = np.asarray(contribution_grid, dtype=float)[ys, xs]
        if contribution.size == 0 or not np.isfinite(contribution).any():
            continue
        mean_contribution = float(np.nanmean(contribution))
        if mean_contribution <= 0:
            continue
        score_grid = detail.get("score", contribution_grid)
        score = np.asarray(score_grid, dtype=float)[ys, xs]
        out.append(
            {
                "factor": factor,
                "field": detail.get("field", factor),
                "label": detail.get("label", factor),
                "weight": float(detail.get("weight", 0.0)),
                "mean_score": round(float(np.nanmean(score)), 3),
                "mean_contribution": round(mean_contribution, 3),
            }
        )
    out.sort(key=lambda item: item["mean_contribution"], reverse=True)
    return out[:limit]


def risk_diagnoses_from_grids(
    *,
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
    systems: list[dict[str, Any]] | None = None,
    threshold_matrix: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    layer_cache: dict[str, dict[str, Any]] = {}
    thresholds = load_thresholds()
    rt = parse_run_time(run_time).isoformat()
    try:
        details, _lat, _lon, source_paths = nafp_multi_hazard_score_details(Path(root), rt, int(forecast_hour))
    except (FileNotFoundError, KeyError, ValueError):
        return []
    diagnoses = []
    for hazard_type in HAZARD_TYPES:
        metadata = hazard_metadata(hazard_type)
        source_grid = risk_grid_for_hazard(hazard_type)
        try:
            layer = load_nafp_layer(source_grid, root=root, run_time=rt, forecast_hour=int(forecast_hour))
        except Exception as exc:
            diagnoses.append(
                {
                    "risk_id": f"risk-{hazard_type}",
                    "hazard_type": hazard_type,
                    "risk_domain": metadata["risk_domain"],
                    "label": metadata["label"],
                    "mechanism_tags": metadata["mechanism_tags"],
                    "source_grid": source_grid,
                    "score": 0.0,
                    "risk_level": "low",
                    "level": "low",
                    "score_source": "source_grid",
                    "score_error": str(exc),
                    "source_chain_ids": [],
                    "dominant_evidence": [],
                    "source_paths": source_paths,
                }
            )
            continue
        layer_cache[source_grid] = layer
        region, indices = _risk_region_from_grid(layer, hazard_type, thresholds)
        score_info = _score_grid_statistic(
            source_grid,
            root=root,
            run_time=rt,
            forecast_hour=forecast_hour,
            region=region,
            layer_cache=layer_cache,
        ) or {"score": 0.0, "score_source": "source_grid"}
        score = float(score_info.get("score") or 0.0)
        level = score_level(score, threshold_matrix or load_threshold_matrix())
        factors = (details.get("factors") or {}).get(source_grid, {})
        quality = (details.get("quality") or {}).get(source_grid, {})
        item = {
            "risk_id": f"risk-{hazard_type}",
            "hazard_type": hazard_type,
            "risk_domain": metadata["risk_domain"],
            "label": metadata["label"],
            "mechanism_tags": metadata["mechanism_tags"],
            "source_grid": source_grid,
            "feature_type": metadata["feature_type"],
            "risk_level": level,
            "level": level,
            "score": score,
            "source_chain_ids": [],
            "region": region,
            "region_source": "source_grid",
            "dominant_evidence": _risk_factor_dominance(factors, indices),
            "input_completeness": quality.get("input_completeness"),
            "missing_critical_factors": list(quality.get("missing_critical_factors") or []),
            "score_cap_applied": bool(quality.get("score_cap_applied", False)),
            "score_cap_value": quality.get("score_cap_value"),
            "source_paths": layer.get("source_paths") or source_paths,
        }
        item.update(score_info)
        support_target = RISK_SUPPORT_TARGET_TYPES.get(hazard_type, "convection_potential")
        links = supporting_system_links(region, systems or [], target_type=support_target) if region else []
        if links:
            item["supporting_systems"] = links
        diagnoses.append(item)
    return diagnoses


def risk_diagnoses_from_chains(
    evidence_chains: list[dict[str, Any]],
    *,
    root: str | Path | None = None,
    run_time: str | datetime | None = None,
    forecast_hour: int | None = None,
    threshold_matrix: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    chains = {chain.get("target_type"): chain for chain in evidence_chains}
    layer_cache: dict[str, dict[str, Any]] = {}
    diagnoses = []
    for source_target, hazard_types in NAFP_RISK_CHAIN_HAZARDS.items():
        chain = chains.get(source_target)
        if not chain:
            continue
        for hazard_type in hazard_types:
            metadata = hazard_metadata(hazard_type)
            source_grid = risk_grid_for_hazard(hazard_type)
            score_info = _score_grid_statistic(
                source_grid,
                root=root,
                run_time=run_time,
                forecast_hour=forecast_hour,
                region=chain.get("region"),
                layer_cache=layer_cache,
            )
            score = chain.get("score")
            level = chain.get("level")
            if score_info and "score" in score_info:
                score = score_info["score"]
                level = score_level(float(score), threshold_matrix or load_threshold_matrix())
            item = {
                "risk_id": f"risk-{hazard_type}",
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
            }
            if score_info:
                item.update(score_info)
            if chain.get("region") is not None:
                item["region"] = chain["region"]
            supporting_systems = chain.get("supporting_systems") or chain.get("linked_systems")
            if supporting_systems:
                item["supporting_systems"] = supporting_systems
            diagnoses.append(item)
    return diagnoses


def build_summary(
    systems: list[dict[str, Any]],
    evidence_chains: list[dict[str, Any]],
    risk_diagnoses: list[dict[str, Any]],
    missing: list[dict[str, Any]],
) -> str:
    parts = []
    if systems:
        counts: dict[str, int] = {}
        for system in systems:
            counts[system["type"]] = counts.get(system["type"], 0) + 1
        parts.append(
            "天气形势识别到"
            + "、".join(f"{_summary_label(SYSTEM_SUMMARY_LABELS, key)} {value} 个" for key, value in counts.items())
            + "。"
        )
    else:
        parts.append("天气形势暂未识别到稳定的大尺度系统。")
    if risk_diagnoses:
        risk_text = "、".join(
            f"{risk.get('label') or risk.get('hazard_type')}为{_summary_label(LEVEL_SUMMARY_LABELS, risk.get('risk_level') or risk.get('level'))}，评分 {float(risk.get('score') or 0.0):.2f}"
            for risk in risk_diagnoses
        )
        parts.append(f"风险诊断：{risk_text}。")
    else:
        for chain in evidence_chains:
            target = _summary_label(CHAIN_SUMMARY_LABELS, chain.get("target_type"))
            level = _summary_label(LEVEL_SUMMARY_LABELS, chain.get("level"))
            parts.append(f"{target}为{level}，评分 {chain['score']:.2f}。")
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
    threshold_matrix = load_threshold_matrix()
    rules = threshold_entries_by_id(threshold_matrix)
    diagnostics = {"gh500": {**finite_stats(gh), "source_path": fields["gh500"].source_path}}
    systems = diagnose_systems(fields, diagnostics, rules)
    evidence_chains = diagnose_evidence_chains(fields, diagnostics, threshold_matrix, rules)
    evidence_chains = attach_chain_supporting_systems(evidence_chains, systems)
    diagnosis_conclusions = conclusions_from_chains(evidence_chains)
    risk_diagnoses = risk_diagnoses_from_grids(
        root=root,
        run_time=rt,
        forecast_hour=forecast_hour,
        systems=systems,
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
        "domain": {
            "lat_min": float(lat.min()),
            "lat_max": float(lat.max()),
            "lon_min": float(lon.min()),
            "lon_max": float(lon.max()),
        },
        "systems": systems,
        "diagnostics": diagnostics,
        "evidence_chains": evidence_chains,
        "diagnosis_conclusions": diagnosis_conclusions,
        "risk_diagnoses": risk_diagnoses,
        "missing_fields": missing,
        "summary": build_summary(systems, evidence_chains, risk_diagnoses, missing),
    }
