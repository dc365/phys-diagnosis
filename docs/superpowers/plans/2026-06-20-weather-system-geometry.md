# Weather System Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace rectangular weather-system regions with geometry that reflects the connected mask shape, and replace bbox-derived band lines with component centerlines.

**Architecture:** Add reusable grid-geometry helpers in `weather_diag/diagnostics/grid.py`, keeping bbox and centroid metadata while changing the actual API geometry to `Polygon`, `MultiPolygon`, or `LineString`. Apply the helpers through existing mask-based system detectors so thresholds and evidence chains remain unchanged.

**Tech Stack:** Python, NumPy, SciPy connected components, Shapely polygon union, existing pytest suite.

---

### Task 1: Lock Geometry Contracts With Tests

**Files:**
- Modify: `tests/test_nafp_situation.py`
- Create: `tests/test_grid_geometry.py`

- [ ] Add focused tests proving L-shaped masks produce non-rectangular polygons and diagonal/banded masks produce multi-point centerlines.
- [ ] Add NAFP integration checks that systems no longer emit `geometry.type = bbox`, that region polygons include coordinates, and that jet/moisture lines have more than two coordinates where enough source points exist.
- [ ] Run the new tests and verify they fail against the existing bbox implementation.

### Task 2: Implement Shared Grid Geometry

**Files:**
- Modify: `weather_diag/diagnostics/grid.py`

- [ ] Extend connected mask feature extraction to build a Shapely union of each component's grid-cell polygons.
- [ ] Return GeoJSON-style `Polygon` or `MultiPolygon` geometry with existing `indices`, `bbox`, `centroid`, and `point_count`.
- [ ] Add a `component_axis_line(item, lat, lon)` helper using PCA-like projection over component points, returning a simplified centerline instead of a bbox centerline.
- [ ] Keep `mask_to_bbox_features` as a compatibility alias if needed, but route callers to the improved geometry.

### Task 3: Apply Geometry to Weather-System Outputs

**Files:**
- Modify: `weather_diag/features/areas.py`
- Modify: `weather_diag/features/low_level_jet.py`
- Modify: `weather_diag/features/moisture_transport.py`
- Modify: `weather_diag/diagnosis/nafp_situation.py`

- [ ] Use the improved component polygon for area systems: subtropical high, pressure convergence/divergence, front candidates, moisture convergence, low-level convergence, upper divergence, and risk regions.
- [ ] Use the axis helper for low-level jet and moisture transport outputs.
- [ ] Preserve existing evidence entries, thresholds, confidence values, ids, levels, and source paths.

### Task 4: Synchronize Rule Documentation

**Files:**
- Modify: `weather_diag/diagnosis/algorithm_rules.py`

- [ ] Replace stale `bbox_for_mask` wording with connected polygon / axis-line wording.
- [ ] Update output contracts for subtropical high, trough/ridge fallback areas, and evidence-chain risk regions.

### Task 5: Verify

**Commands:**
- `.venv/bin/python -m pytest tests/test_grid_geometry.py tests/test_nafp_situation.py -q`
- `.venv/bin/python -m pytest -q`
- `node --test tests/*.test.js`

- [ ] Fix any regressions caused by geometry payload changes.
- [ ] Report any unrelated pre-existing failures separately.
