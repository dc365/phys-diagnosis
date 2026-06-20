from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.responses import ApiError, ok
from backend.app.services.data_sources import (
    DataSourceError,
    discover_nafp_run_inventory,
    list_data_sources,
)


router = APIRouter(prefix="/admin/data-sources", tags=["admin-data-sources"])


@router.get("")
def get_data_sources():
    return ok(list_data_sources())


@router.get("/{data_code}/nafp-runs")
def get_data_source_nafp_runs(
    data_code: str,
    max_run_times: int = Query(default=20, ge=1, le=200),
):
    try:
        return ok(discover_nafp_run_inventory(data_code=data_code, max_run_times=max_run_times))
    except DataSourceError as exc:
        raise ApiError(40403, str(exc), status_code=404) from exc
