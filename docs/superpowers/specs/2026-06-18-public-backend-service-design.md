# Public Backend Service Design

## Context

The current MVP already has a Python/FastAPI backend, a `weather_diag` algorithm
package, demo NetCDF data, generated products, a static WebGIS frontend, and
tests. The next step is to make the backend stable enough for external systems
while preserving the current WebGIS workflow.

The first public-service version will keep the existing Python/FastAPI stack.
It will not introduce a separate Go gateway, database, Redis, or worker queue in
this iteration. Those remain future production options once the API contract is
stable.

## Goals

- Provide a stable API for both the existing WebGIS frontend and third-party
  callers.
- Let callers upload or reference NetCDF files, submit diagnosis jobs, poll job
  status, and read generated products.
- Keep existing product files and frontend endpoints compatible.
- Standardize API responses with compact `code`, `msg`, `data`, and `trace_id`
  fields.
- Add tests for the public service contract before implementation.

## Non-Goals

- User login, tenant isolation, API keys, or billing.
- Distributed asynchronous execution with Redis, Celery, RQ, Kafka, or similar.
- Rewriting the backend in Go.
- Replacing the existing diagnostic algorithms.
- Moving product storage into a database or object store.

## Recommended Approach

Implement a light service layer around the existing FastAPI app and
`weather_diag.pipeline.diagnose_file`.

Diagnosis may still execute synchronously inside the request for this version,
but the public contract should expose it as a job. This gives external callers a
stable polling model now and leaves room to move the execution into a real
worker later without changing client behavior.

## Architecture

### API Layer

The API layer owns request parsing, response envelopes, HTTP status mapping, and
backward-compatible route aliases for the current frontend.

Suggested modules:

- `backend/app/main.py`: app construction, static frontend mount, router
  registration.
- `backend/app/schemas.py`: Pydantic request and response models.
- `backend/app/responses.py`: envelope helpers and trace ID handling.
- `backend/app/api/v1/files.py`: public file upload and inspection routes.
- `backend/app/api/v1/jobs.py`: public diagnosis job submission and status
  routes.
- `backend/app/api/v1/runs.py`: public run metadata and product lookup routes.
- `backend/app/api/layers.py`: layer metadata, grid, and image routes.
- `backend/app/api/features.py`: weather-system feature routes.
- `backend/app/api/analysis.py`: generated analysis routes.

### Service Layer

The service layer owns file paths, job persistence, and calls into existing
pipeline code.

Suggested modules:

- `backend/app/services/files.py`: safe raw-file storage, file IDs, metadata.
- `backend/app/services/jobs.py`: job creation, status updates, persistence.
- `backend/app/services/runs.py`: product index and forecast-hour helpers.

### Algorithm Layer

The existing `weather_diag` package remains the algorithm and product-generation
layer. The public backend must call it through `diagnose_file(...)` rather than
duplicating diagnosis logic.

## Storage Contract

Keep current directories:

- Raw inputs: `data/raw`
- Products: `data/products/{run_id}`

Add a lightweight local job store:

- Job metadata: `data/jobs/{job_id}.json`

Each job record should include:

- `job_id`
- `status`: `queued`, `running`, `succeeded`, or `failed`
- `model`
- `run_id`
- `file_id` when uploaded through the API
- `file_path`
- `created_at`
- `started_at`
- `finished_at`
- `duration_ms`
- `error`
- `result` with product index data when the job succeeds

Because execution is synchronous in this version, `queued` may be transient. It
is still part of the contract for future async execution.

## Response Envelope

All new public routes should return:

```json
{
  "code": 0,
  "msg": "ok",
  "data": {},
  "trace_id": "..."
}
```

Error responses should return the same shape:

```json
{
  "code": 40401,
  "msg": "run not found",
  "data": null,
  "trace_id": "..."
}
```

The legacy frontend routes may keep their current raw payloads when needed for
compatibility. Public `/api/v1/...` routes should use the envelope consistently.

## Public Routes

### Health

- `GET /api/health`

Returns service status, version, data directory, and product directory. This
route may keep its current simple shape for frontend compatibility, but a
versioned public route should use the envelope if one is added later.

### Files

- `POST /api/v1/files/upload`
- `GET /api/v1/files/{file_id}`
- `GET /api/inspect?path=...`

Upload accepts multipart NetCDF files and stores them under `data/raw` using a
server-generated file ID. The response includes `file_id`, original filename,
stored path, size, and creation time.

`/api/inspect` stays compatible with the existing query parameter contract.

### Jobs

- `POST /api/v1/jobs/diagnose`
- `GET /api/v1/jobs/{job_id}`

`POST /api/v1/jobs/diagnose` accepts either an uploaded `file_id` or an
existing `file_path`, plus `model` and optional `run_id`.

The first version may complete the diagnosis before returning. The response
still includes `job_id`, `status`, `run_id`, and product index information so
clients can use the same polling contract that a future async backend will use.

### Runs

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/forecast-hours`
- `GET /api/v1/runs/{run_id}/variables`

These routes expose product metadata in a more third-party-friendly shape while
keeping the existing `/api/model-runs`, `/api/forecast-times`, and
`/api/variables` aliases for the frontend.

### Layers

- `GET /api/layers`
- `GET /api/layers/{layer_id}/metadata?run_id=...&forecast_hour=...`
- `GET /api/layers/{layer_id}/grid?run_id=...&forecast_hour=...`
- `GET /api/layers/{layer_id}/image?run_id=...&forecast_hour=...`

Keep current route shapes and payloads because the frontend consumes them
directly.

### Features

- `GET /api/features?run_id=...&forecast_hour=...`
- `GET /api/features/{feature_id}?run_id=...&forecast_hour=...`

Keep current GeoJSON-compatible payloads. These routes are already useful for
third-party callers because the product format is a standard GeoJSON feature
collection.

### Analysis

- `GET /api/analysis/situation?run_id=...&forecast_hour=...`
- `GET /api/analysis/heavy-rain?run_id=...&forecast_hour=...`
- `GET /api/analysis/convection?run_id=...&forecast_hour=...`

Keep current analysis payloads and document them as product-specific responses.

## Error Handling

New public service routes should map expected failures to explicit codes:

- `40001`: invalid request
- `40002`: unsupported model
- `40003`: missing file reference
- `40401`: run not found
- `40402`: job not found
- `40403`: file not found
- `50001`: diagnosis failed

Unexpected exceptions should still be logged and returned as `50001` with a
trace ID.

## Backward Compatibility

Existing frontend routes and response shapes should continue working:

- `/`
- `/static/*`
- `/api/model-runs`
- `/api/forecast-times`
- `/api/variables`
- `/api/layers/*`
- `/api/features*`
- `/api/analysis/*`
- `/api/jobs/generate-demo`
- `/api/jobs/diagnose`

Do not convert existing non-versioned routes to the new envelope in the first
service version. Add `/api/v1/...` route aliases for public callers where a
stable envelope is required.

## Testing

Implementation should follow test-first changes for new behavior:

- File upload stores a NetCDF file and returns a file record.
- Diagnosis job accepts `file_path`, creates a persisted job record, runs the
  existing pipeline, and returns `status=succeeded`.
- Diagnosis job failure records `status=failed` and exposes the error.
- Job lookup returns persisted metadata.
- Run metadata aliases return product information without breaking existing
  `/api/model-runs`.
- Error responses use `code`, `msg`, `data`, and `trace_id`.
- Existing tests continue passing.

Verification command:

```bash
.venv/bin/pytest -q
```

## Rollout

1. Add tests for the new public service routes and response envelope.
2. Add response helpers and Pydantic schemas.
3. Add file and job service modules with local JSON persistence.
4. Refactor FastAPI routes into focused routers while preserving old paths.
5. Update `docs/api.md` and README examples.
6. Run the full test suite.
