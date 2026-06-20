from __future__ import annotations

from typing import Any, Iterable

import numpy as np


FEATURE_TYPE_ALIASES = {
    "trough": {"trough_candidate"},
    "ridge": {"ridge_candidate"},
    "heavy_rain_risk": {"heavy_rain_potential"},
    "convection_risk": {"convection_potential"},
}

CHAIN_FEATURE_TYPES = {
    "heavy_rain_potential": "heavy_rain_risk",
    "convection_potential": "convection_risk",
}


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


def _chain_feature(chain: dict[str, Any]) -> dict[str, Any] | None:
    target_type = str(chain.get("target_type") or "")
    feature_type = CHAIN_FEATURE_TYPES.get(target_type)
    if not feature_type:
        return None
    region = chain.get("region")
    geometry = _system_geometry_to_geojson(region)
    if geometry is None:
        return None
    properties = {
        "id": chain.get("id") or f"chain-{target_type}",
        "type": feature_type,
        "feature_type": feature_type,
        "source_feature_type": target_type,
        "target_type": target_type,
        "name": "强降水潜势区" if feature_type == "heavy_rain_risk" else "强对流潜势区",
        "level": chain.get("level"),
        "confidence": chain.get("score"),
        "score": chain.get("score"),
        "diagnosis": "综合证据链识别的潜势区",
        "evidence": chain.get("evidence") or [],
        "dominant_evidence": chain.get("dominant_evidence") or [],
        "missing_evidence": chain.get("missing_evidence") or [],
        "linked_systems": chain.get("linked_systems") or [],
    }
    if region.get("bbox"):
        properties["bbox"] = region["bbox"]
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

    for chain in result.get("evidence_chains") or []:
        source_type = str(chain.get("target_type") or "")
        if source_filter is not None and source_type not in source_filter:
            continue
        feature = _chain_feature(chain)
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
