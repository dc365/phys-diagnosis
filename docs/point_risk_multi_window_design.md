# Point Risk Multi-Window Design

Last updated: 2026-07-04

## Purpose

This document defines the compatible multi-window extension for the MCP tool `get_point_risk`.

Implementation status: implemented on 2026-07-04 in `weather_diag/mcp/point_risk.py` and `weather_diag/mcp/area_risk_dsl_mcp.py`.

The current tool returns non-DSL JSON for one time window. It accepts one or more latitude/longitude points, samples the nearest NAFP model grid point, and returns multi-hazard risk scores, risk levels, dominant-factor evidence chains, and original physical evidence.

The extension should support questions such as:

- yesterday vs today severe-convection environment at one or more points
- recent three-day point risk evolution
- daytime vs nighttime point risk evidence
- fixed-run point risk evidence for a business time window

The interface should provide per-window evidence and deterministic summaries. It should not produce cross-window natural-language conclusions such as "today is stronger than yesterday"; downstream third-party systems decide comparison wording and business interpretation.

## Existing Behavior

Legacy MCP `get_point_risk` parameters before the multi-window extension:

```text
points
start_time
end_time
models
data_code
```

`run_time` is now exposed on the MCP wrapper for fixed-run multi-window matching.

Existing output shape:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "request": {},
    "points": [],
    "model_metadata": [],
    "risk_metadata": {},
    "items": [],
    "failures": [],
    "response_guide": "..."
  }
}
```

Existing item semantics:

```text
one item = one model + one run_time + one forecast_hour + one point
```

Each item includes:

```text
model
data_code
run_time
forecast_hour
valid_time
point
sample_method
nearest_grid_point
risks
physical_evidence
```

## Compatibility Rules

1. If `windows` is not provided, the current request parameters and response shape must stay unchanged.
2. Existing `items[]` semantics must not change in single-window mode.
3. Multi-window mode must use `data.windows[]`; it must not replace top-level `data.items[]` for legacy callers.
4. `get_point_risk` remains a JSON evidence interface. It should not introduce DSL output.
5. Summary fields must be derived from generated `items[]`; summary generation must not re-read products or re-score risk grids.

## Request Extension

New MCP parameters:

```text
windows
time_match_policy
run_time
include_window_summary
```

Example request:

```json
{
  "points": [
    {"id": "P1", "name": "xiamen-station", "lat": 24.48, "lon": 118.08},
    {"id": "P2", "name": "haicang", "lat": 24.50, "lon": 117.99}
  ],
  "models": "EC",
  "data_code": "NAFP_ECTHIN_NC",
  "time_match_policy": "latest_per_valid_time",
  "include_window_summary": true,
  "windows": [
    {
      "label": "yesterday",
      "start_time": "2026-07-03T00:00:00",
      "end_time": "2026-07-03T23:59:59"
    },
    {
      "label": "today",
      "start_time": "2026-07-04T00:00:00",
      "end_time": "2026-07-04T23:59:59"
    }
  ]
}
```

Window object:

| Field | Required | Meaning |
| --- | --- | --- |
| `label` | Recommended | Client-facing label such as `yesterday`, `today`, `day1`, or `night` |
| `start_time` | Required | Window start valid time |
| `end_time` | Required | Window end valid time |

## Point Input Rules

Existing point input formats remain valid:

```text
26.08,119.30;25.98,119.45
```

```json
[
  {"name": "point-a", "lat": 26.08, "lon": 119.30},
  {"id": "P2", "name": "point-b", "lat": 25.98, "lon": 119.45}
]
```

The normalized point shape remains:

```json
{
  "id": "P1",
  "name": "point-a",
  "lat": 26.08,
  "lon": 119.3
}
```

Point IDs must be unique in one request. If the caller omits `id`, the parser
assigns stable IDs such as `P1`, `P2`, etc. Duplicate explicit IDs are rejected
because summaries use point identity for unique-point counts and point-level
summary rows.

## Time Matching Rules

Use the same time matching semantics as the town-risk DSL multi-window extension.

All forecast-product matching uses:

```text
valid_time = run_time + forecast_hour
```

A forecast lead matches a window when:

```text
start_time <= valid_time <= end_time
```

Three policies must be supported.

### `single_latest_run`

Compatibility strategy.

Rules:

1. Discover available run times in descending order.
2. For each run time, collect forecast hours whose valid time is inside the window.
3. Return the first run time with at least one matched forecast hour.
4. Do not inspect older run times once a match is found.

### `fixed_run`

Rules:

1. Require explicit `run_time`.
2. Only inspect forecast hours under that run time.
3. Return forecast hours whose valid time is inside the window.
4. If no forecast hour matches, return a window-level failure.

### `latest_per_valid_time`

Rolling latest-product stitching.

Rules:

1. Discover available run times and forecast hours.
2. Keep products whose valid time is inside the window.
3. If multiple products have the same valid time, keep the product with the latest `run_time`.
4. Sort selected products by `valid_time`.
5. Group selected products by `run_time` for source metadata.

Multi-window point-risk calls should default to:

```text
latest_per_valid_time
```

## Multi-Window Response Shape

Multi-window mode:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "mode": "multi_window_point_risk",
    "request": {
      "points": [],
      "models": ["EC"],
      "data_code": "NAFP_ECTHIN_NC",
      "time_match_policy": "latest_per_valid_time",
      "include_window_summary": true
    },
    "points": [],
    "risk_metadata": {},
    "windows": [
      {
        "label": "today",
        "start_time": "2026-07-04T00:00:00",
        "end_time": "2026-07-04T23:59:59",
        "time_match_policy": "latest_per_valid_time",
        "model_metadata": [],
        "items": [],
        "risk_summary": [],
        "point_summary": [],
        "physical_summary": [],
        "point_physical_summary": [],
        "failures": []
      }
    ],
    "response_guide": "..."
  }
}
```

Each `window.model_metadata` must list exact source products:

```json
[
  {
    "model": "EC",
    "data_code": "NAFP_ECTHIN_NC",
    "run_time": "2026-07-04T08:00:00",
    "forecast_hours": [3, 6, 9],
    "valid_times": [
      "2026-07-04T11:00:00",
      "2026-07-04T14:00:00",
      "2026-07-04T17:00:00"
    ]
  },
  {
    "model": "EC",
    "data_code": "NAFP_ECTHIN_NC",
    "run_time": "2026-07-04T20:00:00",
    "forecast_hours": [0, 3],
    "valid_times": [
      "2026-07-04T20:00:00",
      "2026-07-04T23:00:00"
    ]
  }
]
```

## Item Rules

The existing item shape remains unchanged.

For a single window:

```text
item_count <= point_count * matched_forecast_hour_count * model_count
```

Example:

```text
2 points * 5 valid times * 1 model = up to 10 items
```

Failures are stored in `window.failures[]` and do not participate in summary calculation.

## Summary Rules

Summaries are deterministic statistics derived from `window.items[]`.

They are not cross-window conclusions.

### Risk Level Vocabulary

Point risks already include `risk_level` from:

```text
score_level(score, threshold_matrix)
```

Current project levels are:

```text
high
moderate
low
```

For summary counters:

```text
high = risk_level == "high"
watch = risk_level in ["moderate", "high"]
```

`watch` is a summary concept meaning "attention level or above"; it does not introduce a new risk scoring threshold.

### Window-Level Risk Summary

One row per model/data source/risk type in a window.

Example:

```json
{
  "model": "EC",
  "data_code": "NAFP_ECTHIN_NC",
  "hazard_type": "severe_convection_composite",
  "max": 0.82,
  "max_level": "high",
  "max_valid_time": "2026-07-04T20:00:00",
  "max_point_id": "P1",
  "max_point_name": "xiamen-station",
  "max_run_time": "2026-07-04T20:00:00",
  "max_forecast_hour": 0,
  "high_point_peak": 1,
  "watch_point_peak": 3,
  "watch_point_any": 4,
  "active_valid_time_count": 5,
  "item_count": 20
}
```

Rules:

| Field | Calculation |
| --- | --- |
| `max` | Max score for this hazard over all points and valid times in the window |
| `max_level` | `risk_level` at the max row |
| `max_valid_time` | Valid time of the max row |
| `max_point_id` | Point id of the max row |
| `max_point_name` | Point name of the max row |
| `max_run_time` | Run time of the max row |
| `max_forecast_hour` | Forecast hour of the max row |
| `high_point_peak` | For each valid time, count unique points with `risk_level=high`; take the max |
| `watch_point_peak` | For each valid time, count unique points with `risk_level in moderate/high`; take the max |
| `watch_point_any` | Count unique points reaching `moderate/high` at least once in the window |
| `active_valid_time_count` | Count valid times with at least one `moderate/high` point |
| `item_count` | Count item-risk pairs included in this hazard summary |

### Point-Level Risk Summary

One row per model/data source/point/risk type in a window.

Example:

```json
{
  "model": "EC",
  "data_code": "NAFP_ECTHIN_NC",
  "point_id": "P1",
  "point_name": "xiamen-station",
  "hazard_type": "severe_convection_composite",
  "max": 0.82,
  "max_level": "high",
  "max_valid_time": "2026-07-04T20:00:00",
  "max_run_time": "2026-07-04T20:00:00",
  "max_forecast_hour": 0,
  "watch_valid_time_count": 4,
  "high_valid_time_count": 2,
  "item_count": 5
}
```

Rules:

| Field | Calculation |
| --- | --- |
| `max` | Max score for this point and hazard in the window |
| `max_level` | `risk_level` at the max row |
| `max_valid_time` | Valid time of the max row |
| `max_run_time` | Run time of the max row |
| `max_forecast_hour` | Forecast hour of the max row |
| `watch_valid_time_count` | Count valid times where this point reaches `moderate/high` |
| `high_valid_time_count` | Count valid times where this point reaches `high` |
| `item_count` | Count item-risk pairs included in this point/hazard summary |

### Tie-Breaking

If multiple rows have the same maximum score, choose a stable winner:

```text
highest score
then earliest valid_time
then original point input order
then earliest run_time
then smallest forecast_hour
```

This prevents summary output from changing due to dictionary or iteration order.

### Empty Or Failed Windows

If a window has no successful items:

```json
{
  "items": [],
  "risk_summary": [],
  "point_summary": [],
  "physical_summary": [],
  "point_physical_summary": [],
  "failures": [...]
}
```

## Physical Summary

Physical summaries are deterministic statistics derived from `items[].physical_evidence`.
They do not re-read products and do not create cross-window comparison conclusions.

Direction rules:

| Direction | Suggested summary value |
| --- | --- |
| `gte` | Max value in the window |
| `lte` | Min value in the window |

Window-level rows are returned in `physical_summary` and grouped by
`model + data_code + field`. Point-level rows are returned in
`point_physical_summary` and grouped by `model + data_code + point_id + field`.
Both use the physical field's `direction`, `watch`, and `high` thresholds to
derive `extreme_level`, watch counts, and high counts.

## Performance Rules

The extension must avoid repeated expensive product reads/calculations.

Rule:

```text
In one request, a unique product identified by root/data_code + run_time + forecast_hour may be loaded and scored at most once.
```

Implementation implications:

1. Resolve selected `(run_time, forecast_hour)` pairs per window before product loading.
2. Use a request-scoped cache keyed by `root + data_code + run_time + forecast_hour`.
3. Reuse:
   - risk input bundle
   - multi-hazard score details
4. Build `risk_summary`, `point_summary`, `physical_summary`, and `point_physical_summary` from `items[]`.
5. Do not re-read products solely to build summary sections.

Expected cost:

| Scenario | Expected cost |
| --- | --- |
| Legacy call without `windows` | Unchanged |
| One window with summary | Small overhead if summaries reuse items |
| Two windows | Roughly proportional to number of unique selected products |
| Three windows | Roughly proportional to number of unique selected products |
| Bad implementation with repeated reads for summaries | May double or worse the request time |

## Development Plan

### Phase 1: Documentation And Task State

Status: completed on 2026-07-04.

Tasks:

1. Record request rules, response shape, time matching, summary rules, compatibility rules, performance constraints, and implementation phases.
2. Add API documentation pointers.
3. Add AI external-state task documentation.
4. Review related point-risk and town-risk docs for conflicts.

### Phase 2: Tests First

Status: completed on 2026-07-04.

Files:

- `tests/test_point_risk_mcp.py`
- `tests/test_area_risk_dsl.py` for shared resolver regression if needed

Tests:

1. Legacy no-`windows` response unchanged.
2. Two requested windows return two `windows[]`.
3. `single_latest_run` uses the first matching latest run.
4. `fixed_run` requires and uses explicit `run_time`.
5. `latest_per_valid_time` stitches products across multiple runs.
6. `risk_summary` matches generated `items[]`.
7. `point_summary` matches generated `items[]`.
8. `physical_summary` and `point_physical_summary` match generated `items[].physical_evidence`.
9. Same `root + run_time + forecast_hour` product is loaded/scored once across overlapping windows.
10. Existing `get_town_risk_dsl` tests remain green.

### Phase 3: MCP Parameter Extension

Status: completed on 2026-07-04.

Files:

- `weather_diag/mcp/area_risk_dsl_mcp.py`

Tasks:

1. Add optional `windows`.
2. Add optional `time_match_policy`.
3. Add optional `run_time`.
4. Add `include_window_summary` with default `true`.
5. Pass new arguments to `get_point_risk_payload`.

### Phase 4: Multi-Window Payload Builder

Status: completed on 2026-07-04.

Files:

- `weather_diag/mcp/point_risk.py`

Tasks:

1. Add `windows`, `time_match_policy`, and `include_window_summary` to `get_point_risk_payload`.
2. Keep existing no-`windows` branch unchanged.
3. Route `windows` requests to a new internal builder such as `get_point_risk_multi_window_payload`.
4. Reuse existing `parse_point_inputs`, `normalize_models`, and `resolve_model_source`.

### Phase 5: Time Matching

Status: completed on 2026-07-04.

Files:

- `weather_diag/mcp/point_risk.py`
- Reuse from `weather_diag/mcp/area_risk_dsl.py`

Tasks:

1. Reuse `resolve_forecast_contexts`.
2. Preserve existing `resolve_forecast_context` usage for legacy mode.
3. Add failure handling per window/model when no context matches.

### Phase 6: Request-Scoped Cache

Status: completed on 2026-07-04.

Files:

- `weather_diag/mcp/point_risk.py`

Tasks:

1. Add cache for `_risk_input_bundle`.
2. Add cache for `multi_hazard_score_details`.
3. Use the cache across all windows in one request.
4. Confirm tests prove repeated products are not loaded/scored twice.

### Phase 7: Summary Generator

Status: completed on 2026-07-04.

Files:

- `weather_diag/mcp/point_risk.py`

Tasks:

1. Add `build_point_window_risk_summary`.
2. Add `build_point_window_point_summary`.
3. Use existing `risk_level` values rather than introducing new thresholds.
4. Apply stable tie-breaking.
5. Return empty summaries for empty windows.

### Phase 8: Documentation And Review

Status: completed on 2026-07-04.

Files:

- `docs/api.md`
- `doc/api.md`
- `doc/progress.md`
- `doc/task/point-risk-multi-window.md`
- `doc/review.md`
- `doc/bugs.md` if new risks appear

Tasks:

1. Update public and AI API docs.
2. Record implementation state.
3. Record validation results.
4. Record remaining risks and blocked broader tests.

## Validation Commands

Minimum targeted validation:

```text
python.exe -m py_compile weather_diag/mcp/point_risk.py weather_diag/mcp/area_risk_dsl_mcp.py
python.exe -m pytest -q tests/test_point_risk_mcp.py tests/test_area_risk_dsl.py
```

Broader validation if sample-root issue is fixed:

```text
python.exe -m pytest -q tests/test_nafp_area_risks.py
python.exe -m pytest -q
```

Known validation caveat:

`tests/test_nafp_area_risks.py` currently fails in this Windows workspace because `NAFP_SAMPLE_ROOT` is hardcoded to `/Users/dc/...` while checked-in samples exist under `test_datas/NAFP_ECTHIN_NC`. This is recorded in `doc/bugs.md`.

2026-07-04 validation result:

- `python.exe -m py_compile weather_diag/mcp/point_risk.py weather_diag/mcp/area_risk_dsl_mcp.py`: passed.
- `python.exe -m pytest -q tests/test_point_risk_mcp.py tests/test_area_risk_dsl.py`: passed with 15 tests after the MCP schema and duplicate point-id fixes.
- `python.exe -m pytest -q`: failed with 55 failed / 132 passed because of pre-existing workspace data/config/service-script failures; see `doc/bugs.md`.

## Out Of Scope

- No cross-window natural-language conclusions.
- No DSL output for `get_point_risk`.
- No physical summary in the first implementation.
- No public HTTP API route changes.
- No config, threshold, runtime data, or frontend changes unless explicitly requested.
