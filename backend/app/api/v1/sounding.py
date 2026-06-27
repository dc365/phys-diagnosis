from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Query

from backend.app.responses import ApiError, ok
from weather_diag.config import PROJECT_ROOT, load_layers
from weather_diag.diagnosis.objective_analysis import mask_unsupported
from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation
from weather_diag.diagnosis.sounding_features import parse_feature_types, sounding_situation_to_feature_collection
from weather_diag.io.contours import contours_to_geojson
from weather_diag.io.grid_geojson import grid_to_geojson


router = APIRouter(prefix="/sounding", tags=["public-sounding"])


SOUNDING_LAYER_DEFS = {
    "z500": {
        "field": "z500",
        "title": "500hPa 位势高度",
        "unit": "dagpm",
        "scale": 0.1,
        "contour_interval": 4.0,
        # Keep short-to-medium 588-dagpm subtropical-high arcs near Hainan, but
        # still filter small isolated contour fragments.
        "contour_min_length_km": 360.0,
        "contour_smooth_iterations": 2,
        "contour_data_smoothing_sigma": 0.30,
        "contour_simplify_tolerance_deg": 0.012,
        # CMA/NMC H500 charts keep synoptic contours across the whole domain.
        # Keep support metadata, but do not clip z500 contours by station-distance
        # mask; otherwise contour segments break near sparse western/ocean areas.
        "apply_support_mask": False,
    },
    "t500": {
        "field": "t500",
        "title": "500hPa 温度",
        "unit": "degC",
        "scale": 1.0,
        "contour_interval": 4.0,
        "contour_min_length_km": 320.0,
        "contour_smooth_iterations": 2,
        "contour_data_smoothing_sigma": 0.25,
        "contour_simplify_tolerance_deg": 0.012,
        "apply_support_mask": False,
    },
}


def _resolve_csv_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _field_public(field: dict[str, Any]) -> dict[str, Any]:
    values = np.asarray(field["values"], dtype=float)
    valid = values[np.isfinite(values)]
    support = np.asarray(field.get("support_mask"), dtype=bool) if field.get("support_mask") is not None else None
    return {
        "unit": field.get("unit", ""),
        "quality": field.get("quality", {}),
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
        "lat_count": int(len(field.get("lat", []))),
        "lon_count": int(len(field.get("lon", []))),
        "support_ratio": round(float(np.mean(support)), 3) if support is not None and support.size else None,
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
    if int(pressure_level) != 500 or layer_id not in SOUNDING_LAYER_DEFS:
        raise KeyError(layer_id)
    result = _diagnose_sounding(path, pressure_level)
    layer_def = SOUNDING_LAYER_DEFS[layer_id]
    field = result["analysis_fields"][layer_def["field"]]
    values = np.asarray(field["values"], dtype=float) * float(layer_def["scale"])
    if bool(layer_def.get("apply_support_mask", True)):
        values = mask_unsupported(values, field.get("support_mask"))
    valid = values[np.isfinite(values)]
    cfg = load_layers().get(layer_id, {})
    contour_cfg = cfg.get("contour") or {}
    quality = field.get("quality") or {}
    return {
        "layer_id": layer_id,
        "title": cfg.get("title", layer_def["title"]),
        "unit": layer_def["unit"],
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
        "support_ratio": quality.get("supported_grid_ratio"),
        "mean_nearest_station_km": quality.get("mean_nearest_station_km"),
        "station_residual_rmse": quality.get("station_residual_rmse"),
        "apply_support_mask": bool(layer_def.get("apply_support_mask", True)),
        "contour": {
            **contour_cfg,
            "interval": contour_cfg.get("interval", layer_def["contour_interval"]),
            "min_length_km": contour_cfg.get("min_length_km", layer_def["contour_min_length_km"]),
            "smooth_iterations": contour_cfg.get("smooth_iterations", layer_def["contour_smooth_iterations"]),
            "data_smoothing_sigma": contour_cfg.get("data_smoothing_sigma", layer_def["contour_data_smoothing_sigma"]),
            "simplify_tolerance_deg": contour_cfg.get("simplify_tolerance_deg", layer_def["contour_simplify_tolerance_deg"]),
        },
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
        "support_ratio": layer.get("support_ratio"),
        "mean_nearest_station_km": layer.get("mean_nearest_station_km"),
        "station_residual_rmse": layer.get("station_residual_rmse"),
        "apply_support_mask": layer.get("apply_support_mask"),
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
                min_length_km=float(contour_cfg.get("min_length_km", 0.0)),
                smooth=True,
                smooth_iterations=int(contour_cfg.get("smooth_iterations", 1)),
                data_smoothing_sigma=float(contour_cfg.get("data_smoothing_sigma", 0.0)),
                simplify_tolerance_deg=float(contour_cfg.get("simplify_tolerance_deg", 0.0)),
            )
        )
    except KeyError as exc:
        raise ApiError(40408, "sounding layer not supported", status_code=404, data={"layer_id": layer_id}) from exc
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc
