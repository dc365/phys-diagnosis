# NAFP Situation Diagnosis Design

## Context

The project is shifting from a demo WebGIS-oriented MVP to a backend-centered
weather-situation diagnosis service. Frontend compatibility and visualization
are not priorities for this phase.

The real EC/NAFP test data lives at:

```text
/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC
```

This data is not a single multi-variable NetCDF file. It is a directory product
library organized as:

```text
{element}/{level}/{yyyy}/{mm}/{dd}/{cycle_hour}/{yymmddhh}.{forecast_hour}
```

Example:

```text
gh/500/2026/06/17/20/26061720.024
uv/850/2026/06/17/20/26061720.024
pv/300/2026/06/17/20/26061720.024
kindex/999/2026/06/17/20/26061720.024
```

The inspected sample has a 0.25-degree grid with 241 latitudes and 361
longitudes, covering approximately `lat=0..60` and `lon=60..150`. Some files are
plain NetCDF; others, such as sampled `gh` files, are gzip-compressed NetCDF
without a `.gz` extension. The reader must inspect the file magic bytes instead
of relying on suffixes.

## Goals

- Add a backend data adapter for the NAFP directory product structure.
- Build a single-forecast-hour situation diagnosis from real NAFP products.
- Produce structured weather systems, physical diagnostics, and evidence
  chains from numerical forecast grid fields.
- Tolerate missing optional fields and expose `missing_fields` instead of
  failing the whole diagnosis.
- Add a backend API endpoint for diagnosis requests, independent of frontend
  visualization.
- Keep existing demo functionality available, but do not spend effort preserving
  frontend response compatibility in this phase.

## Non-Goals

- Building or changing a frontend visualization.
- Full multi-cycle or multi-forecast-hour batch processing.
- Human editing of fronts, troughs, or weather-system boundaries.
- Deep learning-based feature recognition.
- Database, object storage, user login, or permission management.
- Perfect operational thresholds for all regions. Initial thresholds remain
  rule-based and must later be calibrated with historical cases.

## Real Data Contract

### Product Path

The adapter receives:

- `root`: NAFP product root directory.
- `run_time`: cycle time, for example `2026-06-17T20:00:00`.
- `forecast_hour`: integer lead time, for example `24`.
- Optional `elements` or `diagnosis_profile` in future versions.

It resolves a product path by formatting:

```text
{root}/{element}/{level}/{yyyy}/{mm}/{dd}/{hh}/{yymmddhh}.{forecast_hour:03d}
```

`level=999` means a single-level, surface, accumulated, or layer-derived field
depending on the element.

### Required Reader Behavior

- Detect gzip-compressed NetCDF by magic bytes `1f 8b` and decompress it before
  opening with xarray.
- Open plain NetCDF directly.
- Normalize coordinate names to `lat` and `lon`.
- Sort latitude and longitude ascending if necessary.
- Preserve source metadata, including source path and NetCDF attributes.
- Return an in-memory 2D field object with:
  - `element`
  - `level`
  - `lat`
  - `lon`
  - `values`
  - `attrs`
  - `source_path`
  - `missing` flag and `reason` when absent.

### Initial Element Map

The first diagnosis profile should load these fields when available:

- Large-scale circulation:
  - `gh500`
  - `uv500`
  - `gh588` or `gh500 >= 588`, derived from `gh500`
- Low-level conditions:
  - `uv850`
  - `q850`
  - `rh850`
  - `div850`
  - `ttadv850`
- Upper-level dynamics:
  - `div200` preferred, with `div300` fallback
  - `pv300`
  - `pvadv300`
- Vertical motion:
  - `w700`
- Convection and precipitation:
  - `kindex`
  - `cape`
  - `cin`
  - `tcwv`
  - `rain6`
  - `shr850-200`

The adapter should support adding more element/level pairs without changing the
API contract.

For the first implementation, `gh500` is the only required field because it
anchors the large-scale situation diagnosis. All other fields are optional for a
partial diagnosis and must be reported in `missing_fields` when absent.

## Diagnosis Output Contract

The endpoint returns a backend JSON payload:

```json
{
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24,
  "valid_time": "2026-06-18T20:00:00",
  "domain": {
    "lat_min": 0.0,
    "lat_max": 60.0,
    "lon_min": 60.0,
    "lon_max": 150.0
  },
  "systems": [],
  "diagnostics": {},
  "evidence_chains": [],
  "missing_fields": [],
  "summary": ""
}
```

This payload is wrapped in the existing public `/api/v1` envelope:

```json
{
  "code": 0,
  "msg": "ok",
  "data": {},
  "trace_id": "..."
}
```

## Weather System Model

Each weather system should be explainable and traceable:

```json
{
  "id": "system-001",
  "type": "subtropical_high",
  "name": "500hPa subtropical high area",
  "level": "500",
  "geometry": {
    "type": "bbox",
    "bbox": [105.0, 20.0, 130.0, 35.0]
  },
  "confidence": 0.78,
  "diagnosis": "500hPa height field shows a >=588 dagpm area.",
  "evidence": []
}
```

Geometry can start as bounding boxes and representative points. Polygon or
GeoJSON output can be added later for visualization.

## Evidence Chain Model

Evidence chains link physical fields to a diagnosis conclusion:

```json
{
  "id": "evidence-001",
  "target_type": "heavy_rain_potential",
  "level": "moderate",
  "region": {
    "bbox": [105.0, 22.0, 122.0, 34.0]
  },
  "score": 0.67,
  "evidence": [
    {
      "field": "q850",
      "signal": "low-level moisture is sufficient",
      "value": "p75=12.8 g/kg",
      "weight": 0.2,
      "source_path": "..."
    },
    {
      "field": "div850",
      "signal": "low-level convergence is present",
      "value": "min=-18.4",
      "weight": 0.2,
      "source_path": "..."
    }
  ],
  "missing_evidence": []
}
```

If required or optional evidence is missing, the chain should include
`missing_evidence` and lower confidence rather than silently omitting the issue.

## Initial Algorithms

### Large-Scale Situation

- 500hPa subtropical high:
  - Use `gh500`.
  - Treat values around `588` as `588 dagpm` when the field ranges near
    `500..600`, and values around `5880` as gpm if ranges are near `5000..6000`.
  - Detect contiguous areas above the threshold and summarize area, bbox, max,
    and ridge orientation where possible.

- 500hPa trough and ridge candidates:
  - Use `gh500` anomaly relative to a smoothed or zonal-mean background.
  - Identify negative anomaly axes as trough candidates and positive anomaly
    axes as ridge candidates.
  - First implementation may return candidate centers and bboxes rather than
    polished lines.

### Low-Level Dynamics and Moisture

- Low-level convergence:
  - Use `div850` when available.
  - Negative divergence indicates convergence.
  - Detect contiguous areas below a percentile or threshold.

- Low-level jet:
  - Use `uv850`.
  - Compute wind speed from `u/v`.
  - Detect areas above a wind-speed threshold or high percentile.
  - Strengthen confidence when collocated with high `q850` or `tcwv`.

- Moisture transport:
  - Use `uv850` and `q850`.
  - Compute a simple moisture flux magnitude `q * wind_speed`.
  - Detect high-percentile belts or areas.

### Upper-Level Dynamics

- Upper divergence:
  - Prefer `div200`; use `div300` if `div200` is missing.
  - Positive divergence supports ascent below.

- Potential vorticity support:
  - Use `pv300` and `pvadv300` when available.
  - Summarize maxima, high-percentile areas, and overlap with downstream risk
    regions.

### Heavy Rain Potential

Combine available evidence:

- Moisture: `q850`, `tcwv`
- Moisture transport: derived from `uv850 * q850`
- Low-level convergence: `div850`
- Vertical motion: `w700` interpreted with dataset-specific sign and metadata
- Instability: `kindex`, `cape`
- Model precipitation: `rain6`

The output should include score, qualitative level, bbox, and evidence items
with the contributing source paths and numeric summaries.

### Convection Potential

Combine available evidence:

- Instability: `cape`, `cin`, `kindex`
- Deep-layer shear: `shr850-200`
- Low-level moisture: `q850`, `rh850`, `tcwv`
- Trigger: `div850`, `ttadv850`, local wind convergence
- Upper support: `div200/300`, `pv300`, `pvadv300`

The first implementation can be a transparent weighted score rather than a
calibrated operational severe-convection index.

## API Endpoint

Add:

```text
POST /api/v1/diagnosis/nafp/situation
```

Request:

```json
{
  "root": "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24
}
```

Response:

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "run_time": "2026-06-17T20:00:00",
    "forecast_hour": 24,
    "valid_time": "2026-06-18T20:00:00",
    "systems": [],
    "diagnostics": {},
    "evidence_chains": [],
    "missing_fields": [],
    "summary": ""
  },
  "trace_id": "..."
}
```

Errors:

- `40001`: invalid request
- `40004`: invalid NAFP root
- `40404`: required NAFP product not found
- `50002`: NAFP diagnosis failed

## File/Module Plan

Suggested new modules:

- `weather_diag/data/nafp.py`
  - NAFP path resolution, gzip-aware NetCDF opening, field loading.
- `weather_diag/diagnosis/__init__.py`
- `weather_diag/diagnosis/nafp_situation.py`
  - Single-forecast-hour diagnosis orchestration.
- `weather_diag/diagnosis/evidence.py`
  - Evidence item and evidence chain helpers.
- `backend/app/api/v1/diagnosis.py`
  - Public API route.

Existing modules to reuse:

- `weather_diag.features.*` for area and feature-detection helpers where they
  match the new evidence contract.
- `weather_diag.diagnostics.*` for derived wind, convergence, vorticity, and
  moisture calculations.
- `backend/app.responses` for the `/api/v1` envelope.

## Testing Strategy

Use the real NAFP test data for integration tests with a narrow sample:

- `run_time=2026-06-17T20:00:00`
- `forecast_hour=24`
- `root=/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC`

Tests should cover:

- Path resolution for element, level, run time, and forecast hour.
- Opening both plain NetCDF and gzip-compressed NetCDF without a `.gz` suffix.
- Loading `uv850` as a two-variable field.
- Loading `gh500` from a gzip-compressed file.
- Producing a diagnosis payload with run time, valid time, domain, systems,
  diagnostics, evidence chains, missing fields, and summary.
- API endpoint returns `code/msg/data/trace_id`.
- Missing optional fields are reported in `missing_fields`.

Verification command:

```bash
.venv/bin/pytest -q
```

## Rollout

1. Add test-first coverage around NAFP reader behavior.
2. Add test-first coverage around single-time diagnosis output shape.
3. Implement the NAFP reader and field bundle.
4. Implement the first diagnosis orchestration and evidence-chain scoring.
5. Add the `/api/v1/diagnosis/nafp/situation` route.
6. Update backend API documentation with the new algorithm endpoint.
7. Verify against the real NAFP sample and the full test suite.
