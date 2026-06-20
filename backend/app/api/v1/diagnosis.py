from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.responses import ApiError, ok
from backend.app.services.data_sources import DataSourceError, resolve_data_root
from weather_diag.config import load_layers
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


def _diagnose_situation_or_error(root, run_time: str, forecast_hour: int) -> dict:
    try:
        return diagnose_nafp_situation(
            root=root,
            run_time=run_time,
            forecast_hour=forecast_hour,
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
    return ok(
        {
            "data_code": request.data_code,
            "run_time": request.run_time,
            "forecast_hours": hours,
            "result_count": len(results),
            "failed_count": len(failed),
            "results": results,
            "failed": failed,
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
