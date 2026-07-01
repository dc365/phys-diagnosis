from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from backend.app.responses import ok
from weather_diag.diagnosis.auto_scheduler import (
    auto_scheduler_status,
    save_auto_schedule_config,
)


class AutoScheduleRequest(BaseModel):
    enabled: bool = True
    mode: str = "interval"
    interval_minutes: int = 60
    fixed_times: list[str] = Field(default_factory=list)
    tasks: dict[str, bool] = Field(default_factory=dict)


router = APIRouter(prefix="/admin/auto-diagnostics", tags=["admin-auto-diagnostics"])


@router.get("/schedule")
def get_auto_schedule():
    return ok(auto_scheduler_status())


@router.put("/schedule")
def update_auto_schedule(request: AutoScheduleRequest):
    return ok({"config": save_auto_schedule_config(request.model_dump())})
