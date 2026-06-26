from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from weather_diag.config import load_thresholds
from weather_diag.data.nafp import NafpField, load_nafp_field, parse_run_time
from weather_diag.diagnosis import nafp_situation as base
from weather_diag.diagnosis.conclusions import conclusions_from_chains
from weather_diag.diagnosis.system_links import attach_chain_supporting_systems
from weather_diag.diagnostics.grid import geometry_bounds
from weather_diag.features.convergence import detect_low_level_convergence_axes, detect_upper_divergence_axes
from weather_diag.features.pv_anomaly import detect_pv_anomaly
from weather_diag.features.shear_line import detect_shear_lines
from weather_diag.features.surface_boundary import detect_surface_boundaries
from weather_diag.features.upper_jet import detect_jet_exit_regions, detect_upper_jet
from weather_diag.features.vortex import detect_cold_vortex

INTEGRATION_VERSION = "weather_system_integration_20260625"

NEW_PRIMARY_LIMITS = {
    "shear_line": 3,
    "front_with_shear": 2,
    "low_level_convergence_axis": 3,
    "upper_divergence_axis": 3,
    "cold_vortex": 3,
    "mid_level_vortex": 3,
    "upper_jet": 2,
    "upper_jet_exit_region": 2,
    "pv_anomaly": 2,
    "surface_front_candidate": 2,
    "dryline_candidate": 2,
}

NEW_DISPLAY_PRIORITY = {
    "cold_vortex": 22,
    "mid_level_vortex": 23,
    "shear_line": 48,
    "front_with_shear": 49,
    "low_level_convergence_axis": 58,
    "upper_divergence_axis": 59,
    "upper_jet": 65,
    "upper_jet_exit_region": 66,
    "pv_anomaly": 67,
    "surface_front_candidate": 68,
    "dryline_candidate": 69,
}

NEW_SUMMARY_LABELS = {
    "shear_line": "切变线",
    "front_with_shear": "锋区切变线",
    "low_level_convergence_axis": "低层辐合轴",
    "upper_divergence_axis": "高空辐散轴",
    "cold_vortex": "冷涡候选",
    "mid_level_vortex": "低涡候选",
    "upper_jet": "高空急流轴",
    "upper_jet_exit_region": "急流出口辐散区",
    "pv_anomaly": "高空PV异常区",
    "surface_front_candidate": "地面锋区候选",
    "dryline_candidate": "地面干线候选",
}

DYNAMIC_TYPES = set(NEW_PRIMARY_LIMITS)


def _patch_display_metadata() -> None:
    base.PRIMARY_SYSTEM_LIMITS.update(NEW_PRIMARY_LIMITS)
    base.SYSTEM_DISPLAY_PRIORITY.update(NEW_DISPLAY_PRIORITY)
    base.SYSTEM_SUMMARY_LABELS.update(NEW_SUMMARY_LABELS)
    base.DYNAMIC_CONFIDENCE_SYSTEM_TYPES.update(DYNAMIC_TYPES)


def _load_extra_field(
    fields: dict[str, NafpField],
    root: str | Path,
    run_time: datetime,
    forecast_hour: int,
    element: str,
    level: str,
    key: str,
) -> None:
    if key in fields:
        return
    fields[key] = load_nafp_field(root, element, level, run_time, forecast_hour, required=False)


def _load_extra_fields(
    fields: dict[str, NafpField],
    root: str | Path,
    run_time: datetime,
    forecast_hour: int,
) -> None:
    for element, level, key in [
        ("uv", "700", "uv700"),
        ("uv", "300", "uv300"),
        ("uv", "200", "uv200"),
        ("gh", "850", "gh850"),
    ]:
        _load_extra_field(fields, root, run_time, forecast_hour, element, level, key)


def _field_array(fields: dict[str, NafpField], key: str, preferred: str | None = None) -> np.ndarray | None:
    field = fields.get(key)
    if field is None:
        return None
    return base.field_array(field, preferred)


def _wind(fields: dict[str, NafpField], key: str) -> tuple[np.ndarray, np.ndarray] | None:
    field = fields.get(key)
    if field is None or not field.exists or "u" not in field.values or "v" not in field.values:
        return None
    return field.values["u"], field.values["v"]


def _bbox_from_coords(coords: list[list[float]]) -> list[float]:
    arr = np.asarray(coords, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [float(np.nanmin(arr[:, 0])), float(np.nanmin(arr[:, 1])), float(np.nanmax(arr[:, 0])), float(np.nanmax(arr[:, 1]))]


def _geojson_to_system_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    kind = geometry.get("type")
    if kind == "LineString":
        coords = geometry.get("coordinates") or []
        return {"type": "line", "coordinates": coords, "bbox": _bbox_from_coords(coords)}
    if kind in {"Polygon", "MultiPolygon"}:
        return {
            "type": "polygon",
            "geojson_type": kind,
            "coordinates": geometry.get("coordinates") or [],
            "bbox": geometry_bounds(geometry),
        }
    if kind == "Point":
        coords = geometry.get("coordinates") or []
        bbox = [float(coords[0]), float(coords[1]), float(coords[0]), float(coords[1])] if len(coords) >= 2 else None
        return {"type": "point", "coordinates": coords, "bbox": bbox}
    return dict(geometry)


def _supporting_role(feature_type: str) -> str:
    if feature_type in {"shear_line", "front_with_shear", "surface_front_candidate", "dryline_candidate", "low_level_convergence_axis"}:
        return "trigger"
    if feature_type in {"upper_jet", "upper_jet_exit_region", "upper_divergence_axis", "pv_anomaly"}:
        return "upper_support"
    if feature_type in {"cold_vortex", "mid_level_vortex"}:
        return "synoptic_control"
    return "supporting_diagnosis"


def _system_evidence(items: Any) -> list[dict[str, Any]]:
    if isinstance(items, str):
        items = [items]
    evidence = []
    for index, item in enumerate(items or [], start=1):
        if isinstance(item, dict):
            evidence.append(item)
        else:
            evidence.append({"signal": str(item), "value": "", "raw_value": 0.0, "rank": index})
    return evidence


def _feature_to_system(feature: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not feature or feature.get("type") != "Feature":
        return None
    geometry = feature.get("geometry") or {}
    props = dict(feature.get("properties") or {})
    feature_type = str(props.get("feature_type") or "weather_system")
    source_id = str(props.get("id") or f"{feature_type}_{index:03d}")
    system: dict[str, Any] = {
        "id": f"system-{source_id}",
        "type": feature_type,
        "feature_type": feature_type,
        "name": props.get("title") or feature_type,
        "title": props.get("title") or feature_type,
        "level": str(props.get("level") or ""),
        "geometry": _geojson_to_system_geometry(geometry),
        "confidence": float(props.get("confidence") or 0.6),
        "diagnosis": props.get("classification_reason") or props.get("title") or feature_type,
        "evidence": _system_evidence(props.get("evidence")),
        "supporting_role": _supporting_role(feature_type),
        "source_algorithm": "nafp_integrated_weather_systems",
    }
    for key, value in props.items():
        if key not in system and key not in {"id", "evidence"}:
            system[key] = value
    return system


def _append_feature_systems(systems: list[dict[str, Any]], features: list[dict[str, Any]]) -> None:
    for feature in features:
        system = _feature_to_system(feature, len(systems) + 1)
        if system is not None:
            systems.append(system)


def _safe_call(warnings: list[str], label: str, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        warnings.append(f"{label}: {exc}")
        return []


def _integrated_feature_systems(
    fields: dict[str, NafpField],
    root: str | Path,
    run_time: datetime,
    forecast_hour: int,
    thresholds: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    _load_extra_fields(fields, root, run_time, forecast_hour)
    systems: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1) Shear lines: prefer 850, then 700/500 when wind fields are present.
    for level, wind_key, temp_key, moisture_key in [
        (850, "uv850", "tt850", "q850"),
        (700, "uv700", "tt700", "rh700"),
        (500, "uv500", "tt500", "rh500"),
    ]:
        wind = _wind(fields, wind_key)
        if wind is None:
            continue
        u, v = wind
        field = fields[wind_key]
        features = _safe_call(
            warnings,
            f"shear_line_{level}",
            detect_shear_lines,
            u,
            v,
            field.lat,
            field.lon,
            thresholds,
            level=level,
            temperature=_field_array(fields, temp_key, "tt"),
            moisture=_field_array(fields, moisture_key, "q" if moisture_key == "q850" else "rh"),
        )
        _append_feature_systems(systems, features)

    # 2) Low-level convergence and upper-divergence axes.
    div850 = _field_array(fields, "div850", "div")
    if div850 is not None:
        wind850 = _wind(fields, "uv850")
        u850, v850 = wind850 if wind850 is not None else (None, None)
        features = _safe_call(
            warnings,
            "low_level_convergence_axis",
            detect_low_level_convergence_axes,
            div850,
            fields["div850"].lat,
            fields["div850"].lon,
            thresholds,
            u850=u850,
            v850=v850,
        )
        _append_feature_systems(systems, features)

    for level, div_key, wind_key in [(200, "div200", "uv200"), (300, "div300", "uv300")]:
        div = _field_array(fields, div_key, "div")
        if div is None:
            continue
        wind = _wind(fields, wind_key)
        u, v = wind if wind is not None else (None, None)
        features = _safe_call(
            warnings,
            f"upper_divergence_axis_{level}",
            detect_upper_divergence_axes,
            div,
            fields[div_key].lat,
            fields[div_key].lon,
            thresholds,
            level,
            u_upper=u,
            v_upper=v,
        )
        _append_feature_systems(systems, features)

    # 3) Vortex / cold vortex candidates.
    for level, gh_key, wind_key, temp_key in [(500, "gh500", "uv500", "tt500"), (700, "gh700", "uv700", "tt700"), (850, "gh850", "uv850", "tt850")]:
        height = _field_array(fields, gh_key, "gh")
        if height is None:
            continue
        wind = _wind(fields, wind_key)
        u, v = wind if wind is not None else (None, None)
        features = _safe_call(
            warnings,
            f"vortex_{level}",
            detect_cold_vortex,
            height,
            fields[gh_key].lat,
            fields[gh_key].lon,
            thresholds,
            u=u,
            v=v,
            temperature=_field_array(fields, temp_key, "tt"),
            level=level,
        )
        _append_feature_systems(systems, features)

    # 4) Upper jets and exit regions.
    upper_jet_features: list[dict[str, Any]] = []
    for level, wind_key, div_key in [(200, "uv200", "div200"), (300, "uv300", "div300")]:
        wind = _wind(fields, wind_key)
        if wind is None:
            continue
        u, v = wind
        divergence = _field_array(fields, div_key, "div")
        features = _safe_call(
            warnings,
            f"upper_jet_{level}",
            detect_upper_jet,
            u,
            v,
            fields[wind_key].lat,
            fields[wind_key].lon,
            thresholds,
            level=level,
            divergence_field=divergence,
        )
        upper_jet_features.extend(features)
        _append_feature_systems(systems, features)
        if divergence is not None and features:
            exit_features = _safe_call(
                warnings,
                f"upper_jet_exit_{level}",
                detect_jet_exit_regions,
                features,
                divergence,
                fields[div_key].lat,
                fields[div_key].lon,
                thresholds,
                level=level,
            )
            _append_feature_systems(systems, exit_features)

    # 5) PV anomaly / dry intrusion support.
    pv300 = _field_array(fields, "pv300", "pv")
    if pv300 is not None:
        features = _safe_call(
            warnings,
            "pv_anomaly_300",
            detect_pv_anomaly,
            pv300,
            fields["pv300"].lat,
            fields["pv300"].lon,
            thresholds,
            level=300,
            pv_advection=_field_array(fields, "pvadv300", "pvadv"),
            rh_mid=_field_array(fields, "rh500", "rh"),
        )
        _append_feature_systems(systems, features)

    # 6) Surface boundary / dryline candidates.
    t2m = _field_array(fields, "t2m", "t2m")
    if t2m is not None:
        u10 = _field_array(fields, "u10", "10u")
        v10 = _field_array(fields, "v10", "10v")
        features = _safe_call(
            warnings,
            "surface_boundary",
            detect_surface_boundaries,
            t2m,
            _field_array(fields, "td2m", "td2"),
            u10,
            v10,
            fields["t2m"].lat,
            fields["t2m"].lon,
            thresholds,
        )
        _append_feature_systems(systems, features)

    return systems, warnings


def _deduplicate_systems(systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for system in systems:
        key = str(system.get("id") or "")
        if not key:
            key = f"{system.get('type')}:{system.get('name')}:{system.get('level')}:{len(out)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(system)
    return out


def extend_nafp_situation_result(
    result: dict[str, Any],
    *,
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
) -> dict[str, Any]:
    if (result.get("weather_system_integration") or {}).get("version") == INTEGRATION_VERSION:
        return result

    _patch_display_metadata()
    out = deepcopy(result)
    rt = parse_run_time(run_time)
    thresholds = load_thresholds()
    fields, _missing = base.load_field_bundle(root, rt, int(forecast_hour))
    extra_systems, warnings = _integrated_feature_systems(fields, root, rt, int(forecast_hour), thresholds)

    systems = _deduplicate_systems(list(out.get("systems") or []) + extra_systems)
    systems = base._annotate_system_display_metadata(systems)
    out["systems"] = systems

    evidence_chains = list(out.get("evidence_chains") or [])
    if evidence_chains:
        evidence_chains = attach_chain_supporting_systems(evidence_chains, systems)
        out["evidence_chains"] = evidence_chains
        out["diagnosis_conclusions"] = conclusions_from_chains(evidence_chains)

    try:
        threshold_matrix = base.load_threshold_matrix()
        out["risk_diagnoses"] = base.risk_diagnoses_from_grids(
            root=root,
            run_time=rt,
            forecast_hour=int(forecast_hour),
            systems=systems,
            threshold_matrix=threshold_matrix,
        )
    except Exception as exc:
        warnings.append(f"risk_relink: {exc}")

    out["weather_system_integration"] = {
        "version": INTEGRATION_VERSION,
        "added_system_count": len(extra_systems),
        "warnings": warnings,
        "enabled_feature_types": sorted({str(item.get("type")) for item in extra_systems}),
    }
    out["summary"] = base.build_summary(systems, out.get("evidence_chains") or [], out.get("risk_diagnoses") or [], out.get("missing_fields") or [])
    return out


def diagnose_nafp_situation(
    root: str | Path = base.NAFP_SAMPLE_ROOT,
    run_time: str | datetime = "2026-06-17T20:00:00",
    forecast_hour: int = 24,
) -> dict[str, Any]:
    result = base.diagnose_nafp_situation(root=root, run_time=run_time, forecast_hour=forecast_hour)
    return extend_nafp_situation_result(result, root=root, run_time=run_time, forecast_hour=forecast_hour)
