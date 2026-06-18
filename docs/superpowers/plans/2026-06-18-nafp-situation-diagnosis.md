# NAFP Situation Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a backend-first NAFP directory-product reader, single-forecast-hour weather-situation diagnosis, evidence-chain output, and `/api/v1/diagnosis/nafp/situation` endpoint using the real EC/NAFP sample data.

**Architecture:** Add a gzip-aware NAFP data adapter under `weather_diag/data`, then add a focused diagnosis orchestrator under `weather_diag/diagnosis` that loads a field bundle, computes transparent rule-based systems and evidence chains, and exposes the result through a versioned FastAPI router. Keep visualization and frontend compatibility out of scope.

**Tech Stack:** Python 3, xarray, numpy, scipy.ndimage for connected components, FastAPI/Pydantic, pytest, real NAFP NetCDF sample data.

---

## File Structure

- Create `weather_diag/data/nafp.py`: NAFP path resolution, gzip-aware xarray open, `NafpField`, and optional field loading.
- Create `weather_diag/diagnosis/__init__.py`: diagnosis package marker.
- Create `weather_diag/diagnosis/nafp_situation.py`: single-time NAFP diagnosis orchestration, systems, diagnostics, evidence chains, and summaries.
- Create `backend/app/api/v1/diagnosis.py`: public diagnosis route.
- Modify `backend/app/main.py`: register the diagnosis router.
- Create `tests/test_nafp_reader.py`: reader integration tests against the real NAFP sample.
- Create `tests/test_nafp_situation.py`: diagnosis and API contract tests.
- Modify `docs/api.md`: document the new backend diagnosis endpoint.

This workspace is not a git repository, so commit steps are replaced by test checkpoints.

## Task 1: NAFP Reader Tests

**Files:**
- Create: `tests/test_nafp_reader.py`
- Create later: `weather_diag/data/nafp.py`

- [ ] **Step 1: Write failing reader tests**

Create `tests/test_nafp_reader.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from weather_diag.data.nafp import (
    NAFP_SAMPLE_ROOT,
    load_nafp_field,
    nafp_product_path,
    open_nafp_dataset,
)


RUN_TIME = datetime(2026, 6, 17, 20)


def test_nafp_product_path_formats_directory_layout():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    assert path == Path(
        "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC/"
        "gh/500/2026/06/17/20/26061720.024"
    )


def test_open_nafp_dataset_reads_gzip_netcdf_without_gz_suffix():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    ds = open_nafp_dataset(path)

    assert list(ds.sizes) == ["lat", "lon"]
    assert ds.sizes["lat"] == 241
    assert ds.sizes["lon"] == 361
    assert "gh" in ds.data_vars


def test_load_nafp_field_reads_multivariable_uv850():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "uv", "850", RUN_TIME, 24)

    assert field.key == "uv850"
    assert field.exists is True
    assert set(field.variables) == {"u", "v"}
    assert field.lat.shape == (241,)
    assert field.lon.shape == (361,)
    assert field.values["u"].shape == (241, 361)
    assert np.isfinite(field.values["u"]).any()
    assert field.source_path.endswith("uv/850/2026/06/17/20/26061720.024")


def test_load_nafp_field_marks_missing_optional_field():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "not_real", "999", RUN_TIME, 24, required=False)

    assert field.exists is False
    assert field.missing_reason == "not_found"
    assert field.values == {}
```

- [ ] **Step 2: Run reader tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_nafp_reader.py -q
```

Expected: import failure for `weather_diag.data.nafp`.

## Task 2: NAFP Reader Implementation

**Files:**
- Create: `weather_diag/data/nafp.py`
- Test: `tests/test_nafp_reader.py`

- [ ] **Step 1: Implement the NAFP reader**

Create `weather_diag/data/nafp.py`:

```python
from __future__ import annotations

import gzip
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


NAFP_SAMPLE_ROOT = Path("/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC")


@dataclass
class NafpField:
    element: str
    level: str
    key: str
    lat: np.ndarray
    lon: np.ndarray
    values: dict[str, np.ndarray]
    attrs: dict[str, Any]
    source_path: str
    exists: bool = True
    missing_reason: str | None = None
    variables: list[str] = field(default_factory=list)


def parse_run_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def nafp_product_path(root: str | Path, element: str, level: str | int, run_time: str | datetime, forecast_hour: int) -> Path:
    rt = parse_run_time(run_time)
    return (
        Path(root)
        / element
        / str(level)
        / f"{rt.year:04d}"
        / f"{rt.month:02d}"
        / f"{rt.day:02d}"
        / f"{rt.hour:02d}"
        / f"{rt:%y%m%d%H}.{int(forecast_hour):03d}"
    )


def _is_gzip(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(2) == b"\x1f\x8b"


def _normalize_coords(ds: xr.Dataset) -> xr.Dataset:
    rename = {}
    for candidate in ("latitude", "Latitude", "y"):
        if candidate in ds.coords or candidate in ds.dims:
            rename[candidate] = "lat"
            break
    for candidate in ("longitude", "Longitude", "x"):
        if candidate in ds.coords or candidate in ds.dims:
            rename[candidate] = "lon"
            break
    if rename:
        ds = ds.rename(rename)
    if "lat" in ds.coords:
        ds = ds.sortby("lat")
    if "lon" in ds.coords:
        ds = ds.sortby("lon")
    return ds


def open_nafp_dataset(path: str | Path) -> xr.Dataset:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if _is_gzip(path):
        with gzip.open(path, "rb") as src, tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
            tmp.write(src.read())
            tmp.flush()
            return _normalize_coords(xr.open_dataset(tmp.name).load())
    return _normalize_coords(xr.open_dataset(path).load())


def missing_field(element: str, level: str | int, root: str | Path, run_time: str | datetime, forecast_hour: int, reason: str) -> NafpField:
    path = nafp_product_path(root, element, level, run_time, forecast_hour)
    return NafpField(
        element=element,
        level=str(level),
        key=f"{element}{level}",
        lat=np.asarray([]),
        lon=np.asarray([]),
        values={},
        attrs={},
        source_path=str(path),
        exists=False,
        missing_reason=reason,
    )


def load_nafp_field(
    root: str | Path,
    element: str,
    level: str | int,
    run_time: str | datetime,
    forecast_hour: int,
    *,
    required: bool = True,
) -> NafpField:
    path = nafp_product_path(root, element, level, run_time, forecast_hour)
    if not path.exists():
        if required:
            raise FileNotFoundError(str(path))
        return missing_field(element, level, root, run_time, forecast_hour, "not_found")
    ds = open_nafp_dataset(path)
    lat = ds["lat"].values
    lon = ds["lon"].values
    values = {name: da.squeeze(drop=True).values.astype(float) for name, da in ds.data_vars.items()}
    return NafpField(
        element=element,
        level=str(level),
        key=f"{element}{level}",
        lat=lat,
        lon=lon,
        values=values,
        attrs=dict(ds.attrs),
        source_path=str(path),
        variables=list(values),
    )
```

- [ ] **Step 2: Run reader tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_nafp_reader.py -q
```

Expected: 4 passed.

## Task 3: Situation Diagnosis Tests

**Files:**
- Create: `tests/test_nafp_situation.py`
- Create later: `weather_diag/diagnosis/__init__.py`
- Create later: `weather_diag/diagnosis/nafp_situation.py`
- Create later: `backend/app/api/v1/diagnosis.py`
- Modify later: `backend/app/main.py`

- [ ] **Step 1: Write failing situation and API tests**

Create `tests/test_nafp_situation.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    return body


def test_diagnose_nafp_situation_returns_evidence_payload():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert result["run_time"] == "2026-06-17T20:00:00"
    assert result["forecast_hour"] == 24
    assert result["valid_time"] == "2026-06-18T20:00:00"
    assert result["domain"]["lat_min"] == 0.0
    assert result["domain"]["lat_max"] == 60.0
    assert result["domain"]["lon_min"] == 60.0
    assert result["domain"]["lon_max"] == 150.0
    assert result["diagnostics"]["gh500"]["max"] > 580
    assert any(system["type"] == "subtropical_high" for system in result["systems"])
    assert {chain["target_type"] for chain in result["evidence_chains"]} >= {
        "heavy_rain_potential",
        "convection_potential",
    }
    assert "summary" in result and result["summary"]


def test_diagnose_nafp_situation_reports_missing_optional_fields(tmp_path):
    root = tmp_path / "empty_nafp"
    required_dir = root / "gh" / "500" / "2026" / "06" / "17" / "20"
    required_dir.mkdir(parents=True)
    sample = NAFP_SAMPLE_ROOT / "gh" / "500" / "2026" / "06" / "17" / "20" / "26061720.024"
    (required_dir / "26061720.024").write_bytes(sample.read_bytes())

    result = diagnose_nafp_situation(
        root=root,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    missing = {item["field"] for item in result["missing_fields"]}
    assert "uv850" in missing
    assert "div850" in missing
    assert result["diagnostics"]["gh500"]["max"] > 580


def test_nafp_situation_api_returns_public_envelope():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/situation",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["data"]["diagnostics"]["gh500"]["max"] > 580
    assert body["data"]["evidence_chains"]


def test_nafp_situation_api_rejects_invalid_root():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/situation",
        json={
            "root": "/not/a/real/nafp/root",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40004
    assert body["msg"] == "invalid NAFP root"
```

- [ ] **Step 2: Run situation tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_nafp_situation.py -q
```

Expected: import failure for `weather_diag.diagnosis`.

## Task 4: Situation Diagnosis Implementation

**Files:**
- Create: `weather_diag/diagnosis/__init__.py`
- Create: `weather_diag/diagnosis/nafp_situation.py`
- Test: `tests/test_nafp_situation.py`

- [ ] **Step 1: Implement the diagnosis package marker**

Create `weather_diag/diagnosis/__init__.py`:

```python
"""Weather situation diagnosis orchestration."""
```

- [ ] **Step 2: Implement single-time NAFP diagnosis**

Create `weather_diag/diagnosis/nafp_situation.py` with functions that:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from weather_diag.data.nafp import NAFP_SAMPLE_ROOT, NafpField, load_nafp_field, parse_run_time


DEFAULT_OPTIONAL_FIELDS = [
    ("uv", "500", "uv500"),
    ("uv", "850", "uv850"),
    ("q", "850", "q850"),
    ("rh", "850", "rh850"),
    ("div", "850", "div850"),
    ("ttadv", "850", "ttadv850"),
    ("div", "200", "div200"),
    ("div", "300", "div300"),
    ("pv", "300", "pv300"),
    ("pvadv", "300", "pvadv300"),
    ("w", "700", "w700"),
    ("kindex", "999", "kindex"),
    ("cape", "999", "cape"),
    ("cin", "999", "cin"),
    ("tcwv", "999", "tcwv"),
    ("rain6", "999", "rain6"),
    ("shr850-200", "999", "shr850-200"),
]


def field_array(field: NafpField, preferred: str | None = None) -> np.ndarray | None:
    if not field.exists:
        return None
    if preferred and preferred in field.values:
        return field.values[preferred]
    if len(field.values) == 1:
        return next(iter(field.values.values()))
    return None


def finite_stats(values: np.ndarray) -> dict[str, Any]:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return {"min": None, "max": None, "mean": None, "p75": None, "p90": None}
    return {
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "p75": float(np.nanpercentile(valid, 75)),
        "p90": float(np.nanpercentile(valid, 90)),
    }


def bbox_for_mask(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> list[float] | None:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return None
    return [
        float(lon[int(xs.min())]),
        float(lat[int(ys.min())]),
        float(lon[int(xs.max())]),
        float(lat[int(ys.max())]),
    ]


def largest_component(mask: np.ndarray, min_points: int = 12) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    idx = int(np.argmax(sizes)) + 1
    if float(sizes[idx - 1]) < min_points:
        return np.zeros_like(mask, dtype=bool)
    return labels == idx


def load_field_bundle(root: str | Path, run_time: str | datetime, forecast_hour: int) -> tuple[dict[str, NafpField], list[dict[str, Any]]]:
    fields = {"gh500": load_nafp_field(root, "gh", "500", run_time, forecast_hour, required=True)}
    missing = []
    for element, level, key in DEFAULT_OPTIONAL_FIELDS:
        field = load_nafp_field(root, element, level, run_time, forecast_hour, required=False)
        fields[key] = field
        if not field.exists:
            missing.append({"field": key, "element": element, "level": level, "reason": field.missing_reason, "source_path": field.source_path})
    return fields, missing


def diagnose_nafp_situation(root: str | Path = NAFP_SAMPLE_ROOT, run_time: str | datetime = "2026-06-17T20:00:00", forecast_hour: int = 24) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    fields, missing = load_field_bundle(root, rt, forecast_hour)
    gh = field_array(fields["gh500"], "gh")
    if gh is None:
        raise FileNotFoundError("gh500")
    lat = fields["gh500"].lat
    lon = fields["gh500"].lon
    diagnostics = {"gh500": {**finite_stats(gh), "source_path": fields["gh500"].source_path}}
    systems = diagnose_systems(fields, diagnostics)
    evidence_chains = diagnose_evidence_chains(fields, diagnostics)
    valid_time = rt + timedelta(hours=int(forecast_hour))
    return {
        "run_time": rt.isoformat(),
        "forecast_hour": int(forecast_hour),
        "valid_time": valid_time.isoformat(),
        "domain": {"lat_min": float(lat.min()), "lat_max": float(lat.max()), "lon_min": float(lon.min()), "lon_max": float(lon.max())},
        "systems": systems,
        "diagnostics": diagnostics,
        "evidence_chains": evidence_chains,
        "missing_fields": missing,
        "summary": build_summary(systems, evidence_chains, missing),
    }
```

Also implement `diagnose_systems`, `diagnose_evidence_chains`, `score_level`, and `build_summary` so they:

- detect a subtropical high component from `gh500 >= 588` when `gh500.max() < 1000`, otherwise `gh500 >= 5880`;
- compute `uv850_speed`, `moisture_flux850`, and stats when `uv850` and `q850` exist;
- add a heavy-rain evidence chain with evidence from `q850`, `moisture_flux850`, `div850`, `w700`, `kindex`, `cape`, and `rain6` when present;
- add a convection evidence chain with evidence from `cape`, `cin`, `kindex`, `shr850-200`, `q850`, `div850`, `div200/div300`, `pv300`, and `pvadv300` when present;
- include `source_path` on every evidence item that comes from an input field;
- use score thresholds: `>=0.7` high, `>=0.45` moderate, otherwise low.

- [ ] **Step 3: Run situation tests and verify diagnosis import failures move to route failures or assertions**

Run:

```bash
.venv/bin/pytest tests/test_nafp_situation.py -q
```

Expected: diagnosis tests pass or only the API route test fails because the router is not registered yet.

## Task 5: Diagnosis API Route

**Files:**
- Create: `backend/app/api/v1/diagnosis.py`
- Modify: `backend/app/main.py`
- Test: `tests/test_nafp_situation.py`

- [ ] **Step 1: Add the diagnosis route**

Create `backend/app/api/v1/diagnosis.py`:

```python
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
        return ok(diagnose_nafp_situation(root=root, run_time=request.run_time, forecast_hour=request.forecast_hour))
    except FileNotFoundError as exc:
        raise ApiError(40404, "required NAFP product not found", status_code=404, data={"error": str(exc)})
    except Exception as exc:
        raise ApiError(50002, "NAFP diagnosis failed", status_code=500, data={"error": str(exc)})
```

- [ ] **Step 2: Register the diagnosis router**

Modify `backend/app/main.py`:

```python
from backend.app.api.v1.diagnosis import router as public_diagnosis_router
```

Then add:

```python
app.include_router(public_diagnosis_router, prefix="/api/v1")
```

- [ ] **Step 3: Run situation tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_nafp_situation.py -q
```

Expected: 4 passed.

## Task 6: Documentation and Full Verification

**Files:**
- Modify: `docs/api.md`
- Test: full suite

- [ ] **Step 1: Document the NAFP diagnosis endpoint**

Add to `docs/api.md`:

```markdown
## Public v1 NAFP Situation Diagnosis

- `POST /api/v1/diagnosis/nafp/situation`

Request:

```json
{
  "root": "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24
}
```

The response `data` contains `run_time`, `forecast_hour`, `valid_time`,
`domain`, `systems`, `diagnostics`, `evidence_chains`, `missing_fields`, and
`summary`. This endpoint is backend-focused and does not return visualization
tiles or frontend-specific payloads.
```

- [ ] **Step 2: Run the full test suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: all tests pass. The existing numpy binary-compatibility warning may still appear.

- [ ] **Step 3: Smoke the API through TestClient**

Run:

```bash
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT

client = TestClient(app)
resp = client.post("/api/v1/diagnosis/nafp/situation", json={
    "root": str(NAFP_SAMPLE_ROOT),
    "run_time": "2026-06-17T20:00:00",
    "forecast_hour": 24,
})
body = resp.json()
print(resp.status_code, body["code"], body["msg"])
print(body["data"]["summary"][:160])
print(len(body["data"]["systems"]), len(body["data"]["evidence_chains"]))
PY
```

Expected: `200 0 ok`, non-empty summary, and at least one evidence chain.

