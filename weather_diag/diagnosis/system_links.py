from __future__ import annotations

from copy import deepcopy
from typing import Any

from shapely.geometry import LineString, Point, box, shape


RISK_FEATURE_TO_CHAIN = {
    "heavy_rain_risk": "heavy_rain_potential",
    "convection_risk": "convection_potential",
    "persistent_heavy_rain_risk": "heavy_rain_potential",
    "short_duration_heavy_rain_risk": "heavy_rain_potential",
    "thunderstorm_gale_risk": "convection_potential",
    "hail_risk": "convection_potential",
    "rotating_storm_risk": "convection_potential",
    "severe_convection_composite_risk": "convection_potential",
}


SUPPORT_WEIGHTS = {
    "heavy_rain_potential": {
        "moisture_convergence": 1.0,
        "low_level_convergence": 0.95,
        "low_level_jet": 0.92,
        "moisture_transport": 0.9,
        "upper_divergence": 0.75,
        "front_candidate": 0.72,
        "trough": 0.58,
        "trough_candidate": 0.58,
        "low_pressure_convergence": 0.54,
        "subtropical_high": 0.42,
    },
    "convection_potential": {
        "low_level_convergence": 1.0,
        "upper_divergence": 0.95,
        "front_candidate": 0.86,
        "trough": 0.76,
        "trough_candidate": 0.76,
        "low_level_jet": 0.72,
        "moisture_convergence": 0.7,
        "moisture_transport": 0.62,
        "low_pressure_convergence": 0.56,
        "ridge": 0.35,
        "ridge_candidate": 0.35,
    },
    "dynamic_lift_potential": {
        "trough": 1.0,
        "trough_candidate": 1.0,
        "upper_divergence": 0.92,
        "low_level_convergence": 0.82,
        "front_candidate": 0.78,
        "low_pressure_convergence": 0.76,
        "ridge": 0.38,
        "ridge_candidate": 0.38,
    },
}


TYPE_LABELS = {
    "moisture_convergence": "水汽辐合区",
    "low_level_convergence": "低层辐合区",
    "low_level_jet": "低空急流",
    "moisture_transport": "水汽输送带",
    "upper_divergence": "高空辐散区",
    "front_candidate": "锋面候选区",
    "trough": "槽线",
    "trough_candidate": "槽线候选",
    "ridge": "脊线",
    "ridge_candidate": "脊线候选",
    "low_pressure_convergence": "低压辐合区",
    "subtropical_high": "副高 5880gpm 区",
}


def _geojson_shape(geometry: dict[str, Any]):
    if not geometry:
        return None
    geom_type = str(geometry.get("type") or "")
    if geom_type in {"Point", "LineString", "Polygon", "MultiPolygon"}:
        return shape(geometry)
    if geom_type == "polygon":
        return shape({"type": geometry.get("geojson_type", "Polygon"), "coordinates": geometry.get("coordinates", [])})
    if geom_type == "line":
        return LineString(geometry.get("coordinates", []))
    if geom_type == "point":
        coords = geometry.get("coordinates")
        if coords is not None:
            return Point(coords)
    bbox = geometry.get("bbox")
    if bbox and len(bbox) == 4:
        return box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return None


def _item_geometry(item: dict[str, Any]):
    if item.get("type") == "Feature":
        return _geojson_shape(item.get("geometry") or {})
    return _geojson_shape(item.get("geometry") or item)


def _item_type(item: dict[str, Any]) -> str:
    if item.get("type") == "Feature":
        return str((item.get("properties") or {}).get("feature_type") or "")
    return str(item.get("type") or item.get("target_type") or "")


def _item_id(item: dict[str, Any]) -> str:
    if item.get("type") == "Feature":
        props = item.get("properties") or {}
        return str(props.get("id") or props.get("feature_type") or "")
    return str(item.get("id") or item.get("target_type") or item.get("type") or "")


def _item_name(item: dict[str, Any]) -> str:
    if item.get("type") == "Feature":
        props = item.get("properties") or {}
        return str(props.get("title") or props.get("feature_type") or "")
    return str(item.get("name") or item.get("title") or item.get("type") or "")


def _reason(candidate_type: str, relation: str, distance: float) -> str:
    label = TYPE_LABELS.get(candidate_type, candidate_type)
    if relation == "overlap":
        return f"{label}与风险区空间重叠，可作为天气学支撑系统"
    return f"{label}位于风险区附近，距离约 {distance:.2f}°，可作为邻近支撑系统"


def supporting_system_links(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    target_type: str,
    max_links: int = 5,
    max_distance_degrees: float = 4.0,
    max_per_type: int = 1,
) -> list[dict[str, Any]]:
    target_geom = _item_geometry(target)
    if target_geom is None or target_geom.is_empty:
        return []
    weights = SUPPORT_WEIGHTS.get(target_type, {})
    links = []
    for candidate in candidates:
        candidate_type = _item_type(candidate)
        type_weight = weights.get(candidate_type, 0.0)
        if type_weight <= 0:
            continue
        candidate_geom = _item_geometry(candidate)
        if candidate_geom is None or candidate_geom.is_empty:
            continue
        distance = float(target_geom.distance(candidate_geom))
        intersects = bool(target_geom.intersects(candidate_geom))
        if not intersects and distance > max_distance_degrees:
            continue
        spatial_score = 1.0 if intersects else max(0.0, 1.0 - distance / max_distance_degrees)
        relation = "overlap" if intersects else "nearby"
        relevance = round(type_weight * 0.7 + spatial_score * 0.3, 3)
        candidate_id = _item_id(candidate)
        links.append(
            {
                "id": candidate_id,
                "system_id": candidate_id,
                "type": candidate_type,
                "name": _item_name(candidate),
                "relation": relation,
                "distance_degrees": round(distance, 3),
                "relevance": relevance,
                "reason": _reason(candidate_type, relation, distance),
            }
        )
    links.sort(key=lambda item: (item["relevance"], item["relation"] == "overlap"), reverse=True)
    if max_per_type <= 0:
        return links[:max_links]

    selected = []
    type_counts: dict[str, int] = {}
    for link in links:
        count = type_counts.get(link["type"], 0)
        if count >= max_per_type:
            continue
        selected.append(link)
        type_counts[link["type"]] = count + 1
        if len(selected) >= max_links:
            break
    return selected


def attach_feature_supporting_systems(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = deepcopy(features)
    candidates = [
        feature
        for feature in out
        if _item_type(feature) not in RISK_FEATURE_TO_CHAIN
    ]
    for feature in out:
        feature_type = _item_type(feature)
        target_type = RISK_FEATURE_TO_CHAIN.get(feature_type)
        if not target_type:
            continue
        links = supporting_system_links(feature, candidates, target_type=target_type)
        props = feature.setdefault("properties", {})
        props["supporting_systems"] = links
        if links:
            props.setdefault("evidence", []).append("关联天气系统：" + "、".join(link["name"] or link["type"] for link in links[:3]))
    return out


def attach_chain_supporting_systems(
    evidence_chains: list[dict[str, Any]],
    systems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = deepcopy(evidence_chains)
    for chain in out:
        target_type = str(chain.get("target_type") or "")
        if target_type not in SUPPORT_WEIGHTS:
            chain["linked_systems"] = []
            continue
        region = chain.get("region")
        links = supporting_system_links(region, systems, target_type=target_type) if region else []
        chain["linked_systems"] = links
    return out
