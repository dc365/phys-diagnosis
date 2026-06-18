from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.responses import ApiError, ok
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


class NafpSituationRequest(BaseModel):
    root: str
    run_time: str
    forecast_hour: int


router = APIRouter(prefix="/diagnosis/nafp", tags=["public-diagnosis"])


@router.post("/situation")
def diagnose_situation(request: NafpSituationRequest):
    root = Path(request.root)
    if not root.exists() or not root.is_dir():
        raise ApiError(40004, "invalid NAFP root", status_code=400)
    try:
        return ok(
            diagnose_nafp_situation(
                root=root,
                run_time=request.run_time,
                forecast_hour=request.forecast_hour,
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
            "NAFP diagnosis failed",
            status_code=500,
            data={"error": str(exc)},
        )
