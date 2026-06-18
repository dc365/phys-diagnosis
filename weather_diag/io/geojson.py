from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def feature_collection(features: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def point_feature(lon: float, lat: float, properties: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


def line_feature(coords: list[list[float]], properties: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": properties}


def polygon_feature(geometry: Dict[str, Any], properties: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def save_geojson(path: str | Path, features: Iterable[Dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(feature_collection(features), ensure_ascii=False, indent=2), encoding='utf-8')


def load_geojson(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return feature_collection([])
    return json.loads(p.read_text(encoding='utf-8'))
