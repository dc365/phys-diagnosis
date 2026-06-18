from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]


class FileRecord(BaseModel):
    file_id: str
    original_filename: str
    stored_path: str
    size: int
    created_at: str


class DiagnoseJobRequest(BaseModel):
    model: str = "ecmwf"
    file_id: str | None = None
    file_path: str | None = None
    run_id: str | None = None


class JobRecord(BaseModel):
    job_id: str
    status: JobStatus
    model: str = "ecmwf"
    run_id: str | None = None
    file_id: str | None = None
    file_path: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None


class RunSummary(BaseModel):
    run_id: str
    model: str | None = None
    forecast_hours: list[int] = Field(default_factory=list)
