# Public Backend Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned public backend APIs for file upload, diagnosis jobs, run metadata, and standardized `code/msg/data/trace_id` responses while preserving existing WebGIS routes.

**Architecture:** Keep FastAPI as the service entrypoint and `weather_diag.pipeline.diagnose_file` as the algorithm boundary. Add focused response, schema, file-service, job-service, and `/api/v1` router modules; keep non-versioned routes backward-compatible.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, xarray/NetCDF pipeline, local JSON persistence, pytest, FastAPI TestClient.

---

## File Structure

- Create `backend/app/responses.py`: public envelope helpers, trace ID generation, and `ApiError`.
- Create `backend/app/schemas.py`: Pydantic request/response data models for public files, jobs, and runs.
- Create `backend/app/services/files.py`: upload persistence under `data/raw` and file metadata lookup.
- Create `backend/app/services/jobs.py`: local job JSON persistence and synchronous diagnosis job execution.
- Create `backend/app/api/v1/__init__.py`: versioned router package.
- Create `backend/app/api/v1/files.py`: `/api/v1/files/*` routes.
- Create `backend/app/api/v1/jobs.py`: `/api/v1/jobs/*` routes.
- Create `backend/app/api/v1/runs.py`: `/api/v1/runs/*` routes.
- Modify `backend/app/main.py`: register `/api/v1` routers, add exception handler, keep legacy routes.
- Create `tests/test_public_api.py`: contract tests for the new public API.
- Modify `docs/api.md`: document `/api/v1` routes and `msg` envelope.
- Modify `README.md`: add public service examples.

This workspace is not a git repository, so commit steps are replaced by test and content checkpoints.

## Task 1: Public API Contract Tests

**Files:**
- Create: `tests/test_public_api.py`
- Read: `backend/app/main.py`
- Read: `weather_diag/data/synthetic.py`

- [ ] **Step 1: Write failing tests for the public envelope, file upload, job execution, job lookup, run aliases, and errors**

Add this file:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.synthetic import create_demo_ecmwf_netcdf


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    return body


def test_public_file_upload_stores_netcdf_and_returns_envelope(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "upload_demo.nc")

    with source.open("rb") as fh:
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("upload_demo.nc", fh, "application/x-netcdf")},
        )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["data"]["file_id"]
    assert body["data"]["original_filename"] == "upload_demo.nc"
    assert body["data"]["size"] > 0
    assert Path(body["data"]["stored_path"]).exists()


def test_public_diagnose_job_accepts_file_path_and_can_be_looked_up(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "job_demo.nc")

    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "ecmwf",
            "file_path": str(source),
            "run_id": "public_api_job_demo",
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["job_id"]
    assert data["status"] == "succeeded"
    assert data["run_id"] == "public_api_job_demo"
    assert data["result"]["run_id"] == "public_api_job_demo"
    assert data["result"]["forecast_hours"]

    lookup = client.get(f"/api/v1/jobs/{data['job_id']}")

    assert lookup.status_code == 200
    lookup_body = envelope(lookup.json())
    assert lookup_body["code"] == 0
    assert lookup_body["data"]["job_id"] == data["job_id"]
    assert lookup_body["data"]["status"] == "succeeded"


def test_public_diagnose_job_records_failure_for_missing_file():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "ecmwf",
            "file_path": "data/raw/not_here.nc",
            "run_id": "missing_public_file",
        },
    )

    assert response.status_code == 500
    body = envelope(response.json())
    assert body["code"] == 50001
    assert body["msg"] == "diagnosis failed"
    assert body["data"]["status"] == "failed"
    assert body["data"]["error"]


def test_public_run_routes_wrap_existing_product_index():
    response = client.get("/api/v1/runs/ecmwf_demo")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["data"]["run_id"] == "ecmwf_demo"
    assert 24 in body["data"]["forecast_hours"]

    hours = client.get("/api/v1/runs/ecmwf_demo/forecast-hours")
    hours_body = envelope(hours.json())
    assert hours_body["data"] == [0, 6, 12, 24, 36]


def test_public_error_uses_msg_not_message():
    response = client.get("/api/v1/jobs/not-a-real-job")

    assert response.status_code == 404
    body = response.json()
    assert "msg" in body
    assert "message" not in body
    assert body["code"] == 40402
    assert body["data"] is None


def test_public_diagnose_requires_file_reference():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={"model": "ecmwf", "run_id": "missing_file_reference"},
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40003
    assert body["msg"] == "missing file reference"


def test_public_diagnose_rejects_unsupported_model():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "not_supported",
            "file_path": "data/raw/ecmwf_demo.nc",
            "run_id": "unsupported_model",
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40002
    assert body["msg"] == "unsupported model"
```

- [ ] **Step 2: Run the new tests and verify they fail because routes do not exist**

Run:

```bash
.venv/bin/pytest tests/test_public_api.py -q
```

Expected: failures with HTTP 404 responses for `/api/v1/...` routes.

## Task 2: Response Envelope and Schemas

**Files:**
- Create: `backend/app/responses.py`
- Create: `backend/app/schemas.py`
- Test: `tests/test_public_api.py`

- [ ] **Step 1: Implement the minimal response helper and API error**

Create `backend/app/responses.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def new_trace_id() -> str:
    return uuid4().hex


def envelope(data: Any = None, *, code: int = 0, msg: str = "ok", trace_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "msg": msg,
        "data": data,
        "trace_id": trace_id or new_trace_id(),
    }


def ok(data: Any = None, *, msg: str = "ok") -> dict[str, Any]:
    return envelope(data, msg=msg)


@dataclass
class ApiError(Exception):
    code: int
    msg: str
    status_code: int = 400
    data: Any = None


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(exc.data, code=exc.code, msg=exc.msg),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=envelope(exc.errors(), code=40001, msg="invalid request"),
    )
```

- [ ] **Step 2: Implement request and record models**

Create `backend/app/schemas.py`:

```python
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
```

- [ ] **Step 3: Run tests and verify the same route failures remain**

Run:

```bash
.venv/bin/pytest tests/test_public_api.py -q
```

Expected: failures are still missing `/api/v1/...` routes, not import errors.

## Task 3: File and Job Services

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/files.py`
- Create: `backend/app/services/jobs.py`
- Modify: `weather_diag/config.py`
- Test: `tests/test_public_api.py`

- [ ] **Step 1: Add the jobs directory constant**

Modify `weather_diag/config.py`:

```python
JOBS_DIR = DATA_DIR / "jobs"
```

Update `ensure_dirs()`:

```python
def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Create the services package**

Create `backend/app/services/__init__.py`:

```python
"""Application service helpers for the public backend API."""
```

- [ ] **Step 3: Implement file storage**

Create `backend/app/services/files.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from backend.app.responses import ApiError
from backend.app.schemas import FileRecord
from weather_diag.config import RAW_DIR, ensure_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata_path(file_id: str) -> Path:
    return RAW_DIR / f"{file_id}.json"


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in {".nc", ".cdf", ".nc4"} else ".nc"


def save_upload(file: UploadFile) -> FileRecord:
    ensure_dirs()
    file_id = uuid4().hex
    stored_path = RAW_DIR / f"{file_id}{_safe_suffix(file.filename)}"
    size = 0
    with stored_path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            out.write(chunk)
    record = FileRecord(
        file_id=file_id,
        original_filename=file.filename or stored_path.name,
        stored_path=str(stored_path),
        size=size,
        created_at=utc_now(),
    )
    _metadata_path(file_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def load_file(file_id: str) -> FileRecord:
    path = _metadata_path(file_id)
    if not path.exists():
        raise ApiError(40403, "file not found", status_code=404)
    return FileRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Implement job persistence and synchronous execution**

Create `backend/app/services/jobs.py`:

```python
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
```

- [ ] **Step 5: Run tests and verify failures move to missing routers**

Run:

```bash
.venv/bin/pytest tests/test_public_api.py -q
```

Expected: failures are still route-related because routers are not registered yet.

## Task 4: Versioned Public Routers

**Files:**
- Create: `backend/app/api/v1/__init__.py`
- Create: `backend/app/api/v1/files.py`
- Create: `backend/app/api/v1/jobs.py`
- Create: `backend/app/api/v1/runs.py`
- Modify: `backend/app/main.py`
- Test: `tests/test_public_api.py`

- [ ] **Step 1: Create the v1 router package**

Create `backend/app/api/v1/__init__.py`:

```python
"""Versioned public API routers."""
```

- [ ] **Step 2: Add file routes**

Create `backend/app/api/v1/files.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, UploadFile

from backend.app.responses import ok
from backend.app.services.files import load_file, save_upload


router = APIRouter(prefix="/files", tags=["public-files"])


@router.post("/upload")
def upload_file(file: UploadFile):
    record = save_upload(file)
    return ok(record.model_dump())


@router.get("/{file_id}")
def get_file(file_id: str):
    record = load_file(file_id)
    return ok(record.model_dump())
```

- [ ] **Step 3: Add job routes**

Create `backend/app/api/v1/jobs.py`:

```python
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
```

- [ ] **Step 4: Add run routes**

Create `backend/app/api/v1/runs.py`:

```python
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
```

- [ ] **Step 5: Register routers and the API error handler**

Modify `backend/app/main.py` imports:

```python
from backend.app.api.v1.files import router as public_files_router
from backend.app.api.v1.jobs import router as public_jobs_router
from backend.app.api.v1.runs import router as public_runs_router
from fastapi.exceptions import RequestValidationError

from backend.app.responses import ApiError, api_error_handler, validation_error_handler
```

Add after app creation:

```python
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(public_files_router, prefix="/api/v1")
app.include_router(public_jobs_router, prefix="/api/v1")
app.include_router(public_runs_router, prefix="/api/v1")
```

- [ ] **Step 6: Run the public API tests and fix only failures in the new public API**

Run:

```bash
.venv/bin/pytest tests/test_public_api.py -q
```

Expected: all tests in `tests/test_public_api.py` pass.

## Task 5: Full Regression and Docs

**Files:**
- Modify: `docs/api.md`
- Modify: `README.md`
- Test: all tests

- [ ] **Step 1: Update API documentation with the v1 envelope**

Add to `docs/api.md` near the top:

```markdown
## Public v1 Response Envelope

Third-party service routes under `/api/v1` return:

```json
{
  "code": 0,
  "msg": "ok",
  "data": {},
  "trace_id": "..."
}
```

The field is `msg`, not `message`.

## Public v1 Files

- `POST /api/v1/files/upload`
- `GET /api/v1/files/{file_id}`

## Public v1 Jobs

- `POST /api/v1/jobs/diagnose`
- `GET /api/v1/jobs/{job_id}`

`POST /api/v1/jobs/diagnose` accepts either:

```json
{
  "model": "ecmwf",
  "file_id": "uploaded-file-id",
  "run_id": "ecmwf_demo"
}
```

or:

```json
{
  "model": "ecmwf",
  "file_path": "data/raw/ecmwf_demo.nc",
  "run_id": "ecmwf_demo"
}
```

## Public v1 Runs

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/forecast-hours`
- `GET /api/v1/runs/{run_id}/variables`
```

- [ ] **Step 2: Update README with a third-party API example**

Add to `README.md` after the diagnosis curl example:

```markdown
### 对外服务 API 示例

第三方系统建议使用 `/api/v1` 接口，响应统一为 `code/msg/data/trace_id`：

```bash
curl -F "file=@data/raw/ecmwf_demo.nc" http://localhost:8000/api/v1/files/upload
```

```bash
curl -X POST http://localhost:8000/api/v1/jobs/diagnose \
  -H "Content-Type: application/json" \
  -d '{"model":"ecmwf","file_path":"data/raw/ecmwf_demo.nc","run_id":"ecmwf_demo"}'
```

```bash
curl http://localhost:8000/api/v1/runs/ecmwf_demo
```
```

- [ ] **Step 3: Run the full test suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: all tests pass. Existing warning about numpy binary compatibility may still appear if the environment is unchanged.

- [ ] **Step 4: Confirm legacy WebGIS routes still have raw payloads**

Run:

```bash
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
for path in ["/api/model-runs", "/api/forecast-times?run_id=ecmwf_demo", "/api/layers"]:
    response = client.get(path)
    print(path, response.status_code, type(response.json()).__name__)
PY
```

Expected: HTTP 200 responses; `/api/model-runs` and `/api/forecast-times` return lists, and `/api/layers` returns a dict rather than the v1 envelope.
