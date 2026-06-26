from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Query

from backend.app.responses import ApiError, ok
from weather_diag.config import PROJECT_ROOT, load_layers
from weather_diag.diagnosis.sounding import diagnose_sounding_situation
from weather_diag.diagnosis.sounding_features import parse_feature_types, sounding_situation_to_feature_collection
from weather_diag.io.contours import contours_to_geojson
from weather_diag.io.grid_geojson import grid_to_geojson


router = APIRouter(prefix="/sounding", tags=["public-sounding"])


def _resolve_csv_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _field_public(field: dict[str, Any]) -> dict[str, Any]:
    values = np.asarray(field["values"], dtype=float)
    valid = values[np.isfinite(values)]
    return {
        "unit": field.get("unit", ""),
        "quality": field.get("quality", {}),
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
        "lat_count": int(len(field.get("lat", []))),
        "lon_count": int(len(field.get("lon", []))),
    }


@lru_cache(maxsize=16)
def _diagnose_sounding_cached(path: str, pressure_level: int, mtime_ns: int) -> dict[str, Any]:
    return diagnose_sounding_situation(Path(path), pressure_level=pressure_level)


def _diagnose_sounding(path: Path, pressure_level: int) -> dict[str, Any]:
    return _diagnose_sounding_cached(str(path), int(pressure_level), path.stat().st_mtime_ns)


def _public_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_type": result["data_type"],
        "observation_time": result["observation_time"],
        "analysis_level": result["analysis_level"],
        "domain": result["domain"],
        "analysis_fields": {
            name: _field_public(field)
            for name, field in result["analysis_fields"].items()
        },
        "systems": result["systems"],
        "station_features": result["station_features"],
        "station_diagnostics": result["station_diagnostics"],
        "station_risk_diagnoses": result["station_risk_diagnoses"],
        "summary": result["summary"],
    }


def _sounding_layer(path: Path, pressure_level: int, layer_id: str) -> dict[str, Any]:
    if int(pressure_level) != 500 or layer_id != "z500":
        raise KeyError(layer_id)
    result = _diagnose_sounding(path, pressure_level)
    field = result["analysis_fields"]["z500"]
    values = np.asarray(field["values"], dtype=float) / 10.0
    valid = values[np.isfinite(values)]
    cfg = load_layers().get("z500", {})
    quality = field.get("quality") or {}
    return {
        "layer_id": "z500",
        "title": cfg.get("title", "500hPa 位势高度"),
        "unit": "dagpm",
        "values": values,
        "lat": np.asarray(field["lat"], dtype=float),
        "lon": np.asarray(field["lon"], dtype=float),
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
        "data_type": "sounding",
        "observation_time": result["observation_time"],
        "analysis_level": result["analysis_level"],
        "analysis_method": quality.get("method"),
        "station_count": quality.get("station_count"),
        "contour": cfg.get("contour") or {},
    }


def _sounding_layer_metadata(layer: dict[str, Any]) -> dict[str, Any]:
    lat = layer["lat"]
    lon = layer["lon"]
    return {
        "layer_id": layer["layer_id"],
        "title": layer["title"],
        "unit": layer["unit"],
        "data_type": layer["data_type"],
        "observation_time": layer["observation_time"],
        "analysis_level": layer["analysis_level"],
        "analysis_method": layer["analysis_method"],
        "station_count": layer["station_count"],
        "lat_min": float(np.nanmin(lat)),
        "lat_max": float(np.nanmax(lat)),
        "lon_min": float(np.nanmin(lon)),
        "lon_max": float(np.nanmax(lon)),
        "min": layer["min"],
        "max": layer["max"],
    }


@router.get("/situation")
def sounding_situation(csv_path: str, pressure_level: int = 500):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        return ok(_public_payload(_diagnose_sounding(path, pressure_level)))
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc


@router.get("/features")
def sounding_features(csv_path: str, pressure_level: int = 500, types: str | None = None):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        result = _diagnose_sounding(path, pressure_level)
        return ok(
            sounding_situation_to_feature_collection(
                result,
                requested_types=parse_feature_types(types),
            )
        )
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc


@router.get("/layers/{layer_id}/metadata")
def sounding_layer_metadata(layer_id: str, csv_path: str, pressure_level: int = 500):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        return ok(_sounding_layer_metadata(_sounding_layer(path, pressure_level, layer_id)))
    except KeyError as exc:
        raise ApiError(40408, "sounding layer not supported", status_code=404, data={"layer_id": layer_id}) from exc
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc


@router.get("/layers/{layer_id}/grid")
def sounding_layer_grid(
    layer_id: str,
    csv_path: str,
    pressure_level: int = 500,
    max_cells: int = Query(default=12000, ge=100, le=50000),
):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        layer = _sounding_layer(path, pressure_level, layer_id)
        return ok(
            grid_to_geojson(
                layer["layer_id"],
                layer["title"],
                layer["unit"],
                layer["values"],
                lat=layer["lat"],
                lon=layer["lon"],
                max_cells=max_cells,
            )
        )
    except KeyError as exc:
        raise ApiError(40408, "sounding layer not supported", status_code=404, data={"layer_id": layer_id}) from exc
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc


@router.get("/layers/{layer_id}/contours")
def sounding_layer_contours(
    layer_id: str,
    csv_path: str,
    pressure_level: int = 500,
    levels: str | None = Query(default=None),
    interval: float | None = Query(default=None),
    max_segments: int | None = Query(default=None, ge=100, le=50000),
):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        layer = _sounding_layer(path, pressure_level, layer_id)
        contour_cfg = layer.get("contour") or {}
        return ok(
            contours_to_geojson(
                layer["layer_id"],
                layer["title"],
                layer["unit"],
                layer["values"],
                lat=layer["lat"],
                lon=layer["lon"],
                levels=[float(item) for item in levels.split(",") if item.strip()] if levels else contour_cfg.get("levels"),
                interval=interval or contour_cfg.get("interval"),
                max_segments=max_segments or int(contour_cfg.get("max_segments", 12000)),
            )
        )
    except KeyError as exc:
        raise ApiError(40408, "sounding layer not supported", status_code=404, data={"layer_id": layer_id}) from exc
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc
