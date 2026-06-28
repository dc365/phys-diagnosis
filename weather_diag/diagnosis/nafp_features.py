from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from weather_diag.diagnosis.risk_taxonomy import feature_type_for_hazard


FEATURE_TYPE_ALIASES = {
    "trough": {"trough_candidate"},
    "ridge": {"ridge_candidate"},
}
BACKGROUND_SUPPORT_SYSTEM_TYPES = {"low_level_convergence_axis", "upper_divergence_axis"}


def parse_feature_types(value: str | None) -> list[str] | None:
    if not value:
        return None
    types = [item.strip() for item in value.split(",") if item.strip()]
    return types or None


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _requested_sources(requested_types: Iterable[str] | None) -> set[str] | None:
    if requested_types is None:
        return None
    sources: set[str] = set()
    for feature_type in requested_types:
        sources.add(feature_type)
        sources.update(FEATURE_TYPE_ALIASES.get(feature_type, set()))
    return sources


def _public_feature_type(source_type: str) -> str:
    for public_type, source_types in FEATURE_TYPE_ALIASES.items():
        if source_type in source_types:
            return public_type
    return source_type


def _support_system_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type") or item.get("feature_type") or "")
    return ""


def _system_geometry_to_geojson(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not geometry:
        return None
    kind = geometry.get("type")
    if kind == "polygon":
        return {
            "type": geometry.get("geojson_type") or "Polygon",
            "coordinates": _json_safe(geometry.get("coordinates") or []),
        }
    if kind == "line":
        return {
            "type": "LineString",
            "coordinates": _json_safe(geometry.get("coordinates") or []),
        }
    if kind == "point":
        return {
            "type": "Point",
            "coordinates": _json_safe(geometry.get("coordinates") or []),
        }
    if kind in {"Polygon", "MultiPolygon", "LineString", "Point"}:
        return {
            "type": kind,
            "coordinates": _json_safe(geometry.get("coordinates") or []),
        }
    return None


def _system_feature(system: dict[str, Any]) -> dict[str, Any] | None:
    geometry = _system_geometry_to_geojson(system.get("geometry"))
    if geometry is None:
        return None
    source_type = str(system.get("feature_type") or system.get("type") or "")
    properties = {
        key: _json_safe(value)
        for key, value in system.items()
        if key != "geometry"
    }
    properties["source_feature_type"] = source_type
    properties["feature_type"] = _public_feature_type(source_type)
    source_geometry = system.get("geometry") or {}
    if source_geometry.get("bbox"):
        properties["bbox"] = _json_safe(source_geometry["bbox"])
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _risk_feature(risk: dict[str, Any]) -> dict[str, Any] | None:
    hazard_type = str(risk.get("hazard_type") or "")
    if not hazard_type:
        return None
    try:
        feature_type = str(risk.get("feature_type") or feature_type_for_hazard(hazard_type))
    except KeyError:
        return None
    region = risk.get("region")
    geometry = _system_geometry_to_geojson(region)
    if geometry is None:
        return None
    supporting_systems = [
        item
        for item in (risk.get("supporting_systems") or risk.get("linked_systems") or [])
        if _support_system_type(item) not in BACKGROUND_SUPPORT_SYSTEM_TYPES
    ]
    properties = {
        "id": risk.get("risk_id") or f"risk-{hazard_type}",
        "type": feature_type,
        "feature_type": feature_type,
        "source_feature_type": hazard_type,
        "hazard_type": hazard_type,
        "risk_domain": risk.get("risk_domain") or [],
        "risk_level": risk.get("risk_level") or risk.get("level"),
        "level": risk.get("level") or risk.get("risk_level"),
        "score": risk.get("score"),
        "source_grid": risk.get("source_grid"),
        "source_chain_ids": risk.get("source_chain_ids") or [],
        "dominant_evidence": risk.get("dominant_evidence") or [],
        "supporting_systems": supporting_systems,
        "linked_systems": supporting_systems,
        "mechanism_tags": risk.get("mechanism_tags") or [],
        "name": risk.get("label") or hazard_type,
        "score_statistic": risk.get("score_statistic"),
        "score_source": risk.get("score_source"),
        "region_source": risk.get("region_source"),
        "input_completeness": risk.get("input_completeness"),
        "missing_critical_factors": risk.get("missing_critical_factors") or [],
        "score_cap_applied": risk.get("score_cap_applied"),
        "score_cap_value": risk.get("score_cap_value"),
    }
    if region.get("bbox"):
        properties["bbox"] = region["bbox"]
    if "score_mean" in risk:
        properties["score_mean"] = risk["score_mean"]
    if "score_sample_count" in risk:
        properties["score_sample_count"] = risk["score_sample_count"]
    return {"type": "Feature", "geometry": geometry, "properties": _json_safe(properties)}


def nafp_situation_to_feature_collection(
    result: dict[str, Any],
    *,
    requested_types: list[str] | None = None,
    data_code: str | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    source_filter = _requested_sources(requested_types)
    features: list[dict[str, Any]] = []

    for system in result.get("systems") or []:
        source_type = str(system.get("feature_type") or system.get("type") or "")
        if source_filter is not None and source_type not in source_filter:
            continue
        feature = _system_feature(system)
        if feature is not None:
            features.append(feature)

    for risk in result.get("risk_diagnoses") or []:
        hazard_type = str(risk.get("hazard_type") or "")
        try:
            feature_type = str(risk.get("feature_type") or feature_type_for_hazard(hazard_type))
        except KeyError:
            continue
        if source_filter is not None and feature_type not in source_filter and hazard_type not in source_filter:
            continue
        feature = _risk_feature(risk)
        if feature is not None:
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "properties": {
            "data_code": data_code,
            "root": root,
            "run_time": result.get("run_time"),
            "forecast_hour": result.get("forecast_hour"),
            "valid_time": result.get("valid_time"),
            "requested_types": requested_types or [],
            "count": len(features),
            "summary": result.get("summary"),
        },
        "features": features,
    }
