from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.responses import ApiError, ok
from backend.app.services.data_sources import DataSourceError, list_data_sources, resolve_data_root
from weather_diag.areas.registry import load_area_registry
from weather_diag.config import load_layers
from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.area_risk import (
    area_risk_metadata,
    evaluate_area_risks,
    supported_area_risk_types,
)
from weather_diag.diagnosis.nafp_cache import get_or_compute_nafp_situation, nafp_situation_cache_info
from weather_diag.diagnosis.nafp_features import nafp_situation_to_feature_collection, parse_feature_types
from weather_diag.diagnosis.nafp_layers import layer_metadata, load_nafp_layer
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation
from weather_diag.diagnosis.point import diagnose_nafp_point
from weather_diag.io.contours import contours_to_geojson
from weather_diag.io.grid_geojson import grid_to_geojson


class NafpSituationRequest(BaseModel):
    data_code: str | None = None
    root: str | None = None
    run_time: str
    forecast_hour: int


class NafpBatchSituationRequest(BaseModel):
    data_code: str | None = None
    root: str | None = None
    run_time: str
    forecast_hours: list[int]


class NafpPrecomputeRequest(NafpBatchSituationRequest):
    force: bool = False


class NafpPointRequest(NafpSituationRequest):
    lat: float
    lon: float


router = APIRouter(prefix="/diagnosis/nafp", tags=["public-diagnosis"])


def parse_contour_levels(value: Optional[str]) -> list[float] | None:
    if not value:
        return None
    levels: list[float] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            levels.append(float(item))
    return levels or None


def _resolve_nafp_root(data_code: str | None, root: str | None):
    try:
        resolved = resolve_data_root(data_code, root)
    except DataSourceError as exc:
        raise ApiError(40004, "invalid data code", status_code=400, data={"error": str(exc)}) from exc
    if not resolved.exists() or not resolved.is_dir():
        raise ApiError(40004, "invalid NAFP root", status_code=400)
    return resolved


def _diagnose_situation_cached_or_error(
    root,
    run_time: str,
    forecast_hour: int,
    *,
    force: bool = False,
) -> tuple[dict, dict]:
    try:
        return get_or_compute_nafp_situation(
            root=root,
            run_time=run_time,
            forecast_hour=forecast_hour,
            compute=diagnose_nafp_situation,
            force=force,
        )
    except FileNotFoundError as exc:
        raise ApiError(
            40404,
            "required NAFP product not found",
            status_code=404,
            data={"error": str(exc)},
        ) from exc
    except Exception as exc:
        raise ApiError(
            50002,
            "NAFP diagnosis failed",
            status_code=500,
            data={"error": str(exc)},
        ) from exc


def _diagnose_situation_or_error(root, run_time: str, forecast_hour: int) -> dict:
    result, _cache_meta = _diagnose_situation_cached_or_error(root, run_time, forecast_hour)
    return result


def _configured_forecast_hours(data_code: str | None) -> list[int]:
    sources = list_data_sources()
    code = data_code or sources.get("default_code")
    for item in sources.get("items") or []:
        if item.get("code") == code:
            return [int(hour) for hour in item.get("forecast_hours") or []]
    return []


def _parse_api_time(value: str, param: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(40001, f"invalid {param}", status_code=400, data={"value": value}) from exc


def _resolve_area_forecast_hours(
    *,
    data_code: str | None,
    run_time: str,
    forecast_hour_start: int | None,
    forecast_hour_end: int | None,
    valid_start: str | None,
    valid_end: str | None,
    start_time: str | None,
    end_time: str | None,
) -> list[int]:
    configured = _configured_forecast_hours(data_code)
    if not configured:
        start = 0 if forecast_hour_start is None else int(forecast_hour_start)
        end = start if forecast_hour_end is None else int(forecast_hour_end)
        configured = list(range(start, end + 1, 3 if end > start else 1))

    start_value = valid_start or start_time
    end_value = valid_end or end_time
    if start_value or end_value:
        if not start_value or not end_value:
            raise ApiError(40001, "start and end time must be provided together", status_code=400)
        begin = _parse_api_time(start_value, "start_time")
        finish = _parse_api_time(end_value, "end_time")
        if finish < begin:
            raise ApiError(40001, "end_time must be >= start_time", status_code=400)
        rt = parse_run_time(run_time)
        hours = [hour for hour in configured if begin <= rt + timedelta(hours=hour) <= finish]
    else:
        start = min(configured) if forecast_hour_start is None else int(forecast_hour_start)
        end = max(configured) if forecast_hour_end is None else int(forecast_hour_end)
        if end < start:
            raise ApiError(40001, "forecast_hour_end must be >= forecast_hour_start", status_code=400)
        hours = [hour for hour in configured if start <= hour <= end]

    if not hours:
        raise ApiError(40001, "no forecast hours matched the requested range", status_code=400)
    return _dedupe_forecast_hours(hours)


def _resolve_area_scope(town_code: str | None, region_code: str | None, region_level: str | None):
    if bool(town_code) == bool(region_code):
        raise ApiError(40001, "provide exactly one of town_code or region_code", status_code=400)
    registry = load_area_registry()
    if town_code:
        try:
            town = registry.get_town(town_code)
        except KeyError as exc:
            raise ApiError(40406, "town not found", status_code=404, data={"town_code": town_code}) from exc
        return {
            "scope": {
                "type": "town",
                "town_code": town_code,
                "region_code": None,
                "region_level": None,
            },
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
        "scope": {
            "type": "region",
            "town_code": None,
            "region_code": region_code,
            "region_level": region_level,
        },
        "towns": towns,
    }


def _resolve_risk_types(risk_type: str | None) -> list[str]:
    supported = supported_area_risk_types()
    if not risk_type:
        return supported
    if risk_type not in supported:
        raise ApiError(40001, "invalid risk_type", status_code=400, data={"risk_type": risk_type})
    return [risk_type]


@router.get("/areas")
def nafp_area_catalog():
    registry = load_area_registry()
    towns = registry.all_towns()
    city_map: dict[str, dict] = {}
    county_map: dict[str, dict] = {}
    for town in towns:
        city = city_map.setdefault(
            town.city_code,
            {
                "city_code": town.city_code,
                "city_name": town.city_name,
                "town_count": 0,
                "county_codes": set(),
            },
        )
        city["town_count"] += 1
        city["county_codes"].add(town.county_code)
        county = county_map.setdefault(
            town.county_code,
            {
                "city_code": town.city_code,
                "city_name": town.city_name,
                "county_code": town.county_code,
                "county_name": town.county_name,
                "town_count": 0,
            },
        )
        county["town_count"] += 1

    cities = []
    for item in sorted(city_map.values(), key=lambda value: value["city_code"]):
        cities.append(
            {
                "city_code": item["city_code"],
                "city_name": item["city_name"],
                "town_count": item["town_count"],
                "county_count": len(item["county_codes"]),
            }
        )
    counties = sorted(county_map.values(), key=lambda value: (value["city_code"], value["county_code"]))
    return ok(
        {
            "city_count": len(cities),
            "county_count": len(counties),
            "town_count": len(towns),
            "cities": cities,
            "counties": counties,
            "towns": [town.to_dict(include_points=False) for town in towns],
            "risk_metadata": area_risk_metadata(),
        }
    )


@router.post("/situation")
def diagnose_situation(request: NafpSituationRequest):
    root = _resolve_nafp_root(request.data_code, request.root)
    return ok(_diagnose_situation_or_error(root, request.run_time, request.forecast_hour))


def _dedupe_forecast_hours(hours: list[int]) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for raw in hours:
        hour = int(raw)
        if hour in seen:
            continue
        seen.add(hour)
        values.append(hour)
    return values


def _first_system(result: dict, system_type: str) -> dict | None:
    for system in result.get("systems") or []:
        if system.get("type") == system_type:
            return system
    return None


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _subtropical_high_sample(result: dict) -> dict | None:
    system = _first_system(result, "subtropical_high")
    if not system:
        return None
    ridge_point = system.get("ridge_point") or {}
    forecast_hour = _as_int(result.get("forecast_hour"))
    ridge_lon = _as_float(ridge_point.get("lon"))
    ridge_lat = _as_float(ridge_point.get("lat"))
    north_boundary_lat = _as_float(system.get("north_boundary_lat"))
    area_grid_points = _as_int(system.get("area_grid_points"))
    mean_height = _as_float(system.get("mean_height"))
    if (
        forecast_hour is None
        or ridge_lon is None
        or north_boundary_lat is None
        or area_grid_points is None
        or mean_height is None
    ):
        return None
    return {
        "forecast_hour": forecast_hour,
        "ridge_point_lon": ridge_lon,
        "ridge_point_lat": ridge_lat,
        "north_boundary_lat": north_boundary_lat,
        "area_grid_points": area_grid_points,
        "mean_height": mean_height,
    }


def _direction_change(delta: float | None, *, threshold: float, positive: str, negative: str, stable: str) -> str:
    if delta is None:
        return "unknown"
    if delta > threshold:
        return positive
    if delta < -threshold:
        return negative
    return stable


def _change_label(direction: str, labels: dict[str, str]) -> str:
    return labels.get(direction, "未知")


def _empty_change(direction_labels: dict[str, str]) -> dict:
    return {"direction": "unknown", "label": _change_label("unknown", direction_labels)}


def _subtropical_high_trend(results: list[dict]) -> dict:
    samples = [
        sample
        for result in sorted(results, key=lambda item: int(item.get("forecast_hour") or 0))
        if (sample := _subtropical_high_sample(result)) is not None
    ]
    if len(samples) < 2:
        return {
            "system_type": "subtropical_high",
            "label": "副高",
            "geometry_role": "polygon",
            "available": False,
            "samples": samples,
            "west_extension": {"direction": "unknown", "label": "未知"},
            "north_shift": {"direction": "unknown", "label": "未知"},
            "area_change": {"direction": "unknown", "label": "未知"},
            "intensity_change": {"direction": "unknown", "label": "未知"},
            "trend_summary": "副高时效演变样本不足。",
        }

    start = samples[0]
    end = samples[-1]

    west_delta = float(end["ridge_point_lon"]) - float(start["ridge_point_lon"])
    north_delta = float(end["north_boundary_lat"]) - float(start["north_boundary_lat"])
    area_delta = int(end["area_grid_points"]) - int(start["area_grid_points"])
    start_area = max(1, int(start["area_grid_points"]))
    area_percent = area_delta / start_area * 100.0
    intensity_delta = float(end["mean_height"]) - float(start["mean_height"])

    west_direction = _direction_change(
        west_delta,
        threshold=0.25,
        positive="eastward",
        negative="westward",
        stable="stable",
    )
    north_direction = _direction_change(
        north_delta,
        threshold=0.25,
        positive="northward",
        negative="southward",
        stable="stable",
    )
    area_direction = _direction_change(
        area_percent,
        threshold=5.0,
        positive="expanding",
        negative="shrinking",
        stable="stable",
    )
    intensity_direction = _direction_change(
        intensity_delta,
        threshold=0.1,
        positive="strengthening",
        negative="weakening",
        stable="stable",
    )

    west_labels = {"westward": "西伸", "eastward": "东退", "stable": "少变", "unknown": "未知"}
    north_labels = {"northward": "北抬", "southward": "南落", "stable": "少变", "unknown": "未知"}
    area_labels = {"expanding": "扩大", "shrinking": "缩小", "stable": "少变", "unknown": "未知"}
    intensity_labels = {"strengthening": "增强", "weakening": "减弱", "stable": "少变", "unknown": "未知"}

    return {
        "system_type": "subtropical_high",
        "label": "副高",
        "geometry_role": "polygon",
        "available": True,
        "baseline_forecast_hour": start["forecast_hour"],
        "target_forecast_hour": end["forecast_hour"],
        "samples": samples,
        "west_extension": {
            "direction": west_direction,
            "label": _change_label(west_direction, west_labels),
            "delta_lon": round(west_delta, 3),
        },
        "north_shift": {
            "direction": north_direction,
            "label": _change_label(north_direction, north_labels),
            "delta_lat": round(north_delta, 3),
        },
        "area_change": {
            "direction": area_direction,
            "label": _change_label(area_direction, area_labels),
            "delta_grid_points": int(area_delta),
            "delta_percent": round(area_percent, 2),
        },
        "intensity_change": {
            "direction": intensity_direction,
            "label": _change_label(intensity_direction, intensity_labels),
            "delta_mean_height": round(intensity_delta, 3),
        },
        "trend_summary": (
            f"副高从 +{start['forecast_hour']}h 到 +{end['forecast_hour']}h "
            f"{_change_label(west_direction, west_labels)}、"
            f"{_change_label(north_direction, north_labels)}，"
            f"面积{_change_label(area_direction, area_labels)}，"
            f"强度{_change_label(intensity_direction, intensity_labels)}。"
        ),
    }


def _line_coordinates(system: dict) -> list[list[float]]:
    geometry = system.get("geometry") or {}
    if geometry.get("type") != "line":
        return []
    coords = []
    for point in geometry.get("coordinates") or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        lon = _as_float(point[0])
        lat = _as_float(point[1])
        if lon is None or lat is None:
            continue
        coords.append([lon, lat])
    return coords


def _line_length_degrees(coords: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(coords, coords[1:]):
        total += math.hypot(end[0] - start[0], end[1] - start[1])
    return total


def _mean(values: list[float]) -> float | None:
    valid = [value for value in values if value is not None and math.isfinite(value)]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _line_center(coords: list[list[float]]) -> tuple[float, float] | None:
    if not coords:
        return None
    lon = _mean([point[0] for point in coords])
    lat = _mean([point[1] for point in coords])
    if lon is None or lat is None:
        return None
    return lon, lat


def _line_system_sample(result: dict, system_type: str) -> dict | None:
    systems = [
        system
        for system in result.get("systems") or []
        if system.get("type") == system_type and _line_coordinates(system)
    ]
    if not systems:
        return None
    if any(isinstance(system.get("primary"), bool) for system in systems):
        primary_systems = [system for system in systems if system.get("primary") is True]
        systems = primary_systems or systems

    centers = []
    lengths = []
    confidences = []
    for system in systems:
        coords = _line_coordinates(system)
        center = _line_center(coords)
        if center is None:
            continue
        centers.append(center)
        lengths.append(_line_length_degrees(coords))
        confidence = _as_float(system.get("confidence"))
        if confidence is not None:
            confidences.append(confidence)

    forecast_hour = _as_int(result.get("forecast_hour"))
    mean_lon = _mean([center[0] for center in centers])
    mean_lat = _mean([center[1] for center in centers])
    mean_length = _mean(lengths)
    mean_confidence = _mean(confidences)
    if forecast_hour is None or mean_lon is None or mean_lat is None or mean_length is None:
        return None
    return {
        "forecast_hour": forecast_hour,
        "object_count": len(systems),
        "mean_center_lon": round(mean_lon, 3),
        "mean_center_lat": round(mean_lat, 3),
        "mean_axis_length_degrees": round(mean_length, 3),
        "mean_confidence": round(mean_confidence, 3) if mean_confidence is not None else None,
    }


def _percent_delta(end_value: float, start_value: float) -> float | None:
    if start_value == 0:
        return None
    return (end_value - start_value) / abs(start_value) * 100.0


def _line_system_trend(results: list[dict], *, system_type: str, label: str) -> dict:
    samples = [
        sample
        for result in sorted(results, key=lambda item: int(item.get("forecast_hour") or 0))
        if (sample := _line_system_sample(result, system_type)) is not None
    ]
    east_west_labels = {"eastward": "东移", "westward": "西移", "stable": "经向少变", "unknown": "未知"}
    north_south_labels = {"northward": "北抬", "southward": "南落", "stable": "纬向少变", "unknown": "未知"}
    count_labels = {"increasing": "增多", "decreasing": "减少", "stable": "持平", "unknown": "未知"}
    length_labels = {"lengthening": "增长", "shortening": "缩短", "stable": "少变", "unknown": "未知"}
    confidence_labels = {"strengthening": "增强", "weakening": "减弱", "stable": "少变", "unknown": "未知"}

    if len(samples) < 2:
        return {
            "system_type": system_type,
            "label": label,
            "geometry_role": "line",
            "available": False,
            "samples": samples,
            "position_change": {
                "east_west": _empty_change(east_west_labels),
                "north_south": _empty_change(north_south_labels),
            },
            "count_change": _empty_change(count_labels),
            "length_change": _empty_change(length_labels),
            "confidence_change": _empty_change(confidence_labels),
            "trend_summary": f"{label}时效演变样本不足。",
        }

    start = samples[0]
    end = samples[-1]
    delta_lon = float(end["mean_center_lon"]) - float(start["mean_center_lon"])
    delta_lat = float(end["mean_center_lat"]) - float(start["mean_center_lat"])
    delta_count = int(end["object_count"]) - int(start["object_count"])
    delta_length = float(end["mean_axis_length_degrees"]) - float(start["mean_axis_length_degrees"])
    length_percent = _percent_delta(float(end["mean_axis_length_degrees"]), float(start["mean_axis_length_degrees"]))
    start_confidence = _as_float(start.get("mean_confidence"))
    end_confidence = _as_float(end.get("mean_confidence"))
    delta_confidence = None if start_confidence is None or end_confidence is None else end_confidence - start_confidence

    east_west_direction = _direction_change(
        delta_lon,
        threshold=0.25,
        positive="eastward",
        negative="westward",
        stable="stable",
    )
    north_south_direction = _direction_change(
        delta_lat,
        threshold=0.25,
        positive="northward",
        negative="southward",
        stable="stable",
    )
    count_direction = _direction_change(
        float(delta_count),
        threshold=0.0,
        positive="increasing",
        negative="decreasing",
        stable="stable",
    )
    length_direction = _direction_change(
        length_percent,
        threshold=5.0,
        positive="lengthening",
        negative="shortening",
        stable="stable",
    )
    confidence_direction = _direction_change(
        delta_confidence,
        threshold=0.03,
        positive="strengthening",
        negative="weakening",
        stable="stable",
    )

    return {
        "system_type": system_type,
        "label": label,
        "geometry_role": "line",
        "available": True,
        "baseline_forecast_hour": start["forecast_hour"],
        "target_forecast_hour": end["forecast_hour"],
        "samples": samples,
        "position_change": {
            "east_west": {
                "direction": east_west_direction,
                "label": _change_label(east_west_direction, east_west_labels),
                "delta_lon": round(delta_lon, 3),
            },
            "north_south": {
                "direction": north_south_direction,
                "label": _change_label(north_south_direction, north_south_labels),
                "delta_lat": round(delta_lat, 3),
            },
        },
        "count_change": {
            "direction": count_direction,
            "label": _change_label(count_direction, count_labels),
            "delta_count": delta_count,
        },
        "length_change": {
            "direction": length_direction,
            "label": _change_label(length_direction, length_labels),
            "delta_degrees": round(delta_length, 3),
            "delta_percent": round(length_percent, 2) if length_percent is not None else None,
        },
        "confidence_change": {
            "direction": confidence_direction,
            "label": _change_label(confidence_direction, confidence_labels),
            "delta_confidence": round(delta_confidence, 3) if delta_confidence is not None else None,
        },
        "trend_summary": (
            f"{label}从 +{start['forecast_hour']}h 到 +{end['forecast_hour']}h "
            f"{_change_label(east_west_direction, east_west_labels)}、"
            f"{_change_label(north_south_direction, north_south_labels)}，"
            f"对象{_change_label(count_direction, count_labels)}，"
            f"轴线长度{_change_label(length_direction, length_labels)}，"
            f"平均置信度{_change_label(confidence_direction, confidence_labels)}。"
        ),
    }


def _situation_evolution(results: list[dict], subtropical_high_trend: dict | None = None) -> dict:
    sorted_results = sorted(results, key=lambda item: int(item.get("forecast_hour") or 0))
    start_hour = _as_int(sorted_results[0].get("forecast_hour")) if sorted_results else None
    end_hour = _as_int(sorted_results[-1].get("forecast_hour")) if sorted_results else None
    items = [
        subtropical_high_trend or _subtropical_high_trend(results),
        _line_system_trend(results, system_type="trough_candidate", label="槽线"),
        _line_system_trend(results, system_type="ridge_candidate", label="脊线"),
        _line_system_trend(results, system_type="low_level_jet", label="低空急流"),
        _line_system_trend(results, system_type="moisture_transport", label="水汽输送"),
    ]
    available_items = [item for item in items if item.get("available")]
    if available_items:
        summaries = [str(item.get("trend_summary") or "").rstrip("。") for item in available_items[:5]]
        trend_summary = "天气形势演变：" + "；".join(summary for summary in summaries if summary) + "。"
    else:
        trend_summary = "天气形势演变样本不足。"
    return {
        "available": bool(available_items),
        "baseline_forecast_hour": start_hour,
        "target_forecast_hour": end_hour,
        "trend_summary": trend_summary,
        "items": items,
    }


@router.post("/situations")
def diagnose_situations(request: NafpBatchSituationRequest):
    hours = _dedupe_forecast_hours(request.forecast_hours)
    if not hours:
        raise ApiError(40001, "forecast_hours is required", status_code=400)
    root = _resolve_nafp_root(request.data_code, request.root)
    results: list[dict] = []
    failed: list[dict] = []
    for hour in hours:
        try:
            results.append(_diagnose_situation_or_error(root, request.run_time, hour))
        except ApiError as exc:
            failed.append(
                {
                    "forecast_hour": hour,
                    "code": exc.code,
                    "msg": exc.msg,
                    "error": exc.data.get("error") if isinstance(exc.data, dict) else None,
                }
            )
    subtropical_high_trend = _subtropical_high_trend(results)
    return ok(
        {
            "data_code": request.data_code,
            "run_time": request.run_time,
            "forecast_hours": hours,
            "result_count": len(results),
            "failed_count": len(failed),
            "subtropical_high_trend": subtropical_high_trend,
            "situation_evolution": _situation_evolution(results, subtropical_high_trend),
            "results": results,
            "failed": failed,
        }
    )


@router.post("/precompute")
def precompute_situations(request: NafpPrecomputeRequest):
    hours = _dedupe_forecast_hours(request.forecast_hours)
    if not hours:
        raise ApiError(40001, "forecast_hours is required", status_code=400)
    root = _resolve_nafp_root(request.data_code, request.root)
    entries: list[dict] = []
    failed: list[dict] = []
    for hour in hours:
        try:
            result, cache_meta = _diagnose_situation_cached_or_error(
                root,
                request.run_time,
                hour,
                force=request.force,
            )
            entries.append(
                {
                    "forecast_hour": int(hour),
                    "cache_status": cache_meta["cache_status"],
                    "compute_ms": cache_meta["compute_ms"],
                    "system_count": len(result.get("systems") or []),
                    "risk_count": len(result.get("risk_diagnoses") or []),
                }
            )
        except ApiError as exc:
            failed.append(
                {
                    "forecast_hour": hour,
                    "code": exc.code,
                    "msg": exc.msg,
                    "error": exc.data.get("error") if isinstance(exc.data, dict) else None,
                }
            )
    computed_count = sum(1 for entry in entries if entry["cache_status"] in {"computed", "refreshed"})
    hit_count = sum(1 for entry in entries if entry["cache_status"] == "hit")
    return ok(
        {
            "data_code": request.data_code,
            "run_time": request.run_time,
            "forecast_hours": hours,
            "force": request.force,
            "computed_count": computed_count,
            "hit_count": hit_count,
            "failed_count": len(failed),
            "entries": entries,
            "failed": failed,
            "cache": nafp_situation_cache_info(),
        }
    )


@router.get("/area-risks")
def nafp_area_risks(
    data_code: str | None = None,
    root: str | None = None,
    run_time: str = Query(...),
    town_code: str | None = None,
    region_code: str | None = None,
    region_level: str | None = None,
    risk_type: str | None = None,
    forecast_hour_start: int | None = None,
    forecast_hour_end: int | None = None,
    valid_start: str | None = None,
    valid_end: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    include_evidence: bool = True,
    include_samples: bool = False,
):
    resolved_root = _resolve_nafp_root(data_code, root)
    risk_types = _resolve_risk_types(risk_type)
    scope = _resolve_area_scope(town_code, region_code, region_level)
    hours = _resolve_area_forecast_hours(
        data_code=data_code,
        run_time=run_time,
        forecast_hour_start=forecast_hour_start,
        forecast_hour_end=forecast_hour_end,
        valid_start=valid_start,
        valid_end=valid_end,
        start_time=start_time,
        end_time=end_time,
    )
    result = evaluate_area_risks(
        root=resolved_root,
        run_time=run_time,
        forecast_hours=hours,
        towns=scope["towns"],
        risk_types=risk_types,
        include_evidence=include_evidence,
        include_samples=include_samples,
    )
    return ok(
        {
            "data_code": data_code,
            "root": str(resolved_root),
            "run_time": parse_run_time(run_time).isoformat(),
            "scope": scope["scope"],
            "forecast_hours": hours,
            "risk_types": risk_types,
            "risk_metadata": area_risk_metadata(risk_types),
            "items": result["items"],
            "failed": result["failed"],
            "summary": result["summary"],
        }
    )


@router.get("/features")
def nafp_features(
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
    types: Optional[str] = Query(default=None),
):
    resolved_root = _resolve_nafp_root(data_code, root)
    result = _diagnose_situation_or_error(resolved_root, run_time, forecast_hour)
    return ok(
        nafp_situation_to_feature_collection(
            result,
            requested_types=parse_feature_types(types),
            data_code=data_code,
            root=str(resolved_root),
        )
    )


@router.post("/point")
def diagnose_point(request: NafpPointRequest):
    try:
        root = resolve_data_root(request.data_code, request.root)
    except DataSourceError as exc:
        raise ApiError(40004, "invalid data code", status_code=400, data={"error": str(exc)})
    if not root.exists() or not root.is_dir():
        raise ApiError(40004, "invalid NAFP root", status_code=400)
    try:
        return ok(
            diagnose_nafp_point(
                root=root,
                run_time=request.run_time,
                forecast_hour=request.forecast_hour,
                lat=request.lat,
                lon=request.lon,
            )
        )
    except FileNotFoundError as exc:
        raise ApiError(
            40404,
            "required NAFP product not found",
            status_code=404,
            data={"error": str(exc)},
        )
    except Exception as exc:
        raise ApiError(
            50002,
            "NAFP point diagnosis failed",
            status_code=500,
            data={"error": str(exc)},
        )


def _load_layer_or_error(
    layer_id: str,
    data_code: str | None,
    root: str | None,
    run_time: str,
    forecast_hour: int,
) -> dict:
    try:
        return load_nafp_layer(
            layer_id,
            data_code=data_code,
            root=root,
            run_time=run_time,
            forecast_hour=forecast_hour,
        )
    except DataSourceError as exc:
        raise ApiError(40004, "invalid data code", status_code=400, data={"error": str(exc)}) from exc
    except KeyError as exc:
        raise ApiError(40405, "NAFP layer not supported", status_code=404, data={"error": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise ApiError(40404, "required NAFP product not found", status_code=404, data={"error": str(exc)}) from exc
    except Exception as exc:
        raise ApiError(50003, "NAFP layer rendering failed", status_code=500, data={"error": str(exc)}) from exc


@router.get("/layers/{layer_id}/metadata")
def nafp_layer_metadata(
    layer_id: str,
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
):
    layer = _load_layer_or_error(layer_id, data_code, root, run_time, forecast_hour)
    return ok(layer_metadata(layer))


@router.get("/layers/{layer_id}/grid")
def nafp_layer_grid(
    layer_id: str,
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
    max_cells: int = Query(default=12000, ge=100, le=50000),
):
    layer = _load_layer_or_error(layer_id, data_code, root, run_time, forecast_hour)
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


@router.get("/layers/{layer_id}/contours")
def nafp_layer_contours(
    layer_id: str,
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
    levels: Optional[str] = Query(default=None),
    interval: Optional[float] = Query(default=None),
    max_segments: Optional[int] = Query(default=None, ge=100, le=50000),
):
    layer = _load_layer_or_error(layer_id, data_code, root, run_time, forecast_hour)
    cfg = load_layers().get(layer_id, {})
    contour_cfg = cfg.get("contour") or {}
    return ok(
        contours_to_geojson(
            layer["layer_id"],
            layer["title"],
            layer["unit"],
            layer["values"],
            lat=layer["lat"],
            lon=layer["lon"],
            levels=parse_contour_levels(levels) or contour_cfg.get("levels"),
            interval=interval or contour_cfg.get("interval"),
            max_segments=max_segments or int(contour_cfg.get("max_segments", 12000)),
        )
    )
