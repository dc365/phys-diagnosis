from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.responses import ApiError, ok
from backend.app.services.data_sources import DataSourceError, resolve_data_root
from weather_diag.diagnosis.nafp_features import nafp_situation_to_feature_collection, parse_feature_types
from weather_diag.diagnosis.nafp_precompute import (
    load_precomputed_result,
    precompute_status,
    precomputed_result_exists,
    schedule_single_if_missing,
    submit_precompute_job,
)


class NafpPrecomputeRequest(BaseModel):
    data_code: str | None = None
    root: str | None = None
    run_time: str
    forecast_hours: list[int]
    force: bool = False


router = APIRouter(prefix="/diagnosis/nafp/precompute", tags=["public-diagnosis-precompute"])


def _resolve_root(data_code: str | None, root: str | None):
    try:
        resolved = resolve_data_root(data_code, root)
    except DataSourceError as exc:
        raise ApiError(40004, "invalid data code", status_code=400, data={"error": str(exc)}) from exc
    if not resolved.exists() or not resolved.is_dir():
        raise ApiError(40004, "invalid NAFP root", status_code=400)
    return resolved


def _dedupe_hours(hours: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in hours:
        hour = int(raw)
        if hour in seen:
            continue
        seen.add(hour)
        out.append(hour)
    return out


@router.get("/status")
def get_precompute_status():
    return ok(precompute_status())


@router.post("")
def schedule_precompute_compat(request: NafpPrecomputeRequest):
    # Compatibility with the existing map page: scheduling a job is cheap and
    # asynchronous. It does not compute again inside the map request thread.
    return schedule_precompute(request)


@router.post("/run")
def schedule_precompute(request: NafpPrecomputeRequest):
    hours = _dedupe_hours(request.forecast_hours)
    if not hours:
        raise ApiError(40001, "forecast_hours is required", status_code=400)
    root = _resolve_root(request.data_code, request.root)
    job = submit_precompute_job(
        root=root,
        run_time=request.run_time,
        forecast_hours=hours,
        data_code=request.data_code,
        force=request.force,
        background=True,
    )
    return ok(job)


@router.get("/result")
def get_precomputed_result(
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
):
    resolved_root = _resolve_root(data_code, root)
    try:
        return ok(load_precomputed_result(resolved_root, run_time, forecast_hour, data_code))
    except FileNotFoundError as exc:
        job = schedule_single_if_missing(root=resolved_root, run_time=run_time, forecast_hour=forecast_hour, data_code=data_code)
        raise ApiError(
            40909,
            "precomputed NAFP result not ready",
            status_code=409,
            data={"run_time": run_time, "forecast_hour": forecast_hour, "queued_job": job},
        ) from exc


@router.get("/features")
def get_precomputed_features(
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
    types: Optional[str] = Query(default=None),
):
    resolved_root = _resolve_root(data_code, root)
    try:
        result = load_precomputed_result(resolved_root, run_time, forecast_hour, data_code)
    except FileNotFoundError as exc:
        job = schedule_single_if_missing(root=resolved_root, run_time=run_time, forecast_hour=forecast_hour, data_code=data_code)
        raise ApiError(
            40909,
            "precomputed NAFP result not ready",
            status_code=409,
            data={"run_time": run_time, "forecast_hour": forecast_hour, "queued_job": job},
        ) from exc
    return ok(
        nafp_situation_to_feature_collection(
            result,
            requested_types=parse_feature_types(types),
            data_code=data_code,
            root=str(resolved_root),
        )
    )


@router.get("/ready")
def is_precomputed_ready(
    run_time: str,
    forecast_hour: int,
    data_code: str | None = None,
    root: str | None = None,
):
    resolved_root = _resolve_root(data_code, root)
    return ok(
        {
            "ready": precomputed_result_exists(resolved_root, run_time, forecast_hour, data_code),
            "run_time": run_time,
            "forecast_hour": int(forecast_hour),
            "data_code": data_code,
        }
    )
