from __future__ import annotations

import json

from fastapi import APIRouter

from backend.app.responses import ApiError, ok
from weather_diag.config import PRODUCTS_DIR
from weather_diag.pipeline import load_run_index


router = APIRouter(prefix="/runs", tags=["public-runs"])


@router.get("")
def list_runs():
    runs = []
    if PRODUCTS_DIR.exists():
        for path in sorted(PRODUCTS_DIR.iterdir()):
            index_path = path / "index.json"
            if index_path.exists():
                data = json.loads(index_path.read_text(encoding="utf-8"))
                runs.append(
                    {
                        "run_id": data.get("run_id", path.name),
                        "model": data.get("model"),
                        "forecast_hours": data.get("forecast_hours", []),
                    }
                )
    return ok(runs)


@router.get("/{run_id}")
def get_run(run_id: str):
    try:
        return ok(load_run_index(run_id))
    except FileNotFoundError:
        raise ApiError(40401, "run not found", status_code=404)


@router.get("/{run_id}/forecast-hours")
def get_forecast_hours(run_id: str):
    try:
        return ok(load_run_index(run_id).get("forecast_hours", []))
    except FileNotFoundError:
        raise ApiError(40401, "run not found", status_code=404)


@router.get("/{run_id}/variables")
def get_variables(run_id: str):
    try:
        return ok(load_run_index(run_id).get("variable_map", {}))
    except FileNotFoundError:
        raise ApiError(40401, "run not found", status_code=404)
