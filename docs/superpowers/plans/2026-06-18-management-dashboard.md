# Management Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first usable visual management backend for NAFP weather-situation diagnosis, focused on forecaster duty workflows and evidence-chain inspection.

**Architecture:** Keep the current FastAPI static-file delivery model and avoid introducing a frontend build pipeline. Replace the root page with a light operations dashboard, preserve the existing MapLibre page as a secondary `/map` view, and add testable JavaScript helpers for formatting and payload shaping.

**Tech Stack:** FastAPI, static HTML/CSS/JavaScript, Node `node:test` for frontend utility tests, Pytest for backend route tests.

---

### Task 1: Admin Surface Tests

**Files:**
- Create: `tests/frontend-admin-utils.test.js`
- Create: `tests/test_admin_static.py`

- [ ] **Step 1: Write failing tests**

```js
// tests/frontend-admin-utils.test.js
const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildNafpSituationRequest,
  summarizeSituation,
  evidenceLevelLabel,
  formatIsoForDuty,
} = require('../frontend/admin-utils');

test('buildNafpSituationRequest normalizes run time and forecast hour', () => {
  assert.deepEqual(
    buildNafpSituationRequest('/data/nafp', '2026-06-17 20', '24'),
    { root: '/data/nafp', run_time: '2026-06-17T20:00:00', forecast_hour: 24 },
  );
});

test('summarizeSituation derives duty metrics from diagnosis payload', () => {
  const summary = summarizeSituation({
    systems: [{ type: 'subtropical_high' }, { type: 'trough_candidate' }],
    evidence_chains: [{ level: 'moderate' }, { level: 'high' }],
    missing_fields: [{ field: 'rain6' }],
  });

  assert.deepEqual(summary, {
    systemCount: 2,
    highRiskCount: 1,
    moderateRiskCount: 1,
    missingCount: 1,
    completeness: 94,
  });
});

test('evidenceLevelLabel returns Chinese operational labels', () => {
  assert.equal(evidenceLevelLabel('high'), '高');
  assert.equal(evidenceLevelLabel('moderate'), '中');
  assert.equal(evidenceLevelLabel('low'), '低');
});

test('formatIsoForDuty keeps invalid or empty values safe', () => {
  assert.equal(formatIsoForDuty('2026-06-18T20:00:00'), '2026-06-18 20:00');
  assert.equal(formatIsoForDuty(''), '-');
});
```

```python
# tests/test_admin_static.py
from fastapi.testclient import TestClient

from backend.app.main import app


def test_root_serves_management_dashboard():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "可视化管理后台" in response.text


def test_map_view_remains_available():
    response = TestClient(app).get("/map")

    assert response.status_code == 200
    assert "天气诊断 GIS 地图" in response.text
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
node --test tests/frontend-admin-utils.test.js
.venv/bin/pytest tests/test_admin_static.py -q
```

Expected: the Node test fails because `frontend/admin-utils.js` does not exist, and the Pytest route test fails until `/map` and the dashboard title exist.

### Task 2: Static Routes

**Files:**
- Create: `frontend/map.html`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Preserve the old MapLibre page**

Copy the current `frontend/index.html` body into `frontend/map.html` unchanged.

- [ ] **Step 2: Add the `/map` route**

```python
@app.get("/map")
def map_view():
    map_path = FRONTEND_DIR / "map.html"
    if map_path.exists():
        return FileResponse(map_path)
    raise HTTPException(404, "map view not found")
```

- [ ] **Step 3: Run the static route test**

Run:

```bash
.venv/bin/pytest tests/test_admin_static.py -q
```

Expected: `/map` passes after `map.html` exists, `/` still fails until the dashboard page is implemented.

### Task 3: Admin Utilities

**Files:**
- Create: `frontend/admin-utils.js`

- [ ] **Step 1: Implement pure helpers**

Implement:

```js
buildNafpSituationRequest(root, runTime, forecastHour)
summarizeSituation(payload)
evidenceLevelLabel(level)
formatIsoForDuty(value)
```

- [ ] **Step 2: Run frontend utility tests**

Run:

```bash
node --test tests/frontend-admin-utils.test.js
```

Expected: all tests pass.

### Task 4: Dashboard UI

**Files:**
- Replace: `frontend/index.html`
- Replace: `frontend/styles.css`
- Replace: `frontend/app.js`

- [ ] **Step 1: Build the dashboard shell**

Use a sidebar plus main workspace layout with these areas:
- left navigation
- sticky top run controls
- status summary strip
- situation systems table
- evidence chain panel
- data completeness matrix
- recent task log

- [ ] **Step 2: Connect the current NAFP API**

Use:

```http
POST /api/v1/diagnosis/nafp/situation
```

Default request:

```json
{
  "root": "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24
}
```

- [ ] **Step 3: Render evidence details**

Clicking a system or evidence chain updates the right inspector with confidence, score, source paths, missing evidence, and bbox region.

### Task 5: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full automated checks**

Run:

```bash
node --test tests/frontend-admin-utils.test.js tests/frontend-maplibre-utils.test.js
.venv/bin/pytest -q
```

- [ ] **Step 2: Run the app**

Run:

```bash
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 3: Smoke test API and rendered page**

Run:

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/ | head
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/v1/diagnosis/nafp/situation \
  -H 'content-type: application/json' \
  -d '{"root":"/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC","run_time":"2026-06-17T20:00:00","forecast_hour":24}'
```

Expected: dashboard HTML loads and API returns `code: 0`, `msg: ok`.
