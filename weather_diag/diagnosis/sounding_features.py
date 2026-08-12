from __future__ import annotations

from typing import Any, Iterable

from weather_diag.diagnosis.nafp_features import _json_safe, _system_geometry_to_geojson
from weather_diag.diagnosis.risk_taxonomy import feature_type_for_hazard


FEATURE_TYPE_ALIASES = {
    "high": {"height_high"},
    "low": {"height_low"},
    "trough": {"trough_candidate"},
    "ridge": {"ridge_candidate"},
}

PUBLIC_FEATURE_TYPES = {
    "height_high": "high",
    "height_low": "low",
    "trough_candidate": "trough",
    "ridge_candidate": "ridge",
}


def parse_feature_types(value: str | None) -> list[str] | None:
    if not value:
        return None
    types = [item.strip() for item in value.split(",") if item.strip()]
    return types or None


def _requested_sources(requested_types: Iterable[str] | None) -> set[str] | None:
    if requested_types is None:
        return None
    sources: set[str] = set()
    for feature_type in requested_types:
        sources.add(feature_type)
        sources.update(FEATURE_TYPE_ALIASES.get(feature_type, set()))
    return sources


def _public_feature_type(source_type: str) -> str:
    return PUBLIC_FEATURE_TYPES.get(source_type, source_type)


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
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _risk_evidence(risk: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for factor in risk.get("dominant_factors") or []:
        evidence.append(
            {
                "signal": factor.get("label") or factor.get("factor") or "sounding index",
                "field": factor.get("factor") or "",
                "value": factor.get("score"),
                "contribution": factor.get("contribution"),
            }
        )
    return evidence


def _station_risk_features(item: dict[str, Any], source_filter: set[str] | None) -> list[dict[str, Any]]:
    lon = item.get("station_lon")
    lat = item.get("station_lat")
    if lon is None or lat is None:
        return []
    matched_risks: list[tuple[float, str, str, dict[str, Any]]] = []
    for risk in item.get("risks") or []:
        hazard_type = str(risk.get("hazard_type") or "")
        if not hazard_type:
            continue
        feature_type = str(risk.get("feature_type") or feature_type_for_hazard(hazard_type))
        if source_filter is not None and feature_type not in source_filter and hazard_type not in source_filter:
            continue
        matched_risks.append((float(risk.get("score") or 0.0), hazard_type, feature_type, risk))
    if not matched_risks:
        return []
    score, hazard_type, feature_type, risk = max(matched_risks, key=lambda match: match[0])
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": _json_safe(
                {
                    "id": f"sounding-risk-{item.get('station_id')}-{hazard_type}",
                    "type": feature_type,
                    "feature_type": feature_type,
                    "source_feature_type": hazard_type,
                    "hazard_type": hazard_type,
                    "label": risk.get("label") or hazard_type,
                    "station_id": item.get("station_id"),
                    "station_name": item.get("station_name"),
                    "risk_level": risk.get("risk_level"),
                    "level": risk.get("risk_level"),
                    "score": score,
                    "confidence": score,
                    "score_source": risk.get("score_source"),
                    "source_indices": risk.get("source_indices") or [],
                    "dominant_factors": risk.get("dominant_factors") or [],
                    "evidence": _risk_evidence(risk),
                    "input_completeness": risk.get("input_completeness"),
                    "missing_critical_factors": risk.get("missing_critical_factors") or [],
                    "score_cap_applied": risk.get("score_cap_applied"),
                    "score_cap_value": risk.get("score_cap_value"),
                }
            ),
        }
    ]


def sounding_situation_to_feature_collection(
    result: dict[str, Any],
    *,
    requested_types: list[str] | None = None,
) -> dict[str, Any]:
    source_filter = _requested_sources(requested_types)
    features: list[dict[str, Any]] = []

    for system in result.get("systems") or []:
        source_type = str(system.get("feature_type") or system.get("type") or "")
        public_type = _public_feature_type(source_type)
        if source_filter is not None and source_type not in source_filter and public_type not in source_filter:
            continue
        feature = _system_feature(system)
        if feature is not None:
            features.append(feature)

    for item in result.get("station_risk_diagnoses") or []:
        features.extend(_station_risk_features(item, source_filter))

    return {
        "type": "FeatureCollection",
        "properties": {
            "data_type": "sounding",
            "observation_time": result.get("observation_time"),
            "analysis_level": result.get("analysis_level"),
            "domain": result.get("domain") or {},
            "requested_types": requested_types or [],
            "count": len(features),
            "summary": result.get("summary"),
        },
        "features": features,
    }
