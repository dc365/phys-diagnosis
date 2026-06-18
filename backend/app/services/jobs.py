from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from backend.app.responses import ApiError
from backend.app.schemas import DiagnoseJobRequest, JobRecord
from backend.app.services.files import load_file
from weather_diag.config import CONFIG_DIR, JOBS_DIR, ensure_dirs
from weather_diag.pipeline import diagnose_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save_job(record: JobRecord) -> JobRecord:
    ensure_dirs()
    _job_path(record.job_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def load_job(job_id: str) -> JobRecord:
    path = _job_path(job_id)
    if not path.exists():
        raise ApiError(40402, "job not found", status_code=404)
    return JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _resolve_file_path(request: DiagnoseJobRequest) -> tuple[str | None, str]:
    if not (CONFIG_DIR / "models" / f"{request.model}.yaml").exists():
        raise ApiError(40002, "unsupported model", status_code=400)
    if request.file_id:
        record = load_file(request.file_id)
        return record.file_id, record.stored_path
    if request.file_path:
        return None, request.file_path
    raise ApiError(40003, "missing file reference", status_code=400)


def run_diagnosis_job(request: DiagnoseJobRequest) -> JobRecord:
    file_id, file_path = _resolve_file_path(request)
    job = JobRecord(
        job_id=uuid4().hex,
        status="queued",
        model=request.model,
        run_id=request.run_id,
        file_id=file_id,
        file_path=file_path,
        created_at=utc_now(),
    )
    save_job(job)

    start = perf_counter()
    job.status = "running"
    job.started_at = utc_now()
    save_job(job)

    try:
        result = diagnose_file(file_path, model=request.model, run_id=request.run_id)
        job.status = "succeeded"
        job.run_id = str(result.get("run_id") or request.run_id)
        job.result = result
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
    finally:
        job.finished_at = utc_now()
        job.duration_ms = int((perf_counter() - start) * 1000)
        save_job(job)

    return job
