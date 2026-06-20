from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from weather_diag.data.nafp import NAFP_SAMPLE_ROOT, NafpField, load_nafp_field, parse_run_time
from weather_diag.diagnosis.algorithm_rules import (
    load_threshold_matrix,
    score_level as matrix_score_level,
    threshold_entries_by_id,
)
from weather_diag.diagnosis.conclusions import conclusions_from_chains
from weather_diag.diagnosis.nafp_layers import load_nafp_layer
from weather_diag.diagnosis.risk_taxonomy import hazard_metadata, risk_grid_for_hazard
from weather_diag.diagnosis.system_links import attach_chain_supporting_systems
from weather_diag.diagnostics.grid import component_axis_line, derivatives_lonlat, mask_to_bbox_features
from weather_diag.features.convergence import ranked_mask_items, smooth_field
from weather_diag.features.front import front_candidate_fields
from weather_diag.features.transport_objects import ranked_transport_components
from weather_diag.features.trough_ridge import trough_ridge_axis_candidates


DEFAULT_OPTIONAL_FIELDS = [
    ("uv", "500", "uv500"),
    ("uv", "850", "uv850"),
    ("q", "850", "q850"),
    ("rh", "850", "rh850"),
    ("div", "850", "div850"),
    ("tt", "850", "tt850"),
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
    ("uv", "925", "uv925"),
    ("rh", "700", "rh700"),
    ("tt", "925", "tt925"),
    ("li", "999", "li"),
    ("si", "999", "si"),
    ("bli", "999", "bli"),
    ("dcape", "999", "dcape"),
    ("srh", "999", "srh"),
    ("shr0-1", "999", "shr0-1km"),
    ("t2m", "999", "t2m"),
    ("tw0", "999", "tw0_height"),
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


def _polygon_geometry_from_component(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "polygon",
        "bbox": item["bbox"],
        "coordinates": item["geometry"]["coordinates"],
        "geojson_type": item["geometry"]["type"],
    }


def _line_geometry_from_component(item: dict[str, Any], lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    return component_axis_line(item, lat, lon)


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
    if fields["uv850"].exists:
        source_paths.append(fields["uv850"].source_path)
    if fields["div850"].exists:
        source_paths.append(fields["div850"].source_path)
    if fields["ttadv850"].exists:
        source_paths.append(fields["ttadv850"].source_path)
    if fields["rh850"].exists:
        source_paths.append(fields["rh850"].source_path)

    systems = []
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    front_items = mask_to_bbox_features(derived["mask"], tt_field.lat, tt_field.lon, min_points=min_points)
    front_items.sort(
        key=lambda candidate: (
            candidate["point_count"],
            float(np.nanmean(derived["score"][candidate["indices"]])) if candidate["point_count"] else 0.0,
        ),
        reverse=True,
    )
    for idx, item in enumerate(front_items[:max_objects], start=1):
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
                "front candidate connected area",
                f"point_count={item['point_count']}, min_points={min_points}",
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
                "name": "850hPa front candidate area",
                "level": "850",
                "geometry": _polygon_geometry_from_component(item),
                "confidence": 0.66 if wind850 is not None else 0.58,
                "diagnosis": "850hPa 温度梯度、风场形变、锋生函数、低层辐合和温度平流综合识别锋面候选区。",
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
    threshold = float(np.nanpercentile(smoothed_div850, percentile))
    min_points = int(_rule_float(min_points_rule, "threshold", 10.0))
    max_objects = max(1, int(_rule_float(max_objects_rule, "threshold", 12.0)))
    mask = smoothed_div850 <= threshold
    wind850 = _wind_components(fields, "uv850")
    source_paths = [fields["div850"].source_path]
    if wind850 is not None:
        u850, v850 = wind850
        dudx, _ = derivatives_lonlat(u850, fields["uv850"].lat, fields["uv850"].lon)
        _, dvdy = derivatives_lonlat(v850, fields["uv850"].lat, fields["uv850"].lon)
        vector_div850 = smooth_field((dudx + dvdy) * 100000.0, sigma)
        mask &= vector_div850 <= 0
        source_paths.append(fields["uv850"].source_path)
    systems = []
    items = ranked_mask_items(
        mask,
        fields["div850"].lat,
        fields["div850"].lon,
        min_points=min_points,
        max_objects=max_objects,
        primary_value=smoothed_div850,
        descending=False,
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
                "confidence": 0.68 if wind850 is not None else 0.62,
                "diagnosis": "850hPa 低层辐合区：平滑后散度低值且风场散度符号一致，提示主要低层汇聚抬升区。",
                "evidence": [
                    _system_evidence(
                        "div850",
                        fields["div850"],
                        "smoothed low-level convergence percentile",
                        f"smoothed_mean={mean_div:.2f}, raw_mean={raw_mean_div:.2f}, p{percentile:g}={threshold:.2f}",
                        div_rule,
                        mean_div,
                    ),
                    _derived_system_evidence(
                        "div850_smoothed",
                        "low-level convergence smoothing scale",
                        f"sigma_grid={sigma:g}",
                        smooth_rule,
                        sigma,
                        source_paths,
                    ),
                    _derived_system_evidence(
                        "div850",
                        "low-level convergence connected area",
                        f"point_count={item['point_count']}, min_points={min_points}",
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
        threshold = float(np.nanpercentile(smoothed_div, percentile))
        mask = smoothed_div >= threshold
        for item in mask_to_bbox_features(mask, fields[key].lat, fields[key].lon, min_points=min_points):
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
                    "mean_div": float(np.nanmean(smoothed_div[ys, xs])),
                    "raw_mean_div": float(np.nanmean(div[ys, xs])),
                    "point_count": item["point_count"],
                }
            )
    candidates.sort(key=lambda candidate: (candidate["point_count"], candidate["mean_div"]), reverse=True)
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
                "confidence": 0.66,
                "diagnosis": f"{level}hPa 高空辐散区：平滑后高空正散度高值，有利于下方补偿上升。",
                "evidence": [
                    _system_evidence(
                        key,
                        field,
                        "smoothed upper-level divergence percentile",
                        f"smoothed_mean={mean_div:.2f}, raw_mean={raw_mean_div:.2f}, p{percentile:g}={threshold:.2f}",
                        div_rule,
                        mean_div,
                    ),
                    _derived_system_evidence(
                        f"{key}_smoothed",
                        "upper-level divergence smoothing scale",
                        f"sigma_grid={sigma:g}",
                        smooth_rule,
                        sigma,
                        [field.source_path],
                    ),
                    _derived_system_evidence(
                        key,
                        "upper-level divergence connected area",
                        f"point_count={item['point_count']}, min_points={min_points}",
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
                        "bbox": candidate["bbox"],
                    },
                    "confidence": 0.68 if candidate["method"] == "curvature_component_axis" else 0.56,
                    "diagnosis": f"500hPa 位势高度距平尾部、等高线曲率和涡度符号支撑共同识别{label}轴线。",
                    "method": candidate["method"],
                    "evidence": evidence,
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
        systems.append(
            {
                "id": "system-subtropical-high-500",
                "type": "subtropical_high",
                "feature_type": "subtropical_high",
                "name": "500hPa subtropical high area",
                "level": "500",
                "geometry": _polygon_geometry_from_component(subtropical_feature),
                "confidence": 0.78,
                "diagnosis": f"500hPa height field has a contiguous area above {threshold:g}.",
                "evidence": [
                    _system_evidence(
                        "gh500",
                        gh_field,
                        "height threshold area",
                        f"max={gh_max:.2f}, threshold={threshold:g}, min_points={min_points}",
                        height_rule,
                        gh_max,
                    )
                ],
            }
        )

    zonal_mean = np.nanmean(gh, axis=1, keepdims=True)
    anomaly = gh - zonal_mean
    diagnostics["gh500_anomaly"] = finite_stats(anomaly)
    vorticity500 = _relative_vorticity_from_wind(fields, diagnostics, "uv500", "vorticity500")
    moisture_flux, flux_divergence = _moisture_flux_from_fields(fields, diagnostics)
    systems.extend(_pressure_center_systems(fields, anomaly, rules))
    systems.extend(_trough_ridge_axis_systems(fields, anomaly, rules, vorticity500=vorticity500))
    trough_rule = rules["system.trough_candidate.anomaly_percentile"]
    ridge_rule = rules["system.ridge_candidate.anomaly_percentile"]
    trough_percentile = _rule_float(trough_rule, "threshold", 8.0)
    ridge_percentile = _rule_float(ridge_rule, "threshold", 92.0)
    trough_value = float(np.nanpercentile(anomaly, trough_percentile))
    ridge_value = float(np.nanpercentile(anomaly, ridge_percentile))
    component_min_points = int(_rule_float(rules["system.trough_ridge.min_points"], "threshold", 24.0))
    for system_type, rule, mask, confidence, threshold_value in [
        ("trough_candidate", trough_rule, anomaly <= trough_value, 0.52, trough_value),
        ("ridge_candidate", ridge_rule, anomaly >= ridge_value, 0.52, ridge_value),
    ]:
        if not _rule_enabled(rule):
            continue
        component = largest_component(mask, min_points=component_min_points)
        component_features = mask_to_bbox_features(component, lat, lon, min_points=component_min_points)
        if component_features:
            component_feature = component_features[0]
            systems.append(
                {
                    "id": f"system-{system_type}-500",
                    "type": system_type,
                    "feature_type": system_type,
                    "name": f"500hPa {system_type.replace('_', ' ')}",
                    "level": "500",
                    "geometry": _polygon_geometry_from_component(component_feature),
                    "confidence": confidence,
                    "diagnosis": "500hPa height anomaly identifies a candidate synoptic feature.",
                    "evidence": [
                        _system_evidence(
                            "gh500",
                            gh_field,
                            "height anomaly",
                            f"threshold={threshold_value:.2f}, min_points={component_min_points}",
                            rule,
                            threshold_value,
                        )
                    ],
                }
            )
    systems.extend(_low_level_jet_systems(fields, diagnostics, rules, moisture_flux))
    systems.extend(_moisture_transport_systems(fields, rules, moisture_flux))
    systems.extend(_moisture_convergence_systems(fields, rules, moisture_flux, flux_divergence))
    systems.extend(_low_level_convergence_systems(fields, rules))
    systems.extend(_upper_divergence_systems(fields, rules))
    systems.extend(_front_candidate_systems(fields, diagnostics, rules))
    return systems


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
    "high": "高",
    "moderate": "中等",
    "low": "低",
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


def build_summary(systems: list[dict[str, Any]], evidence_chains: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
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
    risk_diagnoses = risk_diagnoses_from_chains(
        evidence_chains,
        root=root,
        run_time=rt,
        forecast_hour=forecast_hour,
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
        "summary": build_summary(systems, evidence_chains, missing),
    }
