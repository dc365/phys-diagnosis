# Weather Render Engine Design

## Context

The project already has a FastAPI backend, a `weather_diag` diagnosis package,
generated NetCDF products, GeoJSON weather-system output, and a MapLibre-based
frontend. The current map renders gridded diagnostic fields through
`/api/layers/{layer_id}/grid`, where the backend converts each sampled grid cell
to a GeoJSON polygon. This is acceptable for the current MVP, but it will not
scale well for high-resolution grids, time animation, wind fields, contour
rendering, or future 3D views.

QuickEarth is useful as a reference architecture, not as a runtime dependency.
The part worth copying is its separation of:

- data providers
- render layers
- style resources
- time and level state
- 2D and 3D views over a shared data contract

The first self-owned version should keep the existing MapLibre frontend and
Python/xarray backend, but introduce a compact render artifact contract and a
client-side WebGL grid renderer.

## Goals

- Build the first version of a self-owned weather rendering engine.
- Preserve existing API paths and the current MapLibre page.
- Replace the long-term gridded-field path with compact grid artifacts instead
  of polygon GeoJSON.
- Keep GeoJSON as the standard model for weather-system vectors, fronts, lines,
  points, and risk polygons.
- Define provider-style contracts for grid, vector, wind, style, time, and
  level data.
- Make the first phase independently shippable without requiring Cesium or a
  full 3D implementation.
- Leave a clean extension path for wind particles, contours, tiled products, and
  3D views.

## Non-Goals

- Depending on the QuickEarth runtime SDK.
- Replacing MapLibre in the current 2D product.
- Building a full GIS platform, online layer editor, or map authoring console.
- Implementing Cesium 3D in the first phase.
- Supporting every meteorological file format directly in the frontend.
- Moving algorithm logic into frontend rendering code.
- Removing the existing `/api/layers/{layer_id}/grid` GeoJSON route.

## Recommended Approach

Introduce a small weather rendering engine inside the existing application:

```text
NetCDF / diagnosis result
  -> backend render artifact
  -> frontend render provider
  -> MapLibre custom WebGL layer
  -> style resource and legend
```

The backend remains responsible for reading NetCDF, normalizing units, running
diagnostics, and producing render-ready artifacts. The frontend owns map
interaction, WebGL drawing, color mapping, picking, and layer composition.

The current GeoJSON grid route remains as a compatibility and fallback path.
New development should use the render artifact route.

## Architecture

```text
weather_diag
  diagnostics and feature detection
        |
        v
backend render services
  grid artifact writer
  metadata builder
  style resource loader
        |
        v
HTTP API
  /api/render/layers/{layer_id}/grid
  /api/render/styles/{style_id}
        |
        v
frontend render engine
  GridProvider
  FeatureProvider
  WindProvider
  StyleProvider
        |
        v
MapLibre
  WeatherGridLayer
  WeatherFeatureLayer
  WeatherWindLayer
```

There are more than three components exchanging data, so the main control rule
is strict ownership:

- Backend owns scientific data correctness and artifact generation.
- Providers own data loading, caching, and coordinate conversion.
- Layers own drawing and hit testing.
- Style resources own color scales, thresholds, units, and legend text.
- Map UI owns layer selection, time selection, and user interaction.

## Backend Contract

### Grid Artifact Metadata

Add a new route:

```text
GET /api/render/layers/{layer_id}/grid?run_id=...&forecast_hour=...
```

The response returns JSON metadata plus URLs for binary data:

```json
{
  "layer_id": "heavy_rain_score",
  "variable": "heavy_rain_score",
  "title": "Heavy rain potential",
  "unit": "score",
  "run_id": "ecmwf_demo",
  "forecast_hour": 24,
  "encoding": "float32-le",
  "shape": [181, 241],
  "bounds": {
    "west": 70.0,
    "south": 15.0,
    "east": 140.0,
    "north": 55.0
  },
  "grid": {
    "x_start": 70.0,
    "x_delta": 0.25,
    "x_size": 241,
    "y_start": 15.0,
    "y_delta": 0.25,
    "y_size": 181
  },
  "value": {
    "min": 0.0,
    "max": 1.0,
    "missing": "nan"
  },
  "style_id": "score",
  "data_url": "/api/render/layers/heavy_rain_score/grid/data?run_id=ecmwf_demo&forecast_hour=24",
  "fallback_geojson_url": "/api/layers/heavy_rain_score/grid?run_id=ecmwf_demo&forecast_hour=24"
}
```

Add a companion route for the data bytes:

```text
GET /api/render/layers/{layer_id}/grid/data?run_id=...&forecast_hour=...
```

The first implementation uses little-endian `float32` bytes. This keeps the
contract easy to inspect and avoids premature compression complexity. Later
versions may add `int16-scale-offset`, `png16`, or `webp-grid` while preserving
the metadata shape.

### Style Resources

Add a style route:

```text
GET /api/render/styles/{style_id}
```

The response defines the color ramp and legend:

```json
{
  "style_id": "score",
  "type": "continuous",
  "colors": ["#fff7bc", "#fec44f", "#fb6a4a", "#bd0026"],
  "domain": [0.0, 1.0],
  "missing_color": "rgba(0,0,0,0)",
  "legend": {
    "title": "Potential score",
    "ticks": [0.0, 0.25, 0.5, 0.75, 1.0]
  }
}
```

Style resources should be loaded from existing layer configuration first. A
future phase can move them into a richer YAML or JSON file.

### Existing API Compatibility

Do not remove or break:

- `GET /api/layers`
- `GET /api/layers/{layer_id}/metadata`
- `GET /api/layers/{layer_id}/grid`
- `GET /api/layers/{layer_id}/image`
- `GET /api/features`
- `GET /api/features/{feature_id}`

The current frontend can continue using GeoJSON until the new renderer is
enabled layer by layer.

## Frontend Contract

### Provider Interfaces

The first provider interfaces can be plain JavaScript objects. TypeScript is not
required for the first phase.

`GridProvider` responsibilities:

- Load grid metadata.
- Load binary grid data.
- Cache the latest array by `layer_id`, `run_id`, and `forecast_hour`.
- Convert map coordinates to grid row and column.
- Pick the nearest grid value for popups.
- Expose min, max, unit, title, bounds, and style ID.

`StyleProvider` responsibilities:

- Load style resources.
- Normalize style domains.
- Provide WebGL color-ramp texture data.
- Provide legend values for the UI.

`FeatureProvider` responsibilities:

- Continue loading GeoJSON from `/api/features`.
- Keep feature filtering by `feature_type`.
- Preserve current point, line, and polygon behavior.

`WindProvider` is reserved for the second phase. It should use the same grid
metadata model but load U and V components together.

### Render Layers

`WeatherGridLayer` should be a MapLibre custom layer with WebGL rendering.

Responsibilities:

- Upload the grid as a texture.
- Upload the color ramp as a small texture.
- Draw a rectangle over the grid bounds.
- Map screen fragments back to grid coordinates in the shader.
- Apply nearest or bilinear sampling.
- Discard missing values.
- Support opacity.
- Preserve map pan, zoom, pitch, and resize behavior.

The first phase can implement one active grid layer at a time. Multi-layer
composition is deferred until the single-layer path is stable.

`WeatherFeatureLayer` can continue using native MapLibre GeoJSON layers. It does
not need to be rewritten during the first phase.

## Data Flow

### First Page Load

1. The map loads the existing base style.
2. The UI calls `/api/layers`.
3. The selected layer calls the new render grid metadata route.
4. The provider fetches binary grid data and style data.
5. The custom layer uploads textures and renders the grid.
6. Feature layers continue loading from `/api/features`.

### Forecast Hour Change

1. The UI updates `forecast_hour`.
2. The grid provider requests metadata and data for the new hour.
3. The custom layer replaces the grid texture.
4. Feature layers reload from the existing feature route.
5. The map bounds do not reset unless the new layer metadata changes domain.

### Grid Picking

1. User clicks the map.
2. The provider converts lon/lat to row and column using grid metadata.
3. The provider reads the value from the cached typed array.
4. The UI shows title, value, unit, row, column, and forecast hour.

## Error Handling

- If the render metadata route fails, fall back to the existing GeoJSON grid
  route for that layer.
- If binary data fails to load, show a non-blocking map status message and keep
  the previous layer visible.
- If WebGL custom layer initialization fails, fall back to GeoJSON grid.
- If style loading fails, use the layer metadata min/max and the existing
  frontend palette for that layer family.
- If a grid has descending latitude or longitude, the backend metadata must
  describe the actual delta sign, and the provider must use that sign instead of
  assuming ascending coordinates.
- If the grid shape does not match metadata, the provider must reject the layer
  and show an explicit status message.

## Phases

### Phase 1: 2D Grid Engine

Ship a single-layer MapLibre WebGL grid renderer.

Scope:

- Backend render metadata route.
- Backend binary float32 grid route.
- Frontend `GridProvider`.
- Frontend `StyleProvider`.
- Frontend `WeatherGridLayer`.
- Popup picking from typed array.
- GeoJSON fallback.
- Tests for metadata, binary size, coordinate picking, and URL helpers.

This phase is independently mergeable. If later phases never ship, the product
still gains a faster gridded-field renderer.

### Phase 2: Wind Layer

Add a `WindProvider` and a MapLibre WebGL wind layer.

Scope:

- U/V grid pairing.
- Shared grid metadata validation.
- Particle rendering.
- Optional speed color overlay.
- Density and opacity controls.

This phase depends on the grid provider contract from Phase 1, but the product
remains usable if wind rendering is not enabled.

### Phase 3: Contours and Weather Polygons

Improve vector products.

Scope:

- Generate isolines or contour polygons server-side for selected variables.
- Replace current bbox-style risk polygons where real contours are useful.
- Keep output as GeoJSON for MapLibre.
- Add simplification controls so products stay small.

This phase improves scientific readability without changing the grid renderer.

### Phase 4: 3D Sidecar View

Add a Cesium-based view only when there is a concrete 3D requirement.

Scope:

- Reuse grid, feature, wind, style, time, and level contracts.
- Render terrain-following grid overlays or extruded fields.
- Add vertical section or volume rendering for selected fields.
- Keep the MapLibre 2D view as the primary operational UI.

This phase must not force 3D dependencies into the 2D first load.

## File Targets

Likely backend files:

- `backend/app/main.py`
- `backend/app/api/render.py`
- `backend/app/services/render_artifacts.py`
- `weather_diag/io/render_artifact.py`
- `configs/layers.yaml`

Likely frontend files:

- `frontend/map.js`
- `frontend/maplibre-utils.js`
- `frontend/weather-render-engine.js`
- `frontend/weather-grid-layer.js`
- `frontend/weather-style-provider.js`

Likely tests:

- `tests/test_render_artifacts.py`
- `tests/test_render_api.py`
- `tests/frontend-maplibre-utils.test.js`
- `tests/frontend-weather-render-engine.test.js`

The exact module split can be adjusted during implementation, but algorithm
logic must stay out of the API layer and out of frontend rendering code.

## Verification

Backend checks:

```bash
python -m pytest -q tests/test_render_artifacts.py tests/test_render_api.py
```

Frontend checks:

```bash
node --test tests/frontend-maplibre-utils.test.js tests/frontend-weather-render-engine.test.js
```

Smoke checks:

```bash
python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc
python - <<'PY'
from pathlib import Path
from weather_diag.pipeline import diagnose_file
diagnose_file(Path("data/raw/ecmwf_demo.nc"), run_id="ecmwf_demo")
PY
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Manual acceptance:

- The map can load the demo run and selected forecast hour.
- The selected grid layer renders without polygon-cell artifacts.
- Clicking the grid shows a value matching the typed array.
- Toggling forecast hours replaces the texture without a full map rebuild.
- Feature layers still render points, lines, and polygons from GeoJSON.
- Disabling the new renderer can fall back to the current GeoJSON grid path.

## Rollback

Rollback is low risk because the new renderer is additive.

- Keep existing `/api/layers/{layer_id}/grid` unchanged.
- Gate the new renderer behind a frontend capability flag or per-layer renderer
  mode.
- If the custom WebGL layer fails in production, disable the flag and return to
  GeoJSON grid rendering.
- Binary artifact routes can remain unused without affecting existing clients.

## Risks

- WebGL coordinate math can be subtly wrong at bounds, zoom levels, and
  descending latitude grids. Tests must include row/column picking at edges and
  center points.
- Raw float32 payloads are easy to implement but not the smallest format. If the
  payload is still too large after Phase 1, add `int16-scale-offset` encoding
  before adding more layer types.
- MapLibre custom layer behavior differs across versions and browsers. Manual
  browser smoke tests are required before claiming the renderer is done.
- 3D requirements can expand scope quickly. Keep Cesium out of Phase 1 and make
  it consume the same provider contract later.

## Success Criteria

The design is successful when one diagnostic grid layer renders through the new
binary-artifact and WebGL path, preserves the current feature overlays, supports
click picking, and can fall back to the existing GeoJSON grid route without
breaking the current page.
