# Town Risk DSL Multi-Window Design

Last updated: 2026-07-04

## Purpose

This document defines the compatible multi-window extension for the MCP tool `get_town_risk_dsl`.

The current tool returns town-level risk scores and physical-evidence fields in `FCST_TWN_PHY` DSL for one time window. The planned extension keeps the existing single-window behavior unchanged and adds a multi-window evidence mode for questions such as:

- yesterday vs today severe-convection environment
- recent three-day environment comparison
- daytime vs nighttime risk evidence
- a fixed forecast run over a business window

The interface should provide evidence, source traceability, and per-window deterministic summaries. It should not produce cross-window natural-language conclusions such as "today is stronger than yesterday"; downstream third-party systems decide comparison wording and business interpretation.

## Implementation Status

Implemented on 2026-07-04.

Code changes:

- `weather_diag/mcp/area_risk_dsl.py`: added `windows`, time matching policies, multi-window payload generation, multi-run window DSL, risk summary DSL, and request-scoped cache usage.
- `weather_diag/mcp/area_risk_dsl_mcp.py`: exposed optional MCP parameters `windows`, `time_match_policy`, `run_time`, and `include_window_summary`.
- `weather_diag/diagnosis/area_risk.py`: added optional cache parameters while keeping default behavior unchanged.
- `tests/test_area_risk_dsl.py`: added coverage for the three time policies, multi-`@T` DSL, summary DSL, and legacy compatibility.

Verification completed:

```text
python.exe -m py_compile weather_diag/mcp/area_risk_dsl.py weather_diag/mcp/area_risk_dsl_mcp.py weather_diag/diagnosis/area_risk.py
python.exe -m pytest -q tests/test_area_risk_dsl.py tests/test_point_risk_mcp.py
```

`tests/test_nafp_area_risks.py` was also attempted after installing missing runtime dependencies, but the data-backed cases returned `invalid NAFP root` because the repository still hardcodes `/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC` while this Windows workspace contains samples under `test_datas/NAFP_ECTHIN_NC`.

## Existing Behavior

Existing `get_town_risk_dsl` parameters:

```text
region
start_time
end_time
models
data_code
```

Existing output shape:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "request": {},
    "region": {},
    "model_metadata": [],
    "risk_metadata": {},
    "dsl": "...",
    "dsl_structure_guide": "..."
  }
}
```

Existing `dsl` body uses one row per forecast lead and town:

```text
DT>S5=value1|value2|...;
```

One row represents:

```text
one forecast lead DT + one town S5
```

For a window with 4 matched forecast leads and 42 towns, the detail section contains up to `4 * 42` rows.

## Compatibility Rules

1. If `windows` is not provided, the tool must keep the current request parameters and current response shape.
2. Existing `data.dsl` semantics must not change in single-window mode.
3. Multi-window mode must use `data.windows[]`; it must not replace `data.dsl` for legacy callers.
4. Existing DSL row format must remain valid:

```text
DT>S5=...
```

5. Existing `@T`, `@DT`, `@WIN_RULE`, `@ORD`, `@PHY_ORD`, `@PHY`, and `#PHY` meanings remain valid.

## Request Extension

Planned new parameters:

```text
windows
time_match_policy
run_time
include_window_summary
```

Example request:

```json
{
  "region": "xiamen",
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
| `label` | Recommended | Client-facing window label, such as `yesterday`, `today`, `day1`, `night` |
| `start_time` | Required | Window start valid time |
| `end_time` | Required | Window end valid time |

## Time Matching Rules

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

Current behavior.

Rules:

1. Discover available run times in descending order.
2. For each run time, collect forecast hours whose valid time is inside the window.
3. Return the first run time with at least one matched forecast hour.
4. Do not inspect older run times once a match is found.

Use for compatibility and for "latest available run that touches this window" semantics.

### `fixed_run`

Rules:

1. Require explicit `run_time`.
2. Only inspect forecast hours under that run time.
3. Return forecast hours whose valid time is inside the window.
4. If no forecast hour matches, return a window-level failure.

Use for questions such as "what does the 08 run say about this period?"

### `latest_per_valid_time`

Rolling latest-product stitching.

Rules:

1. Discover all available run times and forecast hours.
2. Keep products whose valid time is inside the window.
3. If multiple products have the same valid time, keep the product with the latest `run_time`.
4. Sort selected products by `valid_time`.
5. Group selected products by `run_time` for DSL generation and source metadata.

Use for questions such as "what was the severe-convection environment during this business time window?"

Example:

```text
Window: 2026-07-04 10:00 ~ 2026-07-04 23:00

08 run: +3=11:00, +6=14:00, +9=17:00
20 run: +0=20:00, +3=23:00
```

Selected timeline:

```text
11:00, 14:00, 17:00 from 08 run
20:00, 23:00 from 20 run
```

## Multi-Window Response Shape

Multi-window mode:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "mode": "multi_window_evidence",
    "request": {
      "region": "xiamen",
      "models": ["EC"],
      "data_code": "NAFP_ECTHIN_NC",
      "time_match_policy": "latest_per_valid_time",
      "include_window_summary": true
    },
    "region": {
      "region_code": "350200",
      "region_level": "city",
      "region_name": "厦门市",
      "town_count": 42
    },
    "risk_metadata": {},
    "windows": [
      {
        "label": "today",
        "start_time": "2026-07-04T00:00:00",
        "end_time": "2026-07-04T23:59:59",
        "time_match_policy": "latest_per_valid_time",
        "model_metadata": [],
        "dsl": "...",
        "failures": []
      }
    ],
    "dsl_structure_guide": "..."
  }
}
```

Each `window.model_metadata` must list the exact source products:

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

## DSL Structure

### Existing Single-Run DSL

The current single-window DSL has one `@T`:

```text
@B:FCST_TWN_PHY;
@A:350200;
@CR:S5=县区3位短码+乡镇2位短码;
@S:203=思明区>20301xxx,20302xxx;
@M:EC;
@T:2607040800;
@DT:180,360,540,720;
@WIN_RULE:VALID=@T+DT;
@ORD:DT>S5=R_PHR|R_SHR|R_TG|R_HAIL|R_ROT|R_SC|CAPE|CIN|Q850|W700;
@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;
@PHY:R_SHR=risk_short_duration_heavy_rain_score|risk_score_0_1|gte|0.6|0.75;
@PHY:CAPE=cape|J/kg|gte|1000|2000;
#PHY:
180>20301=0.10|0.42|0.20|NA|0.12|0.36|1200|-80|9.2|-0.08;
360>20301=0.16|0.58|0.24|NA|0.14|0.45|1800|-50|10.5|-0.16;
```

### Planned Multi-Run Window DSL

Multi-window mode keeps a single common header per `window.dsl`, adds `@WIN`, and allows multiple `@T` segments.

No `#RUN` marker is used. The nearest preceding `@T` applies to the following `@DT` and `#PHY` rows. This reuses the existing general DSL rule that one DSL document may contain multiple `@T` declarations and data blocks read the nearest `@T`.

```text
@B:FCST_TWN_PHY;
@A:350200;
@CR:S5=县区3位短码+乡镇2位短码;
@S:203=思明区>20301xxx,20302xxx;
@M:EC;
@WIN:today|2026-07-04T10:00:00|2026-07-04T23:00:00;
@WIN_RULE:VALID=@T+DT;
@ORD:DT>S5=R_PHR|R_SHR|R_TG|R_HAIL|R_ROT|R_SC|CAPE|CIN|Q850|W700|SHR6;
@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;
@PHY:R_SHR=risk_short_duration_heavy_rain_score|risk_score_0_1|gte|0.6|0.75;
@PHY:CAPE=cape|J/kg|gte|1000|2000;
@PHY:W700=omega700|Pa/s|lte|-0.05|-0.35;

@T:2607040800;
@DT:180,360,540;
#PHY:
180>20301=0.10|0.42|0.20|NA|0.12|0.36|1200|-80|9.2|-0.08|14.0;
360>20301=0.16|0.58|0.24|NA|0.14|0.45|1800|-50|10.5|-0.16|18.5;
540>20301=0.20|0.70|0.31|NA|0.18|0.62|2400|-35|12.1|-0.28|22.0;

@T:2607042000;
@DT:0,180;
#PHY:
0>20301=0.22|0.74|0.33|NA|0.20|0.68|2600|-30|12.8|-0.35|24.0;
180>20301=0.18|0.63|0.29|NA|0.17|0.57|2100|-45|11.6|-0.20|19.0;
```

### New DSL Lines

First implementation adds these DSL lines:

```text
@WIN
@SUM_RISK_ORD
#SUMMARY_RISK
@SUM_TOWN_RISK_ORD
#SUMMARY_TOWN_RISK
@SUM_PHY_ORD
#SUMMARY_PHY
@SUM_TOWN_PHY_ORD
#SUMMARY_TOWN_PHY
```

## Detail Fields

The detail row fields are declared by `@ORD`.

Common current fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `DT` | Index | Forecast lead in minutes |
| `S5` | Index | Town short code |
| `R_PHR` | Risk | Persistent heavy-rain risk, 0-1 |
| `R_SHR` | Risk | Short-duration heavy-rain risk, 0-1 |
| `R_TG` | Risk | Thunderstorm-gale/downburst risk, 0-1 |
| `R_HAIL` | Risk | Hail risk, 0-1 |
| `R_ROT` | Risk | Rotating-storm/supercell potential, 0-1 |
| `R_SC` | Risk | Severe-convection composite risk, 0-1 |
| `CAPE` | Physical evidence | Convective available potential energy |
| `CIN` | Physical evidence | Convective inhibition |
| `Q850` | Physical evidence | 850hPa specific humidity |
| `PW` | Physical evidence | Precipitable water |
| `W700` | Physical evidence | 700hPa vertical velocity |
| `SHR6` | Physical evidence | 0-6km wind shear |
| `SHR1` | Physical evidence | 0-1km wind shear |
| `KI` | Physical evidence | K index |
| `RAIN3` / `RAIN6` / `RAIN24` | Physical evidence | Model precipitation signal |

Actual fields must always be read from `@ORD` and explained by `@PHY_ORD` / `@PHY`.

## Window Summary DSL

Window summaries are deterministic statistics derived from already generated detail rows. They are not cross-window conclusions.

### Region-Level Risk Summary

Order:

```text
@SUM_RISK_ORD:FIELD=MAX|MAX_VALID|MAX_S5|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
```

Data:

```text
#SUMMARY_RISK:
R_SC=0.82|2607042000|20301|12|28|34|4;
R_SHR=0.76|2607041700|20302|8|21|26|3;
```

Fields:

| Field | Meaning | Calculation |
| --- | --- | --- |
| `FIELD` | Risk DSL field such as `R_SC` | Field identifier |
| `MAX` | Maximum score in the window | Max over all matched `DT/S5` rows |
| `MAX_VALID` | Valid time of `MAX` | `@T + DT` of max row |
| `MAX_S5` | Town where `MAX` occurs | S5 of max row |
| `HIGH_CNT_PEAK` | Peak high-risk town count | For each valid time, count towns with value >= high threshold, then take max |
| `WATCH_CNT_PEAK` | Peak watch-risk town count | For each valid time, count towns with value >= watch threshold, then take max |
| `WATCH_TOWN_ANY` | Any-time watch town count | Count unique towns whose value reaches watch threshold at any matched valid time |
| `ACTIVE_DT_CNT` | Active forecast lead count | Count valid times with at least one town reaching watch threshold |

### Town-Level Risk Summary

Order:

```text
@SUM_TOWN_RISK_ORD:S5>FIELD=MAX|MAX_VALID|MAX_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
```

Data:

```text
#SUMMARY_TOWN_RISK:
20301>R_SC=0.82|2607042000|high|4|1;
20301>R_SHR=0.76|2607041700|high|3|1;
20302>R_SC=0.64|2607041700|watch|2|0;
```

Fields:

| Field | Meaning | Calculation |
| --- | --- | --- |
| `S5` | Town short code | Row key |
| `FIELD` | Risk DSL field such as `R_SC` | Risk field key |
| `MAX` | Maximum score for this town and risk in the window | Max over matched valid times for this S5 |
| `MAX_VALID` | Valid time of town-level max | `@T + DT` of max row |
| `MAX_LEVEL` | Risk level of town-level max | `high`, `watch`, or `low` by configured thresholds |
| `WATCH_DT_CNT` | Watch-level duration count | Count matched valid times with value >= watch threshold |
| `HIGH_DT_CNT` | High-level duration count | Count matched valid times with value >= high threshold |

### Region-Level Physical Summary

Order:

```text
@SUM_PHY_ORD:PID=EXTREME|EXTREME_VALID|EXTREME_S5|EXTREME_LEVEL|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
```

Data:

```text
#SUMMARY_PHY:
CAPE=2600.00|2607041400|20301|high|1|2|2|2;
CIN=40.00|2607041400|20301|high|1|2|2|2;
```

Fields:

| Field | Meaning | Calculation |
| --- | --- | --- |
| `PID` | Physical DSL field such as `CAPE` or `CIN` | Field identifier from `@PHY` |
| `EXTREME` | Direction-aware extreme in the window | `gte` fields use max; `lte` fields use min |
| `EXTREME_VALID` | Valid time of `EXTREME` | `@T + DT` of the extreme row |
| `EXTREME_S5` | Town where `EXTREME` occurs | S5 of the extreme row |
| `EXTREME_LEVEL` | Physical threshold level of the extreme | `high`, `watch`, or `low` by field direction and thresholds |
| `HIGH_CNT_PEAK` | Peak high-threshold town count | For each valid time, count towns reaching high threshold, then take max |
| `WATCH_CNT_PEAK` | Peak watch-threshold town count | For each valid time, count towns reaching watch threshold, then take max |
| `WATCH_TOWN_ANY` | Any-time watch town count | Count unique towns whose value reaches watch threshold at any matched valid time |
| `ACTIVE_DT_CNT` | Active forecast lead count | Count valid times with at least one town reaching watch threshold |

### Town-Level Physical Summary

Order:

```text
@SUM_TOWN_PHY_ORD:S5>PID=EXTREME|EXTREME_VALID|EXTREME_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
```

Data:

```text
#SUMMARY_TOWN_PHY:
20301>CAPE=2600.00|2607041400|high|2|1;
20301>CIN=40.00|2607041400|high|2|1;
```

Fields:

| Field | Meaning | Calculation |
| --- | --- | --- |
| `S5` | Town short code | Row key |
| `PID` | Physical DSL field such as `CAPE` or `CIN` | Field identifier from `@PHY` |
| `EXTREME` | Direction-aware extreme for this town and field | `gte` fields use max; `lte` fields use min |
| `EXTREME_VALID` | Valid time of town-level extreme | `@T + DT` of the extreme row |
| `EXTREME_LEVEL` | Physical threshold level of the extreme | `high`, `watch`, or `low` |
| `WATCH_DT_CNT` | Watch-threshold duration count | Count matched valid times reaching watch threshold |
| `HIGH_DT_CNT` | High-threshold duration count | Count matched valid times reaching high threshold |

### Summary Boundary

The interface should produce window summaries but not cross-window comparison conclusions.

Downstream comparison examples:

```text
today.R_SC.MAX - yesterday.R_SC.MAX
today.20301.R_SC.HIGH_DT_CNT - yesterday.20301.R_SC.HIGH_DT_CNT
today.R_SHR.WATCH_TOWN_ANY - yesterday.R_SHR.WATCH_TOWN_ANY
```

## Performance Rules

The extension must avoid repeated expensive product reads/calculations.

Rule:

```text
In one request, a unique product identified by root/data_code + run_time + forecast_hour may be loaded and scored at most once.
```

Implementation implications:

1. Resolve all selected `(run_time, forecast_hour)` pairs before scoring.
2. Deduplicate selected products across windows.
3. Reuse risk scores and physical evidence when generating detail DSL and summaries.
4. Build summaries from generated details or already computed area-risk items.
5. Do not re-read NAFP files solely to build `#SUMMARY_*` sections.

Expected impact:

| Scenario | Expected cost |
| --- | --- |
| Legacy call without `windows` | Unchanged |
| Single window with risk summary | Small overhead if summaries reuse detail rows |
| Two windows | Roughly proportional to number of unique selected products |
| Three windows | Roughly proportional to number of unique selected products |
| Bad implementation with repeated reads for summaries | May double or worse the request time |

## Development Plan

### Phase 1: Documentation And Test Baseline

Status: this document.

Tasks:

1. Record multi-window rules, DSL extension, summary rules, compatibility rules, and performance constraints.
2. Add or update API documentation entry points.
3. Add AI external-state task documentation.
4. Review related DSL/API docs for conflicts.

### Phase 2: Request Parameter Extension

Files likely affected:

- `weather_diag/mcp/area_risk_dsl_mcp.py`
- `weather_diag/mcp/area_risk_dsl.py`

Tasks:

1. Add optional `windows`, `time_match_policy`, `run_time`, and `include_window_summary` parameters.
2. Keep no-`windows` behavior unchanged.
3. Route `windows` requests to new multi-window payload builder.

### Phase 3: Time Matching

Add policy-specific resolvers:

```text
single_latest_run
fixed_run
latest_per_valid_time
```

Each resolver should return grouped selected products:

```json
[
  {
    "run_time": "2026-07-04T08:00:00",
    "forecast_hours": [3, 6, 9],
    "valid_times": ["...", "..."]
  }
]
```

### Phase 4: Request-Scoped Cache

Add internal cache keyed by:

```text
root/data_code + run_time + forecast_hour
```

The cache should support reusing:

- risk input bundle
- multi-hazard score details
- town area-risk items
- physical-evidence values

### Phase 5: Multi-Window Payload Builder

Add a new builder, conceptually:

```text
get_town_risk_multi_window_payload()
build_town_risk_window_response()
```

Each window should include:

```text
label
start_time
end_time
time_match_policy
model_metadata
dsl
failures
```

### Phase 6: Multi-Run DSL Generator

Add generator for:

```text
common header
@WIN
@T/@DT/#PHY segments
@SUM_RISK_ORD/#SUMMARY_RISK
@SUM_TOWN_RISK_ORD/#SUMMARY_TOWN_RISK
```

The old single-window DSL generator should remain available for legacy calls.

### Phase 7: Summary Generator

Build summary sections from detail rows or area-risk items:

- region-level risk summary
- town-level risk summary

Do not implement physical summaries in the first phase unless explicitly requested.

### Phase 8: Tests

Minimum targeted tests:

```text
pytest -q tests/test_area_risk_dsl.py
pytest -q tests/test_point_risk_mcp.py
```

New tests should cover:

1. Legacy no-`windows` response unchanged.
2. `single_latest_run` still matches current behavior.
3. `fixed_run` only uses specified run time.
4. `latest_per_valid_time` stitches products from multiple run times.
5. `window.dsl` contains one common header and multiple `@T` sections.
6. `#SUMMARY_RISK` and `#SUMMARY_TOWN_RISK` match detail rows.
7. Summary generation does not trigger duplicate product scoring for the same `(run_time, forecast_hour)`.

Broader tests after implementation:

```text
pytest -q tests/test_nafp_area_risks.py
pytest -q
```

## Documentation Review Notes

Reviewed existing docs and code references:

- `docs/api.md`: documents public HTTP API and current v1 contracts; should link to this design for MCP multi-window extension.
- `docs/场景化气象DSL结构说明.md`: already states that one DSL document may contain multiple `@T` values and data blocks use the nearest `@T`; this supports the planned no-`#RUN` multi-run DSL.
- `docs/phys_dsl_mcp.py`: embedded DSL guide explains `FCST_TWN_PHY`, `@T`, `@DT`, and `VALID=@T+DT`; future implementation should update the MCP-facing guide once the new DSL is shipped.
- `doc/api.md`: AI external API summary should mention this planned extension.
- `tests/test_area_risk_dsl.py`: existing tests assert current single-window DSL behavior and should be extended without breaking old assertions.

No implementation has been changed in this phase.
