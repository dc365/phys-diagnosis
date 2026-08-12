from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Query

from backend.app.responses import ApiError, ok
from weather_diag.areas.registry import TownArea, load_area_registry
from weather_diag.config import PROJECT_ROOT, load_layers
from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, score_level
from weather_diag.diagnosis.area_risk import (
    _max_sample,
    _prepare_2d,
    _sample_town_points,
    area_risk_metadata,
    supported_area_risk_types,
)
from weather_diag.diagnosis.objective_analysis import mask_unsupported
from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation
from weather_diag.diagnosis.sounding_features import parse_feature_types, sounding_situation_to_feature_collection
from weather_diag.io.contours import contours_to_geojson
from weather_diag.io.grid_geojson import grid_to_geojson


router = APIRouter(prefix="/sounding", tags=["public-sounding"])


def _base_layer(field: str, title: str, unit: str, *, scale: float = 1.0, contour_interval: float | None = None, apply_support_mask: bool = False) -> dict[str, Any]:
    return {
        "field": field,
        "title": title,
        "unit": unit,
        "scale": scale,
        "contour_interval": contour_interval,
        "contour_min_length_km": 320.0 if contour_interval else 0.0,
        "contour_smooth_iterations": 2 if contour_interval else 1,
        "contour_data_smoothing_sigma": 0.25 if contour_interval else 0.0,
        "contour_simplify_tolerance_deg": 0.012 if contour_interval else 0.0,
        "apply_support_mask": apply_support_mask,
    }


def _risk_layer(field: str, title: str) -> dict[str, Any]:
    return _base_layer(field, title, "0-1", contour_interval=None, apply_support_mask=False)


SOUNDING_LAYER_DEFS: dict[str, dict[str, Any]] = {
    "z500": {
        "field": "z500",
        "title": "500hPa 位势高度",
        "unit": "dagpm",
        "scale": 0.1,
        "contour_interval": 4.0,
        "contour_min_length_km": 360.0,
        "contour_smooth_iterations": 2,
        # The canonical Z500 field is already synoptically smoothed.  Applying a
        # second scalar-field smoothing here would make contours and troughs use
        # different height geometry.
        "contour_data_smoothing_sigma": 0.0,
        "contour_simplify_tolerance_deg": 0.012,
        "apply_support_mask": True,
    },
    "t500": _base_layer("t500", "500hPa 温度", "degC", contour_interval=4.0, apply_support_mask=False),
    "wind500_speed": _base_layer("wind500_speed", "500hPa 风速", "m/s"),
    "vort500": _base_layer("vort500", "500hPa 相对涡度", "s^-1"),
    "div500": _base_layer("div500", "500hPa 散度", "s^-1"),
    "t850": _base_layer("t850", "850hPa 温度", "degC", contour_interval=4.0),
    "td850": _base_layer("td850", "850hPa 露点", "degC"),
    "rh850": _base_layer("rh850", "850hPa 相对湿度", "%"),
    "q850": _base_layer("q850", "850hPa 比湿", "g/kg"),
    "wind850_speed": _base_layer("wind850_speed", "850hPa 风速", "m/s"),
    "div850": _base_layer("div850", "850hPa 散度", "s^-1"),
    "vort850": _base_layer("vort850", "850hPa 相对涡度", "s^-1"),
    "moisture_flux850": _base_layer("moisture_flux850", "850hPa 水汽通量", "g/kg*m/s"),
    "t700": _base_layer("t700", "700hPa 温度", "degC", contour_interval=4.0),
    "rh700": _base_layer("rh700", "700hPa 相对湿度", "%"),
    "wind700_speed": _base_layer("wind700_speed", "700hPa 风速", "m/s"),
    "div700": _base_layer("div700", "700hPa 散度", "s^-1"),
    "lapse_rate_700_500": _base_layer("lapse_rate_700_500", "700-500hPa 温度递减率", "degC/km"),
    "wind300_speed": _base_layer("wind300_speed", "300hPa 风速", "m/s"),
    "div300": _base_layer("div300", "300hPa 散度", "s^-1"),
    "wind200_speed": _base_layer("wind200_speed", "200hPa 风速", "m/s"),
    "div200": _base_layer("div200", "200hPa 散度", "s^-1"),
    "shear_850_500": _base_layer("shear_850_500", "850-500hPa 垂直风切变", "m/s"),
    "risk_persistent_heavy_rain_score": _risk_layer("risk_persistent_heavy_rain_score", "探空持续性强降水风险"),
    "risk_short_duration_heavy_rain_score": _risk_layer("risk_short_duration_heavy_rain_score", "探空短时强降水风险"),
    "risk_thunderstorm_gale_score": _risk_layer("risk_thunderstorm_gale_score", "探空雷暴大风风险"),
    "risk_hail_score": _risk_layer("risk_hail_score", "探空冰雹风险"),
    "risk_rotating_storm_score": _risk_layer("risk_rotating_storm_score", "探空旋转风暴风险"),
    "risk_severe_convection_composite_score": _risk_layer("risk_severe_convection_composite_score", "探空强对流综合风险"),
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
        "risk_metadata": field.get("risk_metadata"),
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


def _resolve_area_scope(town_code: str | None, region_code: str | None, region_level: str | None) -> dict[str, Any]:
    if bool(town_code) == bool(region_code):
        raise ApiError(40001, "provide exactly one of town_code or region_code", status_code=400)
    registry = load_area_registry()
    if town_code:
        try:
            town = registry.get_town(town_code)
        except KeyError as exc:
            raise ApiError(40406, "town not found", status_code=404, data={"town_code": town_code}) from exc
        return {
            "scope": {"type": "town", "town_code": town_code, "region_code": None, "region_level": None},
            "towns": [town],
        }
    towns = registry.towns_for_region(str(region_code), region_level=region_level)
    if not towns:
        raise ApiError(
            40406,
            "region not found or has no towns",
            status_code=404,
            data={"region_code": region_code, "region_level": region_level},
        )
    return {
        "scope": {"type": "region", "town_code": None, "region_code": region_code, "region_level": region_level},
        "towns": towns,
    }


def _resolve_area_risk_types(risk_type: str | None) -> list[str]:
    supported = supported_area_risk_types()
    if not risk_type:
        return supported
    if risk_type not in supported:
        raise ApiError(40001, "invalid risk_type", status_code=400, data={"risk_type": risk_type})
    return [risk_type]


def _sounding_town_risk(
    *,
    town: TownArea,
    hazard_type: str,
    analysis_fields: dict[str, Any],
    threshold_matrix: dict[str, Any],
    include_evidence: bool,
    include_samples: bool,
) -> dict[str, Any]:
    metadata = area_risk_metadata([hazard_type])[hazard_type]
    source_grid = metadata["source_grid"]
    field = analysis_fields.get(source_grid) or {}
    lat_raw = field.get("lat")
    lon_raw = field.get("lon")
    lat = np.asarray(lat_raw if lat_raw is not None else [], dtype=float)
    lon = np.asarray(lon_raw if lon_raw is not None else [], dtype=float)
    score_grid = _prepare_2d(field.get("values"), lat, lon)
    samples = _sample_town_points(town, score_grid, lat, lon) if lat.size and lon.size else []
    scores = np.asarray([item["score"] for item in samples if item.get("score") is not None], dtype=float)
    scores = scores[np.isfinite(scores)]
    if scores.size:
        max_score = float(np.nanmax(scores))
        mean_score = float(np.nanmean(scores))
        p90_score = float(np.nanpercentile(scores, 90))
        best_sample = _max_sample(samples)
        level = score_level(max_score, threshold_matrix)
    else:
        max_score = mean_score = p90_score = 0.0
        best_sample = None
        level = score_level(0.0, threshold_matrix)

    risk_item: dict[str, Any] = {
        "hazard_type": hazard_type,
        "label": metadata["label"],
        "metadata": metadata,
        "risk_domain": metadata["risk_domain"],
        "source_grid": source_grid,
        "feature_type": metadata["feature_type"],
        "score": round(max_score, 3),
        "max_score": round(max_score, 3),
        "mean_score": round(mean_score, 3),
        "p90_score": round(p90_score, 3),
        "risk_level": level,
        "level": level,
        "score_source": "sounding_objective_analysis_grid",
        "score_statistic": "station_points_max",
        "sample_count": int(scores.size),
        "station_count": town.station_count,
        "input_completeness": None,
        "missing_critical_factors": [],
        "score_cap_applied": False,
        "score_cap_value": None,
    }
    if include_evidence:
        field_meta = field.get("risk_metadata") or {}
        risk_item["evidence_chain"] = {
            "hazard_type": hazard_type,
            "source_grid": source_grid,
            "sampling_method": "station_points_on_sounding_grid",
            "score_statistic": "station_points_max",
            "dominant_factors": [
                {"factor": item, "field": item, "label": item, "weight": 0.0}
                for item in field_meta.get("sources") or []
            ],
            "max_sample": best_sample,
            "sample_count": int(scores.size),
            "source_paths": [],
        }
    if include_samples:
        risk_item["samples"] = samples
    return risk_item


def _sounding_area_summary(items: list[dict[str, Any]], towns: list[TownArea], risk_types: list[str]) -> dict[str, Any]:
    risks = [risk for item in items for risk in item.get("risks") or []]
    max_score = max((float(risk.get("score") or 0.0) for risk in risks), default=0.0)
    return {
        "town_count": len(towns),
        "risk_type_count": len(risk_types),
        "item_count": len(items),
        "risk_count": len(risks),
        "max_score": round(max_score, 3),
    }


def _public_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_type": result["data_type"],
        "observation_time": result["observation_time"],
        "analysis_level": result["analysis_level"],
        "threshold_matrix": result.get("threshold_matrix"),
        "domain": result["domain"],
        "analysis_fields": {name: _field_public(field) for name, field in result["analysis_fields"].items()},
        "systems": result["systems"],
        "station_features": result["station_features"],
        "station_diagnostics": result["station_diagnostics"],
        "station_risk_diagnoses": result["station_risk_diagnoses"],
        "preprocess_report": result.get("preprocess_report"),
        "multilevel_summary": result.get("multilevel_summary"),
        "analysis_contract": result.get("analysis_contract"),
        "summary": result["summary"],
    }


def _sounding_layer(path: Path, pressure_level: int, layer_id: str) -> dict[str, Any]:
    if int(pressure_level) != 500 or layer_id not in SOUNDING_LAYER_DEFS:
        raise KeyError(layer_id)
    result = _diagnose_sounding(path, pressure_level)
    layer_def = SOUNDING_LAYER_DEFS[layer_id]
    field_key = layer_def["field"]
    if field_key not in result["analysis_fields"]:
        raise KeyError(layer_id)
    field = result["analysis_fields"][field_key]
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
        "risk_metadata": field.get("risk_metadata"),
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
        "risk_metadata": layer.get("risk_metadata"),
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
        return ok(sounding_situation_to_feature_collection(result, requested_types=parse_feature_types(types)))
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc


@router.get("/area-risks")
def sounding_area_risks(
    csv_path: str,
    pressure_level: int = 500,
    town_code: str | None = None,
    region_code: str | None = None,
    region_level: str | None = None,
    risk_type: str | None = None,
    include_evidence: bool = True,
    include_samples: bool = False,
):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    risk_types = _resolve_area_risk_types(risk_type)
    scope = _resolve_area_scope(town_code, region_code, region_level)
    try:
        result = _diagnose_sounding(path, pressure_level)
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc

    matrix = load_threshold_matrix()
    observation_time = result["observation_time"]
    items = [
        {
            "area": town.to_dict(include_points=False),
            "forecast_hour": 0,
            "valid_time": observation_time,
            "risks": [
                _sounding_town_risk(
                    town=town,
                    hazard_type=hazard_type,
                    analysis_fields=result.get("analysis_fields") or {},
                    threshold_matrix=matrix,
                    include_evidence=include_evidence,
                    include_samples=include_samples,
                )
                for hazard_type in risk_types
            ],
        }
        for town in scope["towns"]
    ]
    return ok(
        {
            "data_type": "sounding",
            "observation_time": observation_time,
            "analysis_level": result["analysis_level"],
            "scope": scope["scope"],
            "forecast_hours": [0],
            "risk_types": risk_types,
            "risk_metadata": area_risk_metadata(risk_types),
            "items": items,
            "failed": [],
            "summary": _sounding_area_summary(items, scope["towns"], risk_types),
        }
    )


@router.get("/layers")
def sounding_layers(csv_path: str | None = None, pressure_level: int = 500):
    if csv_path:
        path = _resolve_csv_path(csv_path)
        if not path.exists():
            raise ApiError(40407, "sounding file not found", status_code=404)
        result = _diagnose_sounding(path, pressure_level)
        available = set(result.get("analysis_fields") or {})
    else:
        available = {cfg["field"] for cfg in SOUNDING_LAYER_DEFS.values()}
    return ok({
        layer_id: {"title": cfg["title"], "unit": cfg["unit"], "variable": cfg["field"]}
        for layer_id, cfg in SOUNDING_LAYER_DEFS.items()
        if cfg["field"] in available
    })


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
def sounding_layer_grid(layer_id: str, csv_path: str, pressure_level: int = 500, max_cells: int = Query(default=12000, ge=100, le=50000)):
    path = _resolve_csv_path(csv_path)
    if not path.exists():
        raise ApiError(40407, "sounding file not found", status_code=404)
    try:
        layer = _sounding_layer(path, pressure_level, layer_id)
        return ok(grid_to_geojson(layer["layer_id"], layer["title"], layer["unit"], layer["values"], lat=layer["lat"], lon=layer["lon"], max_cells=max_cells))
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
        return ok(contours_to_geojson(
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
        ))
    except KeyError as exc:
        raise ApiError(40408, "sounding layer not supported", status_code=404, data={"layer_id": layer_id}) from exc
    except ValueError as exc:
        raise ApiError(40007, "invalid sounding request", status_code=400, data={"error": str(exc)}) from exc
