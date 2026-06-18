from __future__ import annotations

from fastapi import APIRouter

from backend.app.responses import ApiError, ok
from backend.app.schemas import DiagnoseJobRequest
from backend.app.services.jobs import load_job, run_diagnosis_job


router = APIRouter(prefix="/jobs", tags=["public-jobs"])


@router.post("/diagnose")
def diagnose_job(request: DiagnoseJobRequest):
    job = run_diagnosis_job(request)
    if job.status == "failed":
        raise ApiError(
            50001,
            "diagnosis failed",
            status_code=500,
            data=job.model_dump(),
        )
    return ok(job.model_dump())


@router.get("/{job_id}")
def get_job(job_id: str):
    job = load_job(job_id)
    return ok(job.model_dump())
