# Weather Render Engine Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first self-owned 2D weather rendering path: backend binary grid artifacts plus a MapLibre custom WebGL grid layer with GeoJSON fallback.

**Architecture:** The backend exposes compact grid metadata, float32 grid bytes, and style resources under additive `/api/render/...` routes. The frontend loads those artifacts through provider objects, builds WebGL-safe normalized textures, renders one active grid layer through a MapLibre custom layer, and keeps the existing GeoJSON grid route as the fallback path.

**Tech Stack:** Python 3, FastAPI, xarray, numpy, pytest, vanilla JavaScript, Node `node:test`, MapLibre GL JS custom layers, WebGL 1 compatible textures.

---

## Execution Notes

- Execute this plan in an isolated branch or worktree. The source checkout had unrelated dirty files when this plan was written.
- Do not stage unrelated work. Each commit step lists the exact files for that task.
- If a commit step would include files outside the task list, stop and inspect `git status --short`.
- The first WebGL implementation uploads a normalized unsigned-byte grid texture plus a color-ramp texture. The raw float32 array remains in memory for picking. This avoids depending on browser float texture extensions in Phase 1.

## File Structure

Create or modify these files:

- `weather_diag/io/render_artifact.py`: pure backend helpers for grid metadata, binary float32 encoding, style selection, and style resources.
- `backend/app/api/render.py`: additive FastAPI render routes under `/api/render`.
- `backend/app/main.py`: register the render router.
- `frontend/maplibre-utils.js`: URL helpers for render metadata, render data, and style routes.
- `frontend/weather-render-engine.js`: `GridProvider`, `StyleProvider`, coordinate picking, and typed-array validation.
- `frontend/weather-grid-layer.js`: MapLibre custom WebGL layer and texture helper functions.
- `frontend/map.html`: load the new browser scripts before `map.js`.
- `frontend/map.js`: use the render provider/layer first, fall back to the existing GeoJSON grid path.
- `docs/api.md`: document the additive render routes.
- `tests/test_render_artifacts.py`: backend helper tests.
- `tests/test_render_api.py`: FastAPI route tests.
- `tests/frontend-maplibre-utils.test.js`: URL helper tests.
- `tests/frontend-weather-render-engine.test.js`: provider and picking tests.
- `tests/frontend-weather-grid-layer.test.js`: texture-helper and custom-layer-shape tests.

## Task 1: Backend Render Artifact Helpers

**Files:**

- Create: `weather_diag/io/render_artifact.py`
- Create: `tests/test_render_artifacts.py`

- [ ] **Step 1: Write the failing backend helper tests**

Create `tests/test_render_artifacts.py` with this complete content:

```python
import numpy as np

from weather_diag.io.render_artifact import (
    build_grid_artifact_metadata,
    grid_to_float32_le,
    style_id_for_layer,
    style_resource,
)


def test_build_grid_artifact_metadata_preserves_grid_geometry_and_urls():
    data = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=float)

    md = build_grid_artifact_metadata(
        layer_id="heavy_rain_score",
        variable="heavy_rain_score",
        title="强降水潜势评分",
        unit="score",
        data=data,
        lat=np.array([20.0, 21.0]),
        lon=np.array([100.0, 101.0]),
        run_id="ecmwf demo",
        forecast_hour=24,
        style_id="score",
    )

    assert md["layer_id"] == "heavy_rain_score"
    assert md["encoding"] == "float32-le"
    assert md["shape"] == [2, 2]
    assert md["bounds"] == {"west": 100.0, "south": 20.0, "east": 101.0, "north": 21.0}
    assert md["grid"] == {
        "x_start": 100.0,
        "x_delta": 1.0,
        "x_size": 2,
        "y_start": 20.0,
        "y_delta": 1.0,
        "y_size": 2,
    }
    assert md["value"] == {"min": 1.0, "max": 4.0, "missing": "nan"}
    assert md["data_url"] == (
        "/api/render/layers/heavy_rain_score/grid/data?"
        "run_id=ecmwf+demo&forecast_hour=24"
    )
    assert md["fallback_geojson_url"] == (
        "/api/layers/heavy_rain_score/grid?run_id=ecmwf+demo&forecast_hour=24"
    )


def test_build_grid_artifact_metadata_supports_descending_latitude():
    md = build_grid_artifact_metadata(
        layer_id="z500",
        variable="z500",
        title="500hPa 位势高度",
        unit="gpm",
        data=np.array([[10.0], [20.0], [30.0]], dtype=float),
        lat=np.array([55.0, 54.75, 54.5]),
        lon=np.array([110.0]),
        run_id="demo",
        forecast_hour=0,
        style_id="default",
    )

    assert md["bounds"] == {"west": 110.0, "south": 54.5, "east": 110.0, "north": 55.0}
    assert md["grid"]["y_start"] == 55.0
    assert md["grid"]["y_delta"] == -0.25
    assert md["grid"]["y_size"] == 3


def test_grid_to_float32_le_returns_row_major_bytes():
    raw = grid_to_float32_le(np.array([[1.0, 2.5], [np.nan, 4.0]], dtype=float))

    values = np.frombuffer(raw, dtype="<f4")

    assert values.shape == (4,)
    assert np.allclose(values[:2], [1.0, 2.5])
    assert np.isnan(values[2])
    assert values[3] == 4.0


def test_style_id_for_layer_uses_config_then_layer_family():
    assert style_id_for_layer("x", {"style_id": "custom"}) == "custom"
    assert style_id_for_layer("heavy_rain_score", {}) == "score"
    assert style_id_for_layer("moisture_flux850", {}) == "moisture"
    assert style_id_for_layer("div850", {}) == "diverging"
    assert style_id_for_layer("z500", {}) == "default"


def test_style_resource_returns_stable_continuous_style():
    style = style_resource("score", domain=[0.0, 1.0])

    assert style["style_id"] == "score"
    assert style["type"] == "continuous"
    assert style["domain"] == [0.0, 1.0]
    assert style["colors"] == ["#fff7bc", "#fec44f", "#fb6a4a", "#bd0026"]
    assert style["missing_color"] == "rgba(0,0,0,0)"
    assert style["legend"]["ticks"] == [0.0, 0.25, 0.5, 0.75, 1.0]
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
python -m pytest -q tests/test_render_artifacts.py
```

Expected: fail with `ModuleNotFoundError: No module named 'weather_diag.io.render_artifact'`.

- [ ] **Step 3: Add the minimal render artifact helper implementation**

Create `weather_diag/io/render_artifact.py` with this complete content:

```python
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import numpy as np


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "score": {
        "colors": ["#fff7bc", "#fec44f", "#fb6a4a", "#bd0026"],
        "domain": [0.0, 1.0],
        "legend_title": "Potential score",
    },
    "moisture": {
        "colors": ["#edf8fb", "#b2e2e2", "#66c2a4", "#238b45"],
        "domain": None,
        "legend_title": "Moisture",
    },
    "diverging": {
        "colors": ["#2166ac", "#f7f7f7", "#b2182b"],
        "domain": None,
        "legend_title": "Anomaly",
    },
    "default": {
        "colors": ["#f7fbff", "#9ecae1", "#3182bd", "#08519c"],
        "domain": None,
        "legend_title": "Value",
    },
}


def _as_1d_float(values: np.ndarray, name: str) -> np.ndarray:
    coords = np.asarray(values, dtype=float)
    if coords.ndim != 1 or coords.size == 0:
        raise ValueError(f"{name} must be a non-empty 1D array")
    return coords


def _axis_metadata(values: np.ndarray, prefix: str) -> dict[str, float | int]:
    coords = _as_1d_float(values, prefix)
    delta = float(coords[1] - coords[0]) if coords.size > 1 else 1.0
    return {
        f"{prefix}_start": float(coords[0]),
        f"{prefix}_delta": delta,
        f"{prefix}_size": int(coords.size),
    }


def _finite_range(data: np.ndarray) -> tuple[float | None, float | None]:
    valid = np.asarray(data, dtype=float)
    valid = valid[np.isfinite(valid)]
    if not valid.size:
        return None, None
    return float(valid.min()), float(valid.max())


def style_id_for_layer(layer_id: str, cfg: dict[str, Any]) -> str:
    configured = cfg.get("style_id")
    if configured:
        return str(configured)
    if "score" in layer_id or "risk" in layer_id:
        return "score"
    if "moisture" in layer_id or "q" in layer_id:
        return "moisture"
    if any(token in layer_id for token in ("div", "adv", "vort", "omega")):
        return "diverging"
    return "default"


def build_grid_urls(layer_id: str, run_id: str, forecast_hour: int) -> tuple[str, str]:
    query = urlencode({"run_id": run_id, "forecast_hour": int(forecast_hour)})
    encoded_layer = layer_id.replace("/", "%2F")
    return (
        f"/api/render/layers/{encoded_layer}/grid/data?{query}",
        f"/api/layers/{encoded_layer}/grid?{query}",
    )


def build_grid_artifact_metadata(
    *,
    layer_id: str,
    variable: str,
    title: str,
    unit: str,
    data: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    run_id: str,
    forecast_hour: int,
    style_id: str,
) -> dict[str, Any]:
    arr = np.asarray(data, dtype=np.float32)
    lat_values = _as_1d_float(lat, "y")
    lon_values = _as_1d_float(lon, "x")
    if arr.shape != (lat_values.size, lon_values.size):
        raise ValueError("data shape must match lat/lon coordinate lengths")

    min_value, max_value = _finite_range(arr)
    data_url, fallback_url = build_grid_urls(layer_id, run_id, forecast_hour)

    return {
        "layer_id": layer_id,
        "variable": variable,
        "title": title,
        "unit": unit,
        "run_id": run_id,
        "forecast_hour": int(forecast_hour),
        "encoding": "float32-le",
        "shape": [int(lat_values.size), int(lon_values.size)],
        "bounds": {
            "west": float(np.nanmin(lon_values)),
            "south": float(np.nanmin(lat_values)),
            "east": float(np.nanmax(lon_values)),
            "north": float(np.nanmax(lat_values)),
        },
        "grid": {
            **_axis_metadata(lon_values, "x"),
            **_axis_metadata(lat_values, "y"),
        },
        "value": {
            "min": min_value,
            "max": max_value,
            "missing": "nan",
        },
        "style_id": style_id,
        "data_url": data_url,
        "fallback_geojson_url": fallback_url,
    }


def grid_to_float32_le(data: np.ndarray) -> bytes:
    return np.asarray(data, dtype="<f4").tobytes(order="C")


def _ticks(domain: list[float]) -> list[float]:
    start, end = float(domain[0]), float(domain[1])
    return [start + (end - start) * ratio for ratio in (0.0, 0.25, 0.5, 0.75, 1.0)]


def style_resource(style_id: str, *, domain: list[float] | None = None) -> dict[str, Any]:
    preset = STYLE_PRESETS.get(style_id, STYLE_PRESETS["default"])
    resolved_domain = domain or preset.get("domain") or [0.0, 1.0]
    return {
        "style_id": style_id if style_id in STYLE_PRESETS else "default",
        "type": "continuous",
        "colors": list(preset["colors"]),
        "domain": [float(resolved_domain[0]), float(resolved_domain[1])],
        "missing_color": "rgba(0,0,0,0)",
        "legend": {
            "title": str(preset["legend_title"]),
            "ticks": _ticks([float(resolved_domain[0]), float(resolved_domain[1])]),
        },
    }
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
python -m pytest -q tests/test_render_artifacts.py
```

Expected: `5 passed`.

- [ ] **Step 5: Commit Task 1 files**

Run in an isolated worktree:

```bash
git add tests/test_render_artifacts.py weather_diag/io/render_artifact.py
git commit -m "feat: add render grid artifact helpers"
```

Expected: one commit containing only the two files listed above.

## Task 2: Backend Render API Routes

**Files:**

- Create: `backend/app/api/render.py`
- Create: `tests/test_render_api.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing render API tests**

Create `tests/test_render_api.py` with this complete content:

```python
import numpy as np
import xarray as xr
from fastapi.testclient import TestClient

import backend.app.api.render as render_api
from backend.app.main import app


client = TestClient(app)


def _sample_dataset() -> xr.Dataset:
    ds = xr.Dataset(
        {"rain": (("lat", "lon"), np.array([[0.0, 0.5], [1.0, np.nan]], dtype=float))},
        coords={"lat": np.array([20.0, 21.0]), "lon": np.array([100.0, 101.0])},
    )
    ds["rain"].attrs["units"] = "score"
    return ds


def _patch_render_sources(monkeypatch):
    monkeypatch.setattr(render_api, "load_diagnostics", lambda run_id, forecast_hour: _sample_dataset())
    monkeypatch.setattr(
        render_api,
        "load_layers",
        lambda: {"rain_layer": {"variable": "rain", "title": "Rain layer", "unit": "score", "style_id": "score"}},
    )


def test_render_grid_metadata_route(monkeypatch):
    _patch_render_sources(monkeypatch)

    response = client.get("/api/render/layers/rain_layer/grid?run_id=demo&forecast_hour=24")

    assert response.status_code == 200
    body = response.json()
    assert body["layer_id"] == "rain_layer"
    assert body["variable"] == "rain"
    assert body["title"] == "Rain layer"
    assert body["unit"] == "score"
    assert body["encoding"] == "float32-le"
    assert body["shape"] == [2, 2]
    assert body["value"] == {"min": 0.0, "max": 1.0, "missing": "nan"}
    assert body["style_id"] == "score"
    assert body["data_url"] == "/api/render/layers/rain_layer/grid/data?run_id=demo&forecast_hour=24"
    assert body["fallback_geojson_url"] == "/api/layers/rain_layer/grid?run_id=demo&forecast_hour=24"


def test_render_grid_data_route_returns_float32_bytes(monkeypatch):
    _patch_render_sources(monkeypatch)

    response = client.get("/api/render/layers/rain_layer/grid/data?run_id=demo&forecast_hour=24")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    values = np.frombuffer(response.content, dtype="<f4")
    assert values.shape == (4,)
    assert np.allclose(values[:3], [0.0, 0.5, 1.0])
    assert np.isnan(values[3])


def test_render_style_route_uses_domain_query():
    response = client.get("/api/render/styles/score?min_value=0&max_value=1")

    assert response.status_code == 200
    body = response.json()
    assert body["style_id"] == "score"
    assert body["domain"] == [0.0, 1.0]
    assert body["legend"]["ticks"] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_render_grid_route_returns_404_for_missing_variable(monkeypatch):
    monkeypatch.setattr(render_api, "load_diagnostics", lambda run_id, forecast_hour: _sample_dataset())
    monkeypatch.setattr(render_api, "load_layers", lambda: {"bad": {"variable": "missing", "title": "Missing"}})

    response = client.get("/api/render/layers/bad/grid?run_id=demo&forecast_hour=24")

    assert response.status_code == 404
    assert "Layer variable not found" in response.text
```

- [ ] **Step 2: Run the render API tests and verify they fail**

Run:

```bash
python -m pytest -q tests/test_render_api.py
```

Expected: fail with `ModuleNotFoundError: No module named 'backend.app.api.render'`.

- [ ] **Step 3: Add the render router**

Create `backend/app/api/render.py` with this complete content:

```python
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from weather_diag.config import load_layers
from weather_diag.io.render_artifact import (
    build_grid_artifact_metadata,
    grid_to_float32_le,
    style_id_for_layer,
    style_resource,
)
from weather_diag.pipeline import load_diagnostics


router = APIRouter(prefix="/api/render", tags=["render"])


def _layer_data(layer_id: str, run_id: str, forecast_hour: int):
    ds = load_diagnostics(run_id, forecast_hour)
    layers_cfg = load_layers()
    cfg = layers_cfg.get(layer_id, {})
    var = cfg.get("variable", layer_id)
    if var not in ds.data_vars:
        raise HTTPException(404, f"Layer variable not found: {var}")
    return ds, cfg, var


@router.get("/layers/{layer_id}/grid")
def render_grid_metadata(layer_id: str, run_id: str, forecast_hour: int):
    ds, cfg, var = _layer_data(layer_id, run_id, forecast_hour)
    unit = ds[var].attrs.get("units", cfg.get("unit", ""))
    return build_grid_artifact_metadata(
        layer_id=layer_id,
        variable=var,
        title=cfg.get("title", var),
        unit=unit,
        data=ds[var].values,
        lat=ds.lat.values,
        lon=ds.lon.values,
        run_id=run_id,
        forecast_hour=forecast_hour,
        style_id=style_id_for_layer(layer_id, cfg),
    )


@router.get("/layers/{layer_id}/grid/data")
def render_grid_data(layer_id: str, run_id: str, forecast_hour: int):
    ds, cfg, var = _layer_data(layer_id, run_id, forecast_hour)
    raw = grid_to_float32_le(ds[var].values)
    return Response(content=raw, media_type="application/octet-stream")


@router.get("/styles/{style_id}")
def render_style(
    style_id: str,
    min_value: Optional[float] = Query(default=None),
    max_value: Optional[float] = Query(default=None),
):
    domain = None
    if min_value is not None and max_value is not None:
        domain = [float(min_value), float(max_value)]
    return style_resource(style_id, domain=domain)
```

- [ ] **Step 4: Register the render router**

Modify `backend/app/main.py`.

Add this import with the other router imports near the top:

```python
from backend.app.api.render import router as render_router
```

Add this registration after the existing `app.include_router(...)` calls:

```python
app.include_router(render_router)
```

- [ ] **Step 5: Run the render API tests and verify they pass**

Run:

```bash
python -m pytest -q tests/test_render_api.py
```

Expected: `4 passed`.

- [ ] **Step 6: Run existing public API smoke tests**

Run:

```bash
python -m pytest -q tests/test_public_api.py tests/test_grid_geojson.py
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2 files**

Run in an isolated worktree:

```bash
git add backend/app/api/render.py backend/app/main.py tests/test_render_api.py
git commit -m "feat: expose render grid artifact API"
```

Expected: one commit containing only the three files listed above.

## Task 3: Frontend Render URL Helpers

**Files:**

- Modify: `frontend/maplibre-utils.js`
- Modify: `tests/frontend-maplibre-utils.test.js`

- [ ] **Step 1: Add failing helper tests**

Modify the destructuring block in `tests/frontend-maplibre-utils.test.js` so it includes the new helpers:

```javascript
const {
  buildColorRampExpression,
  buildLayerGridUrl,
  buildRenderGridDataUrl,
  buildRenderGridMetadataUrl,
  buildRenderStyleUrl,
  featureDisplayLabel,
  forecastHourLabel,
  nextForecastHour,
  boundsToImageCoordinates,
  mergeFeatureCollections,
} = require('../frontend/maplibre-utils');
```

Append these tests to the same file:

```javascript
test('render grid metadata and data URLs preserve query parameters', () => {
  assert.equal(
    buildRenderGridMetadataUrl('heavy_rain_score', 'ecmwf demo', 24, 12345),
    '/api/render/layers/heavy_rain_score/grid?run_id=ecmwf%20demo&forecast_hour=24&_=12345',
  );
  assert.equal(
    buildRenderGridDataUrl('heavy_rain_score', 'ecmwf demo', 24),
    '/api/render/layers/heavy_rain_score/grid/data?run_id=ecmwf%20demo&forecast_hour=24',
  );
});

test('render style URL includes optional numeric domain', () => {
  assert.equal(
    buildRenderStyleUrl('score', 0, 1),
    '/api/render/styles/score?min_value=0&max_value=1',
  );
  assert.equal(
    buildRenderStyleUrl('score'),
    '/api/render/styles/score',
  );
});
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
node --test tests/frontend-maplibre-utils.test.js
```

Expected: fail because `buildRenderGridMetadataUrl`, `buildRenderGridDataUrl`, and `buildRenderStyleUrl` are not functions.

- [ ] **Step 3: Implement the render URL helpers**

Modify `frontend/maplibre-utils.js`.

Add these functions after `buildLayerGridUrl`:

```javascript
  function buildRenderGridMetadataUrl(layerId, runId, forecastHour, cacheBust) {
    const params = [
      ['run_id', runId],
      ['forecast_hour', forecastHour],
    ];
    if (cacheBust !== undefined) params.push(['_', cacheBust]);
    const query = buildQuery(params);
    return `/api/render/layers/${encodeURIComponent(layerId)}/grid?${query}`;
  }

  function buildRenderGridDataUrl(layerId, runId, forecastHour) {
    const query = buildQuery([
      ['run_id', runId],
      ['forecast_hour', forecastHour],
    ]);
    return `/api/render/layers/${encodeURIComponent(layerId)}/grid/data?${query}`;
  }

  function buildRenderStyleUrl(styleId, minValue, maxValue) {
    const params = [];
    if (minValue !== undefined && maxValue !== undefined) {
      params.push(['min_value', minValue], ['max_value', maxValue]);
    }
    const query = buildQuery(params);
    return query
      ? `/api/render/styles/${encodeURIComponent(styleId)}?${query}`
      : `/api/render/styles/${encodeURIComponent(styleId)}`;
  }
```

Add the functions to the returned object:

```javascript
    buildRenderGridDataUrl,
    buildRenderGridMetadataUrl,
    buildRenderStyleUrl,
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
node --test tests/frontend-maplibre-utils.test.js
```

Expected: all tests in `tests/frontend-maplibre-utils.test.js` pass.

- [ ] **Step 5: Commit Task 3 files**

Run in an isolated worktree:

```bash
git add frontend/maplibre-utils.js tests/frontend-maplibre-utils.test.js
git commit -m "feat: add render endpoint URL helpers"
```

Expected: one commit containing only the two files listed above.

## Task 4: Frontend Grid and Style Providers

**Files:**

- Create: `frontend/weather-render-engine.js`
- Create: `tests/frontend-weather-render-engine.test.js`

- [ ] **Step 1: Write failing provider tests**

Create `tests/frontend-weather-render-engine.test.js` with this complete content:

```javascript
const assert = require('node:assert/strict');
const test = require('node:test');

const {
  GridProvider,
  StyleProvider,
  axisIndex,
  gridIndexForLonLat,
} = require('../frontend/weather-render-engine');

function responseJson(data) {
  return {
    ok: true,
    async json() {
      return data;
    },
  };
}

function responseBuffer(array) {
  return {
    ok: true,
    async arrayBuffer() {
      return array.buffer.slice(array.byteOffset, array.byteOffset + array.byteLength);
    },
  };
}

test('axisIndex supports ascending and descending axes', () => {
  assert.equal(axisIndex(101, 100, 1, 3), 1);
  assert.equal(axisIndex(54.75, 55, -0.25, 3), 1);
  assert.equal(axisIndex(90, 100, 1, 3), null);
  assert.equal(axisIndex(100, 100, 0, 3), null);
});

test('gridIndexForLonLat returns row and column for valid point', () => {
  const metadata = {
    grid: { x_start: 100, x_delta: 1, x_size: 3, y_start: 20, y_delta: 1, y_size: 2 },
  };

  assert.deepEqual(gridIndexForLonLat(metadata, 101, 21), { row: 1, col: 1, index: 4 });
  assert.equal(gridIndexForLonLat(metadata, 120, 21), null);
});

test('GridProvider loads metadata and float32 data then supports picking', async () => {
  const metadata = {
    layer_id: 'rain',
    title: 'Rain',
    unit: 'score',
    style_id: 'score',
    shape: [2, 2],
    grid: { x_start: 100, x_delta: 1, x_size: 2, y_start: 20, y_delta: 1, y_size: 2 },
    value: { min: 0, max: 1, missing: 'nan' },
    data_url: '/data',
    fallback_geojson_url: '/fallback',
  };
  const values = new Float32Array([0, 0.5, 1, Number.NaN]);
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url.includes('/api/render/layers/rain/grid')) return responseJson(metadata);
    if (url === '/data') return responseBuffer(values);
    throw new Error(`unexpected url ${url}`);
  };

  const provider = new GridProvider({ fetchImpl });
  const loaded = await provider.load('rain', 'demo', 24);

  assert.equal(calls[0], '/api/render/layers/rain/grid?run_id=demo&forecast_hour=24');
  assert.equal(calls[1], '/data');
  assert.equal(loaded.values.length, 4);
  assert.deepEqual(provider.pick(101, 20), {
    layer_id: 'rain',
    title: 'Rain',
    unit: 'score',
    value: 0.5,
    row: 0,
    col: 1,
  });
  assert.equal(provider.pick(101, 21), null);
});

test('GridProvider rejects binary payloads with the wrong size', async () => {
  const metadata = {
    layer_id: 'rain',
    title: 'Rain',
    unit: 'score',
    style_id: 'score',
    shape: [2, 2],
    grid: { x_start: 100, x_delta: 1, x_size: 2, y_start: 20, y_delta: 1, y_size: 2 },
    value: { min: 0, max: 1, missing: 'nan' },
    data_url: '/data',
    fallback_geojson_url: '/fallback',
  };
  const fetchImpl = async (url) => {
    if (url.includes('/api/render/layers/rain/grid')) return responseJson(metadata);
    return responseBuffer(new Float32Array([1, 2]));
  };

  const provider = new GridProvider({ fetchImpl });

  await assert.rejects(
    () => provider.load('rain', 'demo', 24),
    /grid data length mismatch/,
  );
});

test('StyleProvider loads style resources with metadata domain', async () => {
  const fetchImpl = async (url) => {
    assert.equal(url, '/api/render/styles/score?min_value=0&max_value=1');
    return responseJson({ style_id: 'score', colors: ['#000000', '#ffffff'], domain: [0, 1] });
  };

  const provider = new StyleProvider({ fetchImpl });
  const style = await provider.load('score', { value: { min: 0, max: 1 } });

  assert.deepEqual(style.colors, ['#000000', '#ffffff']);
});
```

- [ ] **Step 2: Run provider tests and verify they fail**

Run:

```bash
node --test tests/frontend-weather-render-engine.test.js
```

Expected: fail because `frontend/weather-render-engine.js` does not exist.

- [ ] **Step 3: Implement providers**

Create `frontend/weather-render-engine.js` with this complete content:

```javascript
(function attachWeatherRenderEngine(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.WeatherRenderEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function createWeatherRenderEngine() {
  function okResponse(response, url) {
    if (!response || response.ok === false) {
      throw new Error(`request failed: ${url}`);
    }
    return response;
  }

  function axisIndex(value, start, delta, size) {
    if (!Number.isFinite(value) || !Number.isFinite(start) || !Number.isFinite(delta) || delta === 0) {
      return null;
    }
    const index = Math.round((value - start) / delta);
    if (index < 0 || index >= size) return null;
    return index;
  }

  function gridIndexForLonLat(metadata, lon, lat) {
    const grid = metadata?.grid || {};
    const col = axisIndex(Number(lon), Number(grid.x_start), Number(grid.x_delta), Number(grid.x_size));
    const row = axisIndex(Number(lat), Number(grid.y_start), Number(grid.y_delta), Number(grid.y_size));
    if (row === null || col === null) return null;
    return { row, col, index: row * Number(grid.x_size) + col };
  }

  function metadataUrl(layerId, runId, forecastHour) {
    const params = new URLSearchParams({ run_id: runId, forecast_hour: String(forecastHour) });
    return `/api/render/layers/${encodeURIComponent(layerId)}/grid?${params.toString()}`;
  }

  function styleUrl(styleId, metadata) {
    const params = new URLSearchParams();
    const min = metadata?.value?.min;
    const max = metadata?.value?.max;
    if (Number.isFinite(Number(min)) && Number.isFinite(Number(max))) {
      params.set('min_value', String(min));
      params.set('max_value', String(max));
    }
    const query = params.toString();
    return query
      ? `/api/render/styles/${encodeURIComponent(styleId)}?${query}`
      : `/api/render/styles/${encodeURIComponent(styleId)}`;
  }

  class GridProvider {
    constructor({ fetchImpl } = {}) {
      this.fetchImpl = fetchImpl || fetch.bind(globalThis);
      this.current = null;
    }

    async load(layerId, runId, forecastHour) {
      const mdUrl = metadataUrl(layerId, runId, forecastHour);
      const metadataResponse = okResponse(await this.fetchImpl(mdUrl), mdUrl);
      const metadata = await metadataResponse.json();

      const dataResponse = okResponse(await this.fetchImpl(metadata.data_url), metadata.data_url);
      const buffer = await dataResponse.arrayBuffer();
      const values = new Float32Array(buffer);
      const expected = Number(metadata.shape?.[0]) * Number(metadata.shape?.[1]);
      if (values.length !== expected) {
        throw new Error(`grid data length mismatch: expected ${expected}, got ${values.length}`);
      }

      this.current = { metadata, values };
      return this.current;
    }

    clear() {
      this.current = null;
    }

    pick(lon, lat) {
      if (!this.current) return null;
      const location = gridIndexForLonLat(this.current.metadata, lon, lat);
      if (!location) return null;
      const value = this.current.values[location.index];
      if (!Number.isFinite(value)) return null;
      return {
        layer_id: this.current.metadata.layer_id,
        title: this.current.metadata.title,
        unit: this.current.metadata.unit,
        value,
        row: location.row,
        col: location.col,
      };
    }
  }

  class StyleProvider {
    constructor({ fetchImpl } = {}) {
      this.fetchImpl = fetchImpl || fetch.bind(globalThis);
      this.cache = new Map();
    }

    async load(styleId, metadata) {
      const url = styleUrl(styleId || 'default', metadata);
      if (this.cache.has(url)) return this.cache.get(url);
      const response = okResponse(await this.fetchImpl(url), url);
      const style = await response.json();
      this.cache.set(url, style);
      return style;
    }
  }

  return {
    GridProvider,
    StyleProvider,
    axisIndex,
    gridIndexForLonLat,
    metadataUrl,
    styleUrl,
  };
});
```

- [ ] **Step 4: Run provider tests and verify they pass**

Run:

```bash
node --test tests/frontend-weather-render-engine.test.js
```

Expected: all tests in `tests/frontend-weather-render-engine.test.js` pass.

- [ ] **Step 5: Commit Task 4 files**

Run in an isolated worktree:

```bash
git add frontend/weather-render-engine.js tests/frontend-weather-render-engine.test.js
git commit -m "feat: add weather render providers"
```

Expected: one commit containing only the two files listed above.

## Task 5: MapLibre WebGL Grid Layer

**Files:**

- Create: `frontend/weather-grid-layer.js`
- Create: `tests/frontend-weather-grid-layer.test.js`

- [ ] **Step 1: Write failing WebGL helper tests**

Create `tests/frontend-weather-grid-layer.test.js` with this complete content:

```javascript
const assert = require('node:assert/strict');
const test = require('node:test');

const {
  WeatherGridLayer,
  buildColorRampBytes,
  buildNormalizedGridTexture,
  hexToRgba,
} = require('../frontend/weather-grid-layer');

test('hexToRgba parses six-digit hex colors', () => {
  assert.deepEqual(hexToRgba('#fec44f'), [254, 196, 79, 255]);
});

test('buildColorRampBytes converts style colors to rgba bytes', () => {
  const bytes = buildColorRampBytes({ colors: ['#000000', '#ffffff'] });

  assert.deepEqual(Array.from(bytes), [0, 0, 0, 255, 255, 255, 255, 255]);
});

test('buildNormalizedGridTexture maps values to red channel and missing alpha', () => {
  const texture = buildNormalizedGridTexture(
    new Float32Array([0, 0.5, 1, Number.NaN]),
    { shape: [2, 2], grid: { y_delta: 1 }, value: { min: 0, max: 1 } },
  );

  assert.equal(texture.width, 2);
  assert.equal(texture.height, 2);
  assert.deepEqual(Array.from(texture.bytes), [
    0, 0, 0, 255,
    128, 128, 128, 255,
    255, 255, 255, 255,
    0, 0, 0, 0,
  ]);
});

test('buildNormalizedGridTexture flips descending latitude into south-to-north texture rows', () => {
  const texture = buildNormalizedGridTexture(
    new Float32Array([1, 2, 3, 4]),
    { shape: [2, 2], grid: { y_delta: -1 }, value: { min: 1, max: 4 } },
  );

  assert.deepEqual(Array.from(texture.bytes.slice(0, 8)), [
    170, 170, 170, 255,
    255, 255, 255, 255,
  ]);
});

test('WeatherGridLayer exposes the MapLibre custom layer shape', () => {
  const layer = new WeatherGridLayer({ id: 'test-weather-grid', opacity: 0.5 });

  assert.equal(layer.id, 'test-weather-grid');
  assert.equal(layer.type, 'custom');
  assert.equal(layer.renderingMode, '2d');
  assert.equal(typeof layer.onAdd, 'function');
  assert.equal(typeof layer.render, 'function');
  assert.equal(typeof layer.update, 'function');
  assert.equal(typeof layer.clear, 'function');
});
```

- [ ] **Step 2: Run WebGL helper tests and verify they fail**

Run:

```bash
node --test tests/frontend-weather-grid-layer.test.js
```

Expected: fail because `frontend/weather-grid-layer.js` does not exist.

- [ ] **Step 3: Implement the custom layer and texture helpers**

Create `frontend/weather-grid-layer.js` with this complete content:

```javascript
(function attachWeatherGridLayer(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.WeatherGridLayer = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function createWeatherGridLayerModule() {
  function hexToRgba(hex) {
    const clean = String(hex || '').replace('#', '');
    if (!/^[0-9a-fA-F]{6}$/.test(clean)) return [0, 0, 0, 255];
    return [
      parseInt(clean.slice(0, 2), 16),
      parseInt(clean.slice(2, 4), 16),
      parseInt(clean.slice(4, 6), 16),
      255,
    ];
  }

  function buildColorRampBytes(style) {
    const colors = Array.isArray(style?.colors) && style.colors.length ? style.colors : ['#000000', '#ffffff'];
    const bytes = new Uint8Array(colors.length * 4);
    colors.forEach((color, index) => {
      bytes.set(hexToRgba(color), index * 4);
    });
    return bytes;
  }

  function buildNormalizedGridTexture(values, metadata) {
    const height = Number(metadata.shape?.[0]);
    const width = Number(metadata.shape?.[1]);
    const min = Number(metadata.value?.min);
    const max = Number(metadata.value?.max);
    const span = Number.isFinite(max - min) && max !== min ? max - min : 1;
    const bytes = new Uint8Array(width * height * 4);

    for (let row = 0; row < height; row += 1) {
      const sourceRow = Number(metadata.grid?.y_delta) < 0 ? height - 1 - row : row;
      for (let col = 0; col < width; col += 1) {
        const sourceIndex = sourceRow * width + col;
        const targetIndex = row * width + col;
        const value = values[sourceIndex];
        const offset = targetIndex * 4;
        if (!Number.isFinite(value)) {
          bytes[offset] = 0;
          bytes[offset + 1] = 0;
          bytes[offset + 2] = 0;
          bytes[offset + 3] = 0;
          continue;
        }
        const normalized = Math.max(0, Math.min(1, (Number(value) - min) / span));
        const encoded = Math.round(normalized * 255);
        bytes[offset] = encoded;
        bytes[offset + 1] = encoded;
        bytes[offset + 2] = encoded;
        bytes[offset + 3] = 255;
      }
    }

    return { width, height, bytes };
  }

  function createShader(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || 'shader compile failed');
    }
    return shader;
  }

  function createProgram(gl) {
    const vertex = createShader(gl, gl.VERTEX_SHADER, `
      attribute vec2 a_pos;
      attribute vec2 a_uv;
      uniform mat4 u_matrix;
      varying vec2 v_uv;
      void main() {
        gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
        v_uv = a_uv;
      }
    `);
    const fragment = createShader(gl, gl.FRAGMENT_SHADER, `
      precision mediump float;
      uniform sampler2D u_grid;
      uniform sampler2D u_ramp;
      uniform float u_opacity;
      varying vec2 v_uv;
      void main() {
        vec4 encoded = texture2D(u_grid, v_uv);
        if (encoded.a <= 0.0) discard;
        vec4 color = texture2D(u_ramp, vec2(encoded.r, 0.5));
        gl_FragColor = vec4(color.rgb, color.a * u_opacity);
      }
    `);
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || 'program link failed');
    }
    return program;
  }

  function createTexture(gl, width, height, bytes, linear) {
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, linear ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, linear ? gl.LINEAR : gl.NEAREST);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
    return texture;
  }

  class WeatherGridLayer {
    constructor({ id = 'weather-grid-webgl', opacity = 0.58 } = {}) {
      this.id = id;
      this.type = 'custom';
      this.renderingMode = '2d';
      this.opacity = opacity;
      this.map = null;
      this.gl = null;
      this.program = null;
      this.vertexBuffer = null;
      this.uvBuffer = null;
      this.gridTexture = null;
      this.rampTexture = null;
      this.current = null;
    }

    onAdd(map, gl) {
      this.map = map;
      this.gl = gl;
      this.program = createProgram(gl);
      this.vertexBuffer = gl.createBuffer();
      this.uvBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
      if (this.current) this._syncTextures();
    }

    update(current, style) {
      this.current = { ...current, style };
      if (this.gl) this._syncTextures();
      if (this.map) this.map.triggerRepaint();
    }

    clear() {
      this.current = null;
      if (this.map) this.map.triggerRepaint();
    }

    _syncTextures() {
      const gl = this.gl;
      const grid = buildNormalizedGridTexture(this.current.values, this.current.metadata);
      const rampBytes = buildColorRampBytes(this.current.style);
      this.gridTexture = createTexture(gl, grid.width, grid.height, grid.bytes, true);
      this.rampTexture = createTexture(gl, rampBytes.length / 4, 1, rampBytes, true);
    }

    _quadMercator() {
      const bounds = this.current.metadata.bounds;
      const mc = globalThis.maplibregl.MercatorCoordinate;
      const sw = mc.fromLngLat([bounds.west, bounds.south]);
      const se = mc.fromLngLat([bounds.east, bounds.south]);
      const nw = mc.fromLngLat([bounds.west, bounds.north]);
      const ne = mc.fromLngLat([bounds.east, bounds.north]);
      return new Float32Array([sw.x, sw.y, se.x, se.y, nw.x, nw.y, ne.x, ne.y]);
    }

    render(gl, matrix) {
      if (!this.current || !this.program || !this.gridTexture || !this.rampTexture) return;

      gl.useProgram(this.program);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      const vertices = this._quadMercator();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
      const pos = gl.getAttribLocation(this.program, 'a_pos');
      gl.enableVertexAttribArray(pos);
      gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

      gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
      const uv = gl.getAttribLocation(this.program, 'a_uv');
      gl.enableVertexAttribArray(uv);
      gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 0, 0);

      gl.uniformMatrix4fv(gl.getUniformLocation(this.program, 'u_matrix'), false, matrix);
      gl.uniform1f(gl.getUniformLocation(this.program, 'u_opacity'), this.opacity);

      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.gridTexture);
      gl.uniform1i(gl.getUniformLocation(this.program, 'u_grid'), 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.rampTexture);
      gl.uniform1i(gl.getUniformLocation(this.program, 'u_ramp'), 1);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  return {
    WeatherGridLayer,
    buildColorRampBytes,
    buildNormalizedGridTexture,
    hexToRgba,
  };
});
```

- [ ] **Step 4: Run WebGL helper tests and verify they pass**

Run:

```bash
node --test tests/frontend-weather-grid-layer.test.js
```

Expected: all tests in `tests/frontend-weather-grid-layer.test.js` pass.

- [ ] **Step 5: Commit Task 5 files**

Run in an isolated worktree:

```bash
git add frontend/weather-grid-layer.js tests/frontend-weather-grid-layer.test.js
git commit -m "feat: add MapLibre weather grid layer"
```

Expected: one commit containing only the two files listed above.

## Task 6: Map Integration, Fallback, and Docs

**Files:**

- Modify: `frontend/map.html`
- Modify: `frontend/map.js`
- Modify: `docs/api.md`

- [ ] **Step 1: Load new browser scripts**

Modify the script block at the end of `frontend/map.html` so it becomes:

```html
  <script src="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"></script>
  <script src="/static/maplibre-utils.js"></script>
  <script src="/static/weather-render-engine.js"></script>
  <script src="/static/weather-grid-layer.js"></script>
  <script src="/static/map.js"></script>
```

- [ ] **Step 2: Wire provider globals in `frontend/map.js`**

Extend the destructuring from `window.WeatherMapUtils` to include the render URL helpers:

```javascript
const {
  buildColorRampExpression,
  buildLayerGridUrl,
  buildRenderGridDataUrl,
  buildRenderGridMetadataUrl,
  buildRenderStyleUrl,
  featureDisplayLabel,
  forecastHourLabel,
  mergeFeatureCollections,
  metadataToBounds,
  nextForecastHour,
} = window.WeatherMapUtils;
```

Add this destructuring after it:

```javascript
const {
  GridProvider,
  StyleProvider,
} = window.WeatherRenderEngine;

const {
  WeatherGridLayer,
} = window.WeatherGridLayer;
```

Add these globals next to the existing `let map;` block:

```javascript
let gridProvider;
let styleProvider;
let weatherGridLayer;
```

- [ ] **Step 3: Initialize the render providers and custom layer**

Add this function after `initializeMap()`:

```javascript
function initializeRenderEngine() {
  gridProvider = new GridProvider();
  styleProvider = new StyleProvider();
  weatherGridLayer = new WeatherGridLayer({ id: 'diagnostic-grid-webgl', opacity: 0.58 });
  map.addLayer(weatherGridLayer);
  map.on('click', (event) => {
    if (!gridProvider?.current || !weatherGridLayer?.current) return;
    const picked = gridProvider.pick(event.lngLat.lng, event.lngLat.lat);
    if (picked) selectRenderedGridCell(picked, event.lngLat);
  });
}
```

Inside the existing `map.on('load', () => { ... })` block, call it after `ensureGridLayer();`:

```javascript
    initializeRenderEngine();
```

- [ ] **Step 4: Add render-grid load, fallback, and popup functions**

Add these functions before `loadLayer()`:

```javascript
function setGeoJsonGridVisible(visible) {
  if (!map || !map.getLayer(GRID_FILL_LAYER_ID)) return;
  map.setLayoutProperty(GRID_FILL_LAYER_ID, 'visibility', visible ? 'visible' : 'none');
}

async function loadGeoJsonGridLayer(layer, runId, fh, metadata) {
  const grid = await api(buildLayerGridUrl(layer, runId, fh, Date.now()));
  const source = map.getSource(GRID_SOURCE_ID);
  source.setData(grid);
  const palette = paletteForLayer(layer);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(metadata.min, metadata.max, palette));
  setGeoJsonGridVisible(true);
  if (weatherGridLayer) weatherGridLayer.clear();
  return palette;
}

async function loadRenderedGridLayer(layer, runId, fh) {
  const current = await gridProvider.load(layer, runId, fh);
  const style = await styleProvider.load(current.metadata.style_id, current.metadata);
  weatherGridLayer.update(current, style);
  map.getSource(GRID_SOURCE_ID).setData({ type: 'FeatureCollection', features: [] });
  setGeoJsonGridVisible(false);
  return style.colors || paletteForLayer(layer);
}

function renderedMetadataToLegacy(metadata) {
  return {
    layer_id: metadata.layer_id,
    title: metadata.title,
    unit: metadata.unit,
    min: metadata.value?.min,
    max: metadata.value?.max,
    lat_min: metadata.bounds?.south,
    lat_max: metadata.bounds?.north,
    lon_min: metadata.bounds?.west,
    lon_max: metadata.bounds?.east,
  };
}

function selectRenderedGridCell(picked, lngLat) {
  const title = picked.title || '诊断图层';
  const value = formatValue(picked.value, picked.unit);
  $('featureDetail').textContent = [
    `图层：${title}`,
    `格点值：${value}`,
    `行列：${picked.row}, ${picked.col}`,
  ].join('\n');
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong><span>格点值 ${value}</span>`)
    .addTo(map);
}
```

- [ ] **Step 5: Replace `loadLayer()` with render-first logic**

Replace the full existing `loadLayer()` function with:

```javascript
async function loadLayer() {
  if (!map || !state.mapReady) return;
  const layer = $('layerSelect').value;
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  if (!layer || !runId || Number.isNaN(fh)) return;

  state.runId = runId;
  state.forecastHour = fh;
  const title = state.layers[layer]?.title || layer;
  status(`正在加载 GIS 图层：${title} +${fh}h`);

  let metadata;
  let palette;
  try {
    palette = await loadRenderedGridLayer(layer, runId, fh);
    metadata = renderedMetadataToLegacy(gridProvider.current.metadata);
  } catch (e) {
    console.warn('render grid load failed, falling back to GeoJSON grid', e);
    const md = await api(`/api/layers/${layer}/metadata?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}`);
    metadata = md;
    palette = await loadGeoJsonGridLayer(layer, runId, fh, md);
  }

  state.currentBounds = metadataToBounds(metadata);
  updateLegend(metadata, palette);
  renderLayerChips();
  fitCurrentBounds({ duration: 450 });
  status(`已加载 GIS 图层：${metadata.title || layer} +${fh}h`);
  await loadAnalysis();
}
```

- [ ] **Step 6: Remove the redundant metadata fetch from `loadLayer()`**

After replacing `loadLayer()`, run:

```bash
rg -n "const md = await api\\(`/api/layers|buildRenderGridDataUrl|buildRenderStyleUrl" frontend/map.js
```

Expected:

- No match for the old top-level `const md = await api(...)` line inside `loadLayer()`.
- `buildRenderGridDataUrl` and `buildRenderStyleUrl` may be unused in `map.js`; they are still exported utility helpers for callers and tests.

- [ ] **Step 7: Document the render API**

Modify `docs/api.md` under the 图层 section by adding:

```markdown
## 自研渲染

- `GET /api/render/layers/{layer_id}/grid?run_id=...&forecast_hour=24`
- `GET /api/render/layers/{layer_id}/grid/data?run_id=...&forecast_hour=24`
- `GET /api/render/styles/{style_id}?min_value=...&max_value=...`

`/api/render/layers/{layer_id}/grid` 返回格点渲染元数据、二进制数据地址、原 GeoJSON 回退地址、格点起点/间隔/尺寸、范围和样式 ID。

`/api/render/layers/{layer_id}/grid/data` 返回 little-endian float32 的行优先格点数组。数组长度必须等于 `shape[0] * shape[1]`。

`/api/render/styles/{style_id}` 返回连续色标、数值域、缺测透明色和图例刻度。前端使用该资源生成 WebGL 色标纹理。
```

- [ ] **Step 8: Run all focused automated checks**

Run:

```bash
python -m pytest -q tests/test_render_artifacts.py tests/test_render_api.py tests/test_grid_geojson.py
node --test tests/frontend-maplibre-utils.test.js tests/frontend-weather-render-engine.test.js tests/frontend-weather-grid-layer.test.js
```

Expected: all selected tests pass.

- [ ] **Step 9: Run browser smoke**

Run:

```bash
python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc
python - <<'PY'
from pathlib import Path
from weather_diag.pipeline import diagnose_file
diagnose_file(Path("data/raw/ecmwf_demo.nc"), run_id="ecmwf_demo")
PY
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/map
```

Manual pass criteria:

- The map loads the `ecmwf_demo` run.
- Selecting `强降水潜势评分` renders a continuous grid overlay.
- The GeoJSON cell borders are not visible when the WebGL path succeeds.
- Clicking inside the grid shows a finite value, row, and column.
- Changing forecast hour updates the grid without rebuilding the whole map.
- Feature overlays still render points, lines, and polygons.
- If `/api/render/layers/{layer_id}/grid` is temporarily broken, the existing GeoJSON grid fallback still displays.

- [ ] **Step 10: Commit Task 6 files**

Run in an isolated worktree:

```bash
git add frontend/map.html frontend/map.js docs/api.md
git commit -m "feat: use render engine grid layer on map"
```

Expected: one commit containing only the three files listed above.

## Final Verification

Run the focused automated suite:

```bash
python -m pytest -q tests/test_render_artifacts.py tests/test_render_api.py tests/test_grid_geojson.py tests/test_public_api.py
node --test tests/frontend-maplibre-utils.test.js tests/frontend-weather-render-engine.test.js tests/frontend-weather-grid-layer.test.js
```

Expected: all selected tests pass.

Run a full test sweep if runtime dependencies are installed:

```bash
python -m pytest -q
```

Expected: all available Python tests pass.

Run a final worktree check:

```bash
git status --short
```

Expected: only intentional files from this implementation remain modified if commits were skipped; otherwise the working tree is clean.

## Rollback

The rollback path is file-scoped:

1. Revert the `frontend/map.js` and `frontend/map.html` integration commit to return the map to GeoJSON rendering.
2. Leave `/api/render/...` routes in place if external clients are not affected.
3. Revert `backend/app/main.py` router registration if the render API itself causes service startup problems.
4. Keep `weather_diag/io/render_artifact.py` and tests if they are still useful for a revised implementation branch.

## Self-Review Checklist

- Spec coverage: Phase 1 backend metadata, binary data, style route, frontend provider, custom WebGL layer, picking, GeoJSON fallback, tests, docs, and smoke checks are covered.
- API compatibility: existing `/api/layers/*` and `/api/features*` routes are not removed.
- Type consistency: backend metadata uses `shape`, `grid`, `value`, `style_id`, `data_url`, and `fallback_geojson_url`; frontend provider and layer use those exact property names.
- Scope control: wind particles, contours, vector polygon improvements, and Cesium 3D are outside this Phase 1 plan.
