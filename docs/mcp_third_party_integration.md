# MCP Third-Party Integration Guide

Last updated: 2026-07-04

This document is the third-party integration guide for the MCP tools exposed by
`weather_diag/mcp/area_risk_dsl_mcp.py`.

It covers two tools:

- `get_town_risk_dsl`: town-level risk and physical-evidence DSL.
- `get_point_risk`: point-level risk and physical-evidence JSON.

The implementation source of truth is:

- `weather_diag/mcp/area_risk_dsl_mcp.py`
- `weather_diag/mcp/area_risk_dsl.py`
- `weather_diag/mcp/point_risk.py`

## 1. Integration Scope

These are MCP tools, not the public REST endpoints under `/api/v1`.

Default MCP runtime:

| Item | Value |
| --- | --- |
| Server module | `python -m weather_diag.mcp.area_risk_dsl_mcp` |
| Default transport | `http` |
| Default host | `0.0.0.0` |
| Default port | `11012` |
| Default path | `/mcp` |
| Default endpoint | `http://<host>:11012/mcp` |

Runtime environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AREA_RISK_DSL_MCP_TRANSPORT` | `http` | MCP transport. Use `stdio` only for stdio-mode clients. |
| `AREA_RISK_DSL_MCP_HOST` | `0.0.0.0` | MCP HTTP listen host. |
| `AREA_RISK_DSL_MCP_PORT` | `11012` | MCP HTTP listen port. |
| `AREA_RISK_DSL_MCP_PATH` | `/mcp` | MCP HTTP path. |
| `WEATHER_DIAG_CONFIG_DIR` | project `configs/` | Runtime config directory. |
| `WEATHER_DIAG_DATA_DIR` | project `data/` | Runtime data directory for app products; NAFP roots are configured separately. |

Production data-source config should point `NAFP_ECTHIN_NC.root` to the real
NAFP product root. For the current deployment discussion, the known online EC
root is:

```text
/data/Weather/NAFP/NAFP_ECTHIN_NC
```

Example production `configs/data_sources.yaml` item:

```yaml
data_sources:
  - code: NAFP_ECTHIN_NC
    label: ECTHIN
    name: NAFP_ECTHIN_NC
    model: EC
    format: nc
    root: /data/Weather/NAFP/NAFP_ECTHIN_NC
    forecast_hour_start: 0
    forecast_hour_end: 240
    forecast_hour_step: 3
    enabled: true
    default: true
```

## 2. Common Response Envelope

Both MCP tools return the same outer envelope.

Success:

```json
{
  "code": 0,
  "msg": "success",
  "data": {}
}
```

Top-level failure:

```json
{
  "code": 500,
  "msg": "获取乡镇风险 DSL 失败: <reason>",
  "data": {
    "error": "<reason>",
    "dsl_structure_guide": "..."
  }
}
```

For `get_point_risk`, the failure guide field is `response_guide` instead of
`dsl_structure_guide`.

Envelope fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `code` | integer | `0` means the tool call succeeded. `500` means the wrapper caught an exception before a normal payload could be returned. |
| `msg` | string | Human-readable status message. |
| `data` | object | Tool-specific payload on success, or error details on failure. |
| `data.error` | string | Failure reason when `code != 0`. |
| `data.dsl_structure_guide` | string | Town-risk DSL guide returned on `get_town_risk_dsl` wrapper failure. |
| `data.response_guide` | string | Point-risk JSON guide returned on `get_point_risk` wrapper failure. |

Important partial-failure rule:

- A tool call can return `code=0` while one or more products failed inside a
  time window. In multi-window mode, those failures are listed in
  `data.windows[].failures[]`.
- In legacy no-`windows` mode, `get_point_risk` uses `data.failures[]`, while
  `get_town_risk_dsl` keeps product-level failures under
  `data.area_risk.failed[]`.
- Third parties should inspect the failure location that matches the selected
  tool and mode; do not treat `code=0` as meaning every model run and every
  forecast hour was read successfully.

## 3. Common Time Rules

All matching is based on effective forecast time:

```text
valid_time = run_time + forecast_hour
```

Terms:

| Term | Meaning |
| --- | --- |
| `run_time` | Forecast initialization time, also called forecast start time or model cycle. |
| `forecast_hour` | Forecast lead time in hours. |
| `valid_time` | Effective time covered by one product. |
| `DT` in DSL | Forecast lead time in minutes, equal to `forecast_hour * 60`. |
| `start_time` / `end_time` | Requested valid-time window. Matching is inclusive: `start_time <= valid_time <= end_time`. |

Accepted time string format:

- ISO datetime such as `2026-06-17T08:00:00`
- Space-separated datetime accepted by Python `datetime.fromisoformat`, such as
  `2026-06-17 08:00:00`
- A trailing `Z` is stripped before parsing.

Window validation:

- `end_time` must be greater than or equal to `start_time`.
- `windows` must not be empty.
- Each window object must include parseable `start_time` and `end_time`.
- `label` is optional; omitted labels become `window_1`, `window_2`, etc.

## 4. Time Matching Policies

Both tools support the same three policies.

| Policy | Requires `run_time` | Behavior | Use Case |
| --- | --- | --- | --- |
| `single_latest_run` | No | Selects the first inventory run, ordered newest first, that has at least one forecast hour inside the requested valid-time window. This is the legacy-style behavior. | Keep one cycle per window and preserve old behavior as much as possible. |
| `fixed_run` | Yes | Uses only the caller-specified `run_time`, then keeps forecast hours whose valid time falls inside the window. If no forecast hour matches, the tool reports an error. | Audit one exact model cycle, or compare all windows against the same cycle. |
| `latest_per_valid_time` | No | For each valid time inside the window, selects the latest available run that can provide that valid time, then groups selected forecast hours by run. | Recommended for multi-window comparison, because a long window can cross more than one forecast cycle and still use the freshest product for each valid time. |

Defaults:

| Call Shape | Default Policy |
| --- | --- |
| No `windows` | `single_latest_run` |
| With `windows` | `latest_per_valid_time` |

Inventory limit:

- `latest_per_valid_time` scans up to 200 discovered run times.
- `single_latest_run` scans up to 50 discovered run times through the legacy
  context resolver.

## 5. Common Request Fields

| Field | Type | Required | Applies To | Default | Meaning |
| --- | --- | --- | --- | --- | --- |
| `models` | string | No | Both tools | `EC` | Model selector exposed by the MCP wrapper as a string. Multiple models are comma-separated, for example `EC,CMA-GFS`. |
| `data_code` | string or null | No | Both tools | Resolved from `models`; EC maps to configured default EC source | Data-source code from `configs/data_sources.yaml`, for example `NAFP_ECTHIN_NC`. If provided, it wins over model-name matching. |
| `start_time` | string or null | No | Legacy no-`windows` mode only | Current system time | Valid-time window start for legacy single-window calls. Ignored when `windows` is provided. |
| `end_time` | string or null | No | Legacy no-`windows` mode only | `start_time + 6h` | Valid-time window end for legacy single-window calls. Ignored when `windows` is provided. |
| `windows` | JSON string, object, or array | No | Both tools | None | Enables multi-window mode. One object is accepted and normalized to a one-item array. |
| `time_match_policy` | string or null | No | Both tools | See defaults above | One of `single_latest_run`, `fixed_run`, `latest_per_valid_time`. |
| `run_time` | string or null | Conditional | Both tools | None | Forecast cycle. Required when `time_match_policy=fixed_run`; optional for `single_latest_run`. |
| `include_window_summary` | boolean | No | Multi-window mode | `true` | Controls window-level summaries. Town tool emits or suppresses summary DSL blocks; point tool emits or suppresses summary arrays. Detail evidence is still returned. |

`windows` object fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `label` | string | No | Caller-defined window label, for example `yesterday`, `today`, `day_1`. In DSL, unsafe characters `|`, `;`, CR, LF are replaced by `_`. |
| `start_time` | string | Yes | Window valid-time start. |
| `end_time` | string | Yes | Window valid-time end. |

`windows` accepted shapes:

```json
[
  {"label": "yesterday", "start_time": "2026-06-17T08:00:00", "end_time": "2026-06-17T20:00:00"},
  {"label": "today", "start_time": "2026-06-18T08:00:00", "end_time": "2026-06-18T20:00:00"}
]
```

```json
{
  "windows": [
    {"label": "day_1", "start_time": "2026-06-17T08:00:00", "end_time": "2026-06-17T20:00:00"},
    {"label": "day_2", "start_time": "2026-06-18T08:00:00", "end_time": "2026-06-18T20:00:00"}
  ]
}
```

```json
{"label": "today", "start_time": "2026-06-18T08:00:00", "end_time": "2026-06-18T20:00:00"}
```

The examples above are tool argument objects. If the MCP client requires JSON
strings for complex arguments, serialize the same structure to a string.

## 6. Risk Field Dictionary

Risk scores are normalized risk values in the range `[0, 1]`. Higher values mean
higher risk.

Town DSL fields:

| Hazard Type | DSL Field | Source Grid | Meaning |
| --- | --- | --- | --- |
| `persistent_heavy_rain` | `R_PHR` | `risk_persistent_heavy_rain_score` | Persistent heavy-rain risk. |
| `short_duration_heavy_rain` | `R_SHR` | `risk_short_duration_heavy_rain_score` | Short-duration heavy-rain risk. |
| `thunderstorm_gale` | `R_TG` | `risk_thunderstorm_gale_score` | Thunderstorm gale or downburst risk. |
| `hail` | `R_HAIL` | `risk_hail_score` | Hail risk. |
| `rotating_storm_or_supercell` | `R_ROT` | `risk_rotating_storm_score` | Rotating storm or supercell potential. |
| `severe_convection_composite` | `R_SC` | `risk_severe_convection_composite_score` | Severe-convection composite risk. |

Risk level thresholds used by town summary DSL:

| Level | Condition |
| --- | --- |
| `high` | `score >= 0.75` |
| `watch` | `0.60 <= score < 0.75` |
| `low` | `score < 0.60` |

Point summary arrays reuse `risk_level` from the existing threshold matrix. In
the current summary rule, `watch` means `risk_level` is `moderate` or `high`,
and `high` means `risk_level` is `high`.

## 7. Physical Evidence Field Dictionary

Physical quantities are raw-unit evidence values. They are not normalized risk
scores and should not be compared as `[0, 1]` values.

| DSL Field | API Field | Unit | Direction | Watch Threshold | High Threshold | Meaning |
| --- | --- | --- | --- | --- | --- | --- |
| `CAPE` | `cape` | `J/kg` | `gte` | `1000` | `2000` | Convective available potential energy. Larger is more favorable. |
| `CIN` | `cin` | `J/kg` | `lte` | `150` | `50` | Convective inhibition. Smaller is more favorable by the current summary rule. |
| `Q850` | `q850_g_kg` | `g/kg` | `gte` | `8` | `12` | 850 hPa specific humidity. Values are converted to g/kg when source magnitude indicates kg/kg. |
| `PW` | `pw` | `mm` | `gte` | `30` | `55` | Precipitable water. |
| `W700` | `omega700` | `Pa/s` | `lte` | `-0.05` | `-0.35` | 700 hPa vertical velocity. More negative means stronger upward motion. |
| `SHR6` | `shear_0_6km` | `m/s` | `gte` | `12` | `20` | 0-6 km vertical wind shear. |
| `SHR1` | `shear_0_1km` | `m/s` | `gte` | `5` | `15` | 0-1 km vertical wind shear. |
| `KI` | `k_index` | `degC` | `gte` | `32` | `38` | K index. |
| `LI` | `li` | `degC` | `lte` | `0` | `-3` | Lifted index. Smaller is more unstable. |
| `DCAPE` | `dcape` | `J/kg` | `gte` | `500` | `1500` | Downdraft CAPE. |
| `SRH` | `srh` | `m2/s2` | `gte` | `100` | `300` | Storm-relative helicity. |
| `LCL` | `lcl` | `m` | `lte` | `1600` | `600` | Lifting condensation level. Lower is more favorable by the current summary rule. |
| `RH850` | `rh850` | `%` | `gte` | `60` | `90` | 850 hPa relative humidity. |
| `RH700` | `rh700` | `%` | `gte` | `60` | `90` | 700 hPa relative humidity. |
| `RH500` | `rh500` | `%` | `gte` | `50` | `80` | 500 hPa relative humidity. |
| `RAIN3` | `precip_3h` | `mm` | `gte` | `20` | `80` | 3-hour precipitation. |
| `RAIN6` | `precip_6h` | `mm` | `gte` | `20` | `80` | 6-hour precipitation. |
| `RAIN24` | `precip_24h` | `mm` | `gte` | `50` | `150` | 24-hour precipitation. |

Direction rules:

| Direction | Summary Extreme | Threshold Hit Rule |
| --- | --- | --- |
| `gte` | Larger value is more extreme. | `value >= threshold` |
| `lte` | Smaller value is more extreme. | `value <= threshold` |

Sampling rules:

| Tool | Risk Score Sampling | Physical Evidence Sampling |
| --- | --- | --- |
| `get_town_risk_dsl` | Samples town station points and uses the maximum risk score for each hazard/town/forecast hour. | Samples town station points and uses the mean physical value for each town/forecast hour. |
| `get_point_risk` | Samples the nearest model grid point for each requested latitude/longitude. | Samples the nearest model grid point for each requested latitude/longitude. |

## 8. `get_town_risk_dsl`

### 8.1 Purpose

`get_town_risk_dsl` returns town-level risk and physical evidence as
`FCST_TWN_PHY` DSL. It is suitable when the caller wants area/town coverage,
compact evidence text, and one or more comparison windows.

It returns evidence and deterministic summaries only. It does not generate a
cross-window natural-language conclusion. Third parties should compare the
window summaries or DSL values and generate their own conclusion.

### 8.2 Parameters

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `region` | string | No | `xiamen` at MCP wrapper level | Region code or alias. Existing aliases include `xiamen` and `fuzhou`; numeric region codes are also resolved through the area registry. |
| `start_time` | string or null | No | Current system time | Legacy no-`windows` valid-time start. |
| `end_time` | string or null | No | `start_time + 6h` | Legacy no-`windows` valid-time end. |
| `models` | string | No | `EC` | Model selector, comma-separated when multiple. |
| `data_code` | string or null | No | Resolved from `models` | Data-source code. |
| `windows` | JSON string, object, array, or null | No | None | Enables multi-window mode. |
| `time_match_policy` | string or null | No | `single_latest_run` without `windows`; `latest_per_valid_time` with `windows` | Time matching policy. |
| `run_time` | string or null | Conditional | None | Forecast cycle. Required by `fixed_run`. |
| `include_window_summary` | boolean | No | `true` | Whether multi-window DSL includes risk and physical summary blocks. |

### 8.3 Legacy Single-Window Request Example

```json
{
  "region": "xiamen",
  "start_time": "2026-06-18T10:00:00",
  "end_time": "2026-06-18T20:00:00",
  "models": "EC",
  "data_code": "NAFP_ECTHIN_NC"
}
```

Legacy response shape:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "request": {
      "region": "xiamen",
      "start_time": "2026-06-18T10:00:00",
      "end_time": "2026-06-18T20:00:00",
      "models": ["EC"]
    },
    "region": {
      "region_code": "350200",
      "region_level": "city",
      "region_name": "厦门市",
      "town_count": 46
    },
    "model_metadata": [
      {
        "model": "EC",
        "data_code": "NAFP_ECTHIN_NC",
        "run_time": "2026-06-18T08:00:00",
        "forecast_hours": [3, 6, 9, 12]
      }
    ],
    "risk_metadata": {},
    "dsl": "@B:FCST_TWN_PHY;\n...",
    "dsl_structure_guide": "..."
  }
}
```

Legacy `data` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `request` | object | Normalized request echo. |
| `region` | object | Public region metadata. Does not include town point geometry. |
| `model_metadata` | array | Selected model cycles and forecast hours. |
| `risk_metadata` | object | Risk metadata keyed by hazard type. Includes `dsl_field`, `source_grid`, `score_range`, `score_unit`, and `score_direction`. |
| `dsl` | string | Complete `FCST_TWN_PHY` DSL for the selected single time window. |
| `dsl_structure_guide` | string | Human-readable DSL guide. |

### 8.4 Multi-Window Request Example

Business question: compare yesterday and today. The caller should first convert
relative words such as "yesterday" and "today" into concrete valid-time windows.
The following example uses fixed concrete dates.

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
      "start_time": "2026-06-17T08:00:00",
      "end_time": "2026-06-17T20:00:00"
    },
    {
      "label": "today",
      "start_time": "2026-06-18T08:00:00",
      "end_time": "2026-06-18T20:00:00"
    }
  ]
}
```

Multi-window response shape:

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
      "town_count": 46
    },
    "risk_metadata": {},
    "windows": [
      {
        "label": "yesterday",
        "start_time": "2026-06-17T08:00:00",
        "end_time": "2026-06-17T20:00:00",
        "time_match_policy": "latest_per_valid_time",
        "model_metadata": [
          {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T08:00:00",
            "forecast_hours": [0, 3, 6, 9, 12],
            "valid_times": [
              "2026-06-17T08:00:00",
              "2026-06-17T11:00:00",
              "2026-06-17T14:00:00",
              "2026-06-17T17:00:00",
              "2026-06-17T20:00:00"
            ]
          }
        ],
        "dsl": "@B:FCST_TWN_PHY;\n...",
        "failures": []
      },
      {
        "label": "today",
        "start_time": "2026-06-18T08:00:00",
        "end_time": "2026-06-18T20:00:00",
        "time_match_policy": "latest_per_valid_time",
        "model_metadata": [
          {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-18T08:00:00",
            "forecast_hours": [0, 3, 6, 9, 12],
            "valid_times": [
              "2026-06-18T08:00:00",
              "2026-06-18T11:00:00",
              "2026-06-18T14:00:00",
              "2026-06-18T17:00:00",
              "2026-06-18T20:00:00"
            ]
          }
        ],
        "dsl": "@B:FCST_TWN_PHY;\n...",
        "failures": []
      }
    ],
    "dsl_structure_guide": "..."
  }
}
```

`data.windows[]` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `label` | string | Window label after normalization. |
| `start_time` | string | Window valid-time start in ISO format. |
| `end_time` | string | Window valid-time end in ISO format. |
| `time_match_policy` | string | Effective policy used by this response. |
| `model_metadata` | array | Selected model/run groups for this window. Empty if all products failed or no model produced data. |
| `dsl` | string | Complete DSL for this window. Can be empty if all selected products failed. |
| `failures` | array | Per-model/per-run/per-hour failure details. |

`model_metadata[]` fields in multi-window mode:

| Field | Type | Meaning |
| --- | --- | --- |
| `model` | string | Resolved model name, for example `EC`. |
| `data_code` | string | Resolved data-source code. |
| `run_time` | string | Selected model cycle. |
| `forecast_hours` | integer array | Forecast hours used from this run. |
| `valid_times` | string array | Effective times corresponding to `forecast_hours`. |

`failures[]` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `model` | string | Model involved in the failure, when available. |
| `data_code` | string or null | Data-source code involved in the failure, when available. |
| `run_time` | string | Run time involved in the failure, when available. |
| `forecast_hour` | integer | Forecast hour involved in the failure, for single-hour product failures. |
| `forecast_hours` | integer array | Forecast hours involved in the failure, for grouped run failures. |
| `error` | string | Failure reason. |

### 8.5 DSL Structure

A single-window DSL has one header and one `#PHY` block.

A multi-window DSL has:

1. One common header for the window and model.
2. One `@WIN` line for the requested window.
3. One `@ORD` line describing every `#PHY` row.
4. One `@PHY_ORD` line describing every `@PHY` dictionary row.
5. One `@PHY` dictionary row per risk/physical field.
6. One repeated `@T` + `@DT` + `#PHY` group per selected `run_time`.
7. Optional summary blocks when `include_window_summary=true`.

There is no `#RUN` marker. The run boundary is represented by each repeated
`@T` line. The `@ORD` line applies to every following `#PHY` row in that window
DSL.

If multiple models are requested, each model contributes its own complete DSL
block, and blocks are joined by blank lines.

DSL line dictionary:

| Line | Meaning |
| --- | --- |
| `@B:FCST_TWN_PHY;` | DSL business type: forecast, town granularity, physical/risk fields. |
| `@A:<region_code>;` | Region administrative code. |
| `@CR:S5=县区3位短码+乡镇2位短码;` | S5 town code rule. |
| `@S:<county_short>=<county_name>><s5><town_name>,...;` | County-to-town S5 mapping. |
| `@M:<model>;` | Model name. |
| `@WIN:<label>|<start_time>|<end_time>;` | Multi-window metadata. Present only in multi-window DSL. |
| `@T:<yyMMddHHmm>;` | Forecast run time. Example: `2606170800`. |
| `@DT:<minutes>,...;` | Forecast lead times in minutes. Example: `0,180,360`. |
| `@WIN_RULE:VALID=@T+DT;` | Effective-time calculation rule. |
| `@ORD:DT>S5=<field list>;` | Body row order: lead time, then S5 town code, then pipe-separated field values. |
| `@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;` | Field dictionary order. |
| `@PHY:<PID>=<api>|<unit>|<direction>|<watch>|<high>;` | Field dictionary row. |
| `#PHY:` | Detail body block. |
| `<DT>><S5>=v1|v2|...;` | One detail row. Values follow `@ORD` field order. Missing values are `NA`. |
| `@SUM_RISK_ORD:...;` | Region risk summary order. |
| `#SUMMARY_RISK:` | Region risk summary block. |
| `@SUM_TOWN_RISK_ORD:...;` | Town risk summary order. |
| `#SUMMARY_TOWN_RISK:` | Town risk summary block. |
| `@SUM_PHY_ORD:...;` | Region physical summary order. |
| `#SUMMARY_PHY:` | Region physical summary block. |
| `@SUM_TOWN_PHY_ORD:...;` | Town physical summary order. |
| `#SUMMARY_TOWN_PHY:` | Town physical summary block. |

### 8.6 Multi-Run DSL Example

The following is a structural example. Values are examples only.

```text
@B:FCST_TWN_PHY;
@A:350200;
@CR:S5=县区3位短码+乡镇2位短码;
@S:203=思明区>20301莲前街道,20302筼筜街道;
@M:EC;
@WIN:today|2026-06-18T08:00:00|2026-06-18T23:00:00;
@WIN_RULE:VALID=@T+DT;
@ORD:DT>S5=R_PHR|R_SHR|R_TG|R_HAIL|R_ROT|R_SC|CAPE|CIN|Q850|PW|W700|SHR6|SHR1|KI|LI|DCAPE|SRH|LCL|RH850|RH700|RH500|RAIN3|RAIN6|RAIN24;
@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;
@PHY:R_PHR=risk_persistent_heavy_rain_score|risk_score_0_1|gte|0.6|0.75;
@PHY:R_SHR=risk_short_duration_heavy_rain_score|risk_score_0_1|gte|0.6|0.75;
@PHY:R_TG=risk_thunderstorm_gale_score|risk_score_0_1|gte|0.6|0.75;
@PHY:R_HAIL=risk_hail_score|risk_score_0_1|gte|0.6|0.75;
@PHY:R_ROT=risk_rotating_storm_score|risk_score_0_1|gte|0.6|0.75;
@PHY:R_SC=risk_severe_convection_composite_score|risk_score_0_1|gte|0.6|0.75;
@PHY:CAPE=cape|J/kg|gte|1000|2000;
@PHY:CIN=cin|J/kg|lte|150|50;
@PHY:Q850=q850_g_kg|g/kg|gte|8|12;

@T:2606180800;
@DT:0,180,360,540,720;
#PHY:
0>20301=0.10|0.32|0.21|0.05|0.12|0.34|1200.00|80.00|10.50|42.00|-0.12|15.00|7.00|34.00|-1.20|700.00|120.00|900.00|75.00|68.00|55.00|8.00|18.00|45.00;
180>20301=0.12|0.48|0.25|0.08|0.16|0.52|1600.00|60.00|11.20|46.00|-0.18|17.00|8.00|36.00|-2.00|850.00|150.00|850.00|80.00|70.00|58.00|12.00|24.00|50.00;

@T:2606182000;
@DT:0,180;
#PHY:
0>20301=0.20|0.62|0.41|0.11|0.26|0.66|2100.00|45.00|13.00|58.00|-0.38|22.00|11.00|39.00|-3.40|1600.00|260.00|620.00|90.00|82.00|70.00|25.00|48.00|86.00;

@SUM_RISK_ORD:FIELD=MAX|MAX_VALID|MAX_S5|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
#SUMMARY_RISK:
R_SC=0.66|2606182000|20301|0|1|1|1;
@SUM_TOWN_RISK_ORD:S5>FIELD=MAX|MAX_VALID|MAX_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
#SUMMARY_TOWN_RISK:
20301>R_SC=0.66|2606182000|watch|1|0;

@SUM_PHY_ORD:PID=EXTREME|EXTREME_VALID|EXTREME_S5|EXTREME_LEVEL|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
#SUMMARY_PHY:
CAPE=2100.00|2606182000|20301|high|1|1|1|3;
CIN=45.00|2606182000|20301|high|1|1|1|3;
@SUM_TOWN_PHY_ORD:S5>PID=EXTREME|EXTREME_VALID|EXTREME_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
#SUMMARY_TOWN_PHY:
20301>CAPE=2100.00|2606182000|high|3|1;
20301>CIN=45.00|2606182000|high|3|1;
```

### 8.7 Summary DSL Rules

Risk summary order:

```text
@SUM_RISK_ORD:FIELD=MAX|MAX_VALID|MAX_S5|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
```

| Field | Meaning |
| --- | --- |
| `FIELD` | Risk DSL field such as `R_SC`. |
| `MAX` | Maximum risk score in this window for this field. |
| `MAX_VALID` | Valid time of `MAX`, formatted as `yyMMddHHmm`. |
| `MAX_S5` | S5 town code where `MAX` occurs. |
| `HIGH_CNT_PEAK` | Maximum count of high-risk towns at any one valid time. |
| `WATCH_CNT_PEAK` | Maximum count of watch-or-above towns at any one valid time. |
| `WATCH_TOWN_ANY` | Count of distinct towns that reached watch-or-above at least once in the window. |
| `ACTIVE_DT_CNT` | Count of valid times where at least one town reached watch-or-above. |

Town risk summary order:

```text
@SUM_TOWN_RISK_ORD:S5>FIELD=MAX|MAX_VALID|MAX_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
```

| Field | Meaning |
| --- | --- |
| `S5` | Town short code. |
| `FIELD` | Risk DSL field such as `R_SC`. |
| `MAX` | Maximum risk score for this town and risk field in the window. |
| `MAX_VALID` | Valid time of `MAX`, formatted as `yyMMddHHmm`. |
| `MAX_LEVEL` | `high`, `watch`, or `low` using town summary thresholds. |
| `WATCH_DT_CNT` | Number of detail rows where this town reached watch-or-above. |
| `HIGH_DT_CNT` | Number of detail rows where this town reached high. |

Physical summary order:

```text
@SUM_PHY_ORD:PID=EXTREME|EXTREME_VALID|EXTREME_S5|EXTREME_LEVEL|HIGH_CNT_PEAK|WATCH_CNT_PEAK|WATCH_TOWN_ANY|ACTIVE_DT_CNT;
```

| Field | Meaning |
| --- | --- |
| `PID` | Physical field id such as `CAPE` or `CIN`. |
| `EXTREME` | Extreme physical value in the window. `gte` fields use max; `lte` fields use min. |
| `EXTREME_VALID` | Valid time of `EXTREME`, formatted as `yyMMddHHmm`. |
| `EXTREME_S5` | S5 town code where `EXTREME` occurs. |
| `EXTREME_LEVEL` | `high`, `watch`, or `low` using this field's direction and thresholds. |
| `HIGH_CNT_PEAK` | Maximum count of high-threshold towns at any one valid time. |
| `WATCH_CNT_PEAK` | Maximum count of watch-threshold towns at any one valid time. |
| `WATCH_TOWN_ANY` | Count of distinct towns that reached watch threshold at least once. |
| `ACTIVE_DT_CNT` | Count of valid times where at least one town reached watch threshold. |

Town physical summary order:

```text
@SUM_TOWN_PHY_ORD:S5>PID=EXTREME|EXTREME_VALID|EXTREME_LEVEL|WATCH_DT_CNT|HIGH_DT_CNT;
```

| Field | Meaning |
| --- | --- |
| `S5` | Town short code. |
| `PID` | Physical field id. |
| `EXTREME` | Extreme physical value for this town and field in the window. |
| `EXTREME_VALID` | Valid time of `EXTREME`, formatted as `yyMMddHHmm`. |
| `EXTREME_LEVEL` | `high`, `watch`, or `low`. |
| `WATCH_DT_CNT` | Number of detail rows where this town met the field's watch threshold. |
| `HIGH_DT_CNT` | Number of detail rows where this town met the field's high threshold. |

## 9. `get_point_risk`

### 9.1 Purpose

`get_point_risk` returns point-level risk and physical evidence as JSON. It is
suitable when the caller asks about one or more exact latitude/longitude points.

This tool does not output DSL. It returns detail `items[]` plus optional summary
arrays in multi-window mode.

### 9.2 Parameters

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `points` | string, object, or array | Yes | None | Requested point or point list. |
| `start_time` | string or null | No | Current system time | Legacy no-`windows` valid-time start. |
| `end_time` | string or null | No | `start_time + 6h` | Legacy no-`windows` valid-time end. |
| `models` | string | No | `EC` | Model selector, comma-separated when multiple. |
| `data_code` | string or null | No | Resolved from `models` | Data-source code. |
| `windows` | JSON string, object, array, or null | No | None | Enables multi-window mode. |
| `time_match_policy` | string or null | No | `single_latest_run` without `windows`; `latest_per_valid_time` with `windows` | Time matching policy. |
| `run_time` | string or null | Conditional | None | Forecast cycle. Required by `fixed_run`. |
| `include_window_summary` | boolean | No | `true` | Whether multi-window mode fills summary arrays. |

### 9.3 `points` Accepted Shapes

Structured array:

```json
[
  {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08},
  {"id": "P2", "name": "同安站", "lat": 24.73, "lon": 118.15}
]
```

Single object:

```json
{"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08}
```

Array tuple form:

```json
[
  [24.48, 118.08, "P1", "厦门站"],
  [24.73, 118.15, "P2", "同安站"]
]
```

Legacy text form:

```text
24.48,118.08,厦门站;24.73,118.15,同安站
```

Point normalization:

| Output Field | Meaning |
| --- | --- |
| `id` | Caller-supplied id, or auto-generated `P1`, `P2`, etc. Explicit IDs must be unique in one request. |
| `name` | Caller-supplied name, or the point id. |
| `lat` | Latitude rounded to 6 decimals. |
| `lon` | Longitude rounded to 6 decimals. |

### 9.4 Legacy Single-Window Request Example

```json
{
  "points": [
    {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08}
  ],
  "start_time": "2026-06-18T10:00:00",
  "end_time": "2026-06-18T20:00:00",
  "models": "EC",
  "data_code": "NAFP_ECTHIN_NC"
}
```

Legacy response shape:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "request": {
      "points": [
        {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08}
      ],
      "start_time": "2026-06-18T10:00:00",
      "end_time": "2026-06-18T20:00:00",
      "models": ["EC"]
    },
    "points": [
      {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08}
    ],
    "model_metadata": [
      {
        "model": "EC",
        "data_code": "NAFP_ECTHIN_NC",
        "run_time": "2026-06-18T08:00:00",
        "forecast_hours": [3, 6, 9, 12]
      }
    ],
    "risk_metadata": {},
    "items": [],
    "failures": [],
    "response_guide": "..."
  }
}
```

### 9.5 Multi-Window Request Example

```json
{
  "points": [
    {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08},
    {"id": "P2", "name": "同安站", "lat": 24.73, "lon": 118.15}
  ],
  "models": "EC",
  "data_code": "NAFP_ECTHIN_NC",
  "time_match_policy": "latest_per_valid_time",
  "include_window_summary": true,
  "windows": [
    {
      "label": "yesterday",
      "start_time": "2026-06-17T08:00:00",
      "end_time": "2026-06-17T20:00:00"
    },
    {
      "label": "today",
      "start_time": "2026-06-18T08:00:00",
      "end_time": "2026-06-18T20:00:00"
    }
  ]
}
```

Multi-window response shape:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "mode": "multi_window_point_risk",
    "request": {
      "points": [
        {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08},
        {"id": "P2", "name": "同安站", "lat": 24.73, "lon": 118.15}
      ],
      "models": ["EC"],
      "data_code": "NAFP_ECTHIN_NC",
      "time_match_policy": "latest_per_valid_time",
      "include_window_summary": true
    },
    "points": [
      {"id": "P1", "name": "厦门站", "lat": 24.48, "lon": 118.08},
      {"id": "P2", "name": "同安站", "lat": 24.73, "lon": 118.15}
    ],
    "risk_metadata": {},
    "windows": [
      {
        "label": "yesterday",
        "start_time": "2026-06-17T08:00:00",
        "end_time": "2026-06-17T20:00:00",
        "time_match_policy": "latest_per_valid_time",
        "model_metadata": [],
        "items": [],
        "risk_summary": [],
        "point_summary": [],
        "physical_summary": [],
        "point_physical_summary": [],
        "failures": []
      },
      {
        "label": "today",
        "start_time": "2026-06-18T08:00:00",
        "end_time": "2026-06-18T20:00:00",
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

`data.windows[]` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `label` | string | Window label after normalization. |
| `start_time` | string | Window valid-time start in ISO format. |
| `end_time` | string | Window valid-time end in ISO format. |
| `time_match_policy` | string | Effective policy used by this response. |
| `model_metadata` | array | Selected model/run groups. |
| `items` | array | Detail evidence per model, forecast hour, and point. |
| `risk_summary` | array | Window-level risk summary grouped by `model + data_code + hazard_type`. Empty when `include_window_summary=false`. |
| `point_summary` | array | Point-level risk summary grouped by `model + data_code + point_id + hazard_type`. Empty when `include_window_summary=false`. |
| `physical_summary` | array | Window-level physical summary grouped by `model + data_code + field`. Empty when `include_window_summary=false`. |
| `point_physical_summary` | array | Point-level physical summary grouped by `model + data_code + point_id + field`. Empty when `include_window_summary=false`. |
| `failures` | array | Per-model/per-run/per-hour failure details. |

### 9.6 `items[]` Fields

Each `items[]` row represents one model, one forecast hour, and one requested
point.

| Field | Type | Meaning |
| --- | --- | --- |
| `model` | string | Resolved model name. |
| `data_code` | string | Resolved data-source code. |
| `run_time` | string | Forecast cycle in ISO format. |
| `forecast_hour` | integer | Forecast lead time in hours. |
| `valid_time` | string | Effective time, `run_time + forecast_hour`. |
| `point` | object | Normalized requested point. |
| `sample_method` | string | Always `nearest_grid_point`. |
| `nearest_grid_point` | object | Actual grid point sampled from the model field. |
| `risks` | array | Six multi-hazard risk results for this point/time. |
| `physical_evidence` | object | Raw physical evidence dictionary keyed by physical field id. |

`nearest_grid_point` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `lat` | number | Latitude of sampled grid point. |
| `lon` | number | Longitude of sampled grid point. |
| `lat_index` | integer | Latitude index in the source grid. |
| `lon_index` | integer | Longitude index in the source grid. |
| `distance_degrees` | number | Euclidean distance in grid coordinate degrees between requested and sampled point. |
| `outside_domain` | boolean | Whether requested point is outside source grid latitude/longitude bounds. Sampling still uses nearest grid point. |
| `normalized_query_lon` | number | Query longitude after normalization for grids using `0..360` or `-180..180`. |

`risks[]` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `hazard_type` | string | One of the six hazard types in the risk dictionary. |
| `label` | string | Human-readable hazard label from risk metadata. |
| `risk_domain` | string array | Risk domain tags, for example precipitation or severe convection. |
| `mechanism_tags` | string array | Mechanism tags from risk metadata. |
| `source_grid` | string | Source risk score grid. |
| `score` | number | Risk score in `[0, 1]`. |
| `risk_level` | string | Level from threshold matrix. |
| `level` | string | Same value as `risk_level`, retained for compatibility. |
| `score_source` | string | `source_grid`. |
| `score_range` | number array | `[0, 1]`. |
| `score_unit` | string | `risk_score`. |
| `evidence_chain` | object | Dominant-factor evidence sampled at the same nearest grid point. |

`evidence_chain` fields inside `risks[]`:

| Field | Type | Meaning |
| --- | --- | --- |
| `hazard_type` | string | Hazard type this chain explains. |
| `source_grid` | string | Source risk score grid. |
| `sampling_method` | string | `nearest_grid_point`. |
| `sample_point` | object | Same structure as `nearest_grid_point`. |
| `dominant_factors` | array | Up to five positive-contribution factors. |

`dominant_factors[]` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `factor` | string | Internal factor id. |
| `field` | string | Physical or diagnostic field behind the factor. |
| `label` | string | Human-readable factor label. |
| `weight` | number | Factor weight. |
| `score` | number | Factor score sampled at the point. |
| `contribution` | number | Weighted contribution. |

`physical_evidence` item fields:

```json
{
  "CAPE": {
    "value": 1800.25,
    "label": "CAPE",
    "api": "cape",
    "unit": "J/kg",
    "direction": "gte",
    "watch": 1000,
    "high": 2000,
    "sample_method": "nearest_grid_point"
  }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `value` | number | Raw physical value sampled at the nearest grid point. |
| `label` | string | Human-readable label. |
| `api` | string | API/source field name. |
| `unit` | string | Business unit. |
| `direction` | string | `gte` or `lte`; controls threshold and extreme rules. |
| `watch` | number | Watch threshold. |
| `high` | number | High threshold. |
| `sample_method` | string | Always `nearest_grid_point` for point-risk MCP. |

### 9.7 Point Summary Arrays

`risk_summary[]` groups all detail `items[]` by:

```text
model + data_code + hazard_type
```

| Field | Meaning |
| --- | --- |
| `model` | Model name. |
| `data_code` | Data-source code. |
| `hazard_type` | Hazard type. |
| `max` | Maximum point risk score in this window/group. |
| `max_level` | Risk level of the row that produced `max`. |
| `max_valid_time` | Valid time of `max`. |
| `max_point_id` | Point id where `max` occurs. |
| `max_point_name` | Point name where `max` occurs. |
| `max_run_time` | Forecast cycle of `max`. |
| `max_forecast_hour` | Forecast hour of `max`. |
| `high_point_peak` | Maximum count of high-risk points at any one valid time. |
| `watch_point_peak` | Maximum count of watch-or-above points at any one valid time. |
| `watch_point_any` | Count of distinct points that reached watch-or-above at least once. |
| `active_valid_time_count` | Count of valid times where at least one point reached watch-or-above. |
| `item_count` | Number of risk detail rows included in this group. |

`point_summary[]` groups by:

```text
model + data_code + point_id + hazard_type
```

| Field | Meaning |
| --- | --- |
| `model` | Model name. |
| `data_code` | Data-source code. |
| `point_id` | Point id. |
| `point_name` | Point name. |
| `hazard_type` | Hazard type. |
| `max` | Maximum risk score for this point and hazard. |
| `max_level` | Risk level of `max`. |
| `max_valid_time` | Valid time of `max`. |
| `max_run_time` | Forecast cycle of `max`. |
| `max_forecast_hour` | Forecast hour of `max`. |
| `watch_valid_time_count` | Number of valid times where this point reached watch-or-above. |
| `high_valid_time_count` | Number of valid times where this point reached high. |
| `item_count` | Number of risk detail rows included in this group. |

`physical_summary[]` groups by:

```text
model + data_code + field
```

| Field | Meaning |
| --- | --- |
| `model` | Model name. |
| `data_code` | Data-source code. |
| `field` | Physical field id, such as `CAPE`. |
| `api` | API/source field name. |
| `label` | Human-readable label. |
| `unit` | Unit. |
| `direction` | `gte` or `lte`. |
| `watch` | Watch threshold. |
| `high` | High threshold. |
| `extreme` | Extreme physical value in this window/group. `gte` uses max; `lte` uses min. |
| `extreme_level` | `high`, `watch`, or `low` for `extreme`. |
| `extreme_valid_time` | Valid time of `extreme`. |
| `extreme_point_id` | Point id where `extreme` occurs. |
| `extreme_point_name` | Point name where `extreme` occurs. |
| `extreme_run_time` | Forecast cycle of `extreme`. |
| `extreme_forecast_hour` | Forecast hour of `extreme`. |
| `high_point_peak` | Maximum count of high-threshold points at any one valid time. |
| `watch_point_peak` | Maximum count of watch-threshold points at any one valid time. |
| `watch_point_any` | Count of distinct points that reached watch threshold at least once. |
| `active_valid_time_count` | Count of valid times where at least one point reached watch threshold. |
| `item_count` | Number of physical detail rows included in this group. |

`point_physical_summary[]` groups by:

```text
model + data_code + point_id + field
```

| Field | Meaning |
| --- | --- |
| `model` | Model name. |
| `data_code` | Data-source code. |
| `point_id` | Point id. |
| `point_name` | Point name. |
| `field` | Physical field id. |
| `api` | API/source field name. |
| `label` | Human-readable label. |
| `unit` | Unit. |
| `direction` | `gte` or `lte`. |
| `watch` | Watch threshold. |
| `high` | High threshold. |
| `extreme` | Extreme value for this point and field. |
| `extreme_level` | `high`, `watch`, or `low`. |
| `extreme_valid_time` | Valid time of `extreme`. |
| `extreme_run_time` | Forecast cycle of `extreme`. |
| `extreme_forecast_hour` | Forecast hour of `extreme`. |
| `watch_valid_time_count` | Number of valid times where this point met watch threshold. |
| `high_valid_time_count` | Number of valid times where this point met high threshold. |
| `item_count` | Number of physical detail rows included in this group. |

### 9.8 Point Summary Example

Example values only:

```json
{
  "risk_summary": [
    {
      "model": "EC",
      "data_code": "NAFP_ECTHIN_NC",
      "hazard_type": "severe_convection_composite",
      "max": 0.82,
      "max_level": "high",
      "max_valid_time": "2026-06-18T20:00:00",
      "max_point_id": "P1",
      "max_point_name": "厦门站",
      "max_run_time": "2026-06-18T08:00:00",
      "max_forecast_hour": 12,
      "high_point_peak": 1,
      "watch_point_peak": 2,
      "watch_point_any": 2,
      "active_valid_time_count": 3,
      "item_count": 10
    }
  ],
  "physical_summary": [
    {
      "model": "EC",
      "data_code": "NAFP_ECTHIN_NC",
      "field": "CAPE",
      "api": "cape",
      "label": "CAPE",
      "unit": "J/kg",
      "direction": "gte",
      "watch": 1000,
      "high": 2000,
      "extreme": 2380.5,
      "extreme_level": "high",
      "extreme_valid_time": "2026-06-18T20:00:00",
      "extreme_point_id": "P1",
      "extreme_point_name": "厦门站",
      "extreme_run_time": "2026-06-18T08:00:00",
      "extreme_forecast_hour": 12,
      "high_point_peak": 1,
      "watch_point_peak": 2,
      "watch_point_any": 2,
      "active_valid_time_count": 4,
      "item_count": 10
    }
  ]
}
```

## 10. Comparison Guidance For Third Parties

The tools provide evidence per requested window. They do not decide the final
cross-window conclusion.

Recommended comparison workflow:

1. Convert the question's relative dates to concrete windows. For example,
   "昨天和今天" becomes two windows such as `2026-06-17T08:00:00` to
   `2026-06-17T20:00:00`, and `2026-06-18T08:00:00` to
   `2026-06-18T20:00:00`.
2. Call one tool once with both windows.
3. Compare the same summary fields across windows.
4. Generate the third-party conclusion from those differences.

Examples:

| Question | Evidence To Compare |
| --- | --- |
| Today vs yesterday severe-convection environment | `R_SC` in `#SUMMARY_RISK`, `CAPE`, `SHR6`, `LI`, `DCAPE`, `SRH`, `PW` in `#SUMMARY_PHY`, or the matching point JSON summaries. |
| Which day has stronger short-duration heavy-rain support? | `R_SHR.MAX`, `PW.EXTREME`, `Q850.EXTREME`, `W700.EXTREME`, `RAIN3/RAIN6/RAIN24`, plus town/point watch counts. |
| Is the affected area wider today? | `WATCH_TOWN_ANY`, `WATCH_CNT_PEAK`, `ACTIVE_DT_CNT` in town DSL, or `watch_point_any`, `watch_point_peak`, `active_valid_time_count` in point JSON. |
| Where is the strongest signal? | `MAX_S5` / `EXTREME_S5` in town DSL, or `max_point_id` / `extreme_point_id` in point JSON. |

Recommended comparison metrics:

| Metric Type | Meaning |
| --- | --- |
| Extreme value | Compares peak intensity, such as `R_SC.MAX` or `CAPE.EXTREME`. |
| Peak affected count | Compares maximum simultaneous impact scope, such as `WATCH_CNT_PEAK`. |
| Any affected count | Compares total distinct affected towns/points, such as `WATCH_TOWN_ANY`. |
| Active valid-time count | Compares duration or persistence within the window. |
| Location of max/extreme | Compares where the strongest signal occurs. |

## 11. Error And Empty Data Handling

Top-level errors return `code=500` when the wrapper cannot produce a normal
payload. Common causes:

| Cause | Example Error |
| --- | --- |
| Empty `windows` | `windows must not be empty` |
| Invalid window object | `window at index 1 must be an object` |
| Missing or invalid time | `time value is required` |
| End before start | `end_time must be >= start_time` |
| Unsupported policy | `unsupported time_match_policy: ...` |
| Missing `run_time` for fixed policy | `run_time is required when time_match_policy=fixed_run` |
| Unknown data code | `unknown data code: ...` |
| Unsupported model | `unsupported model: ...` |
| No matching run | `no NAFP run time matched the requested time window` |
| Duplicate point id | `duplicate point id: ...` |

Partial failures are represented by `failures[]`. Common causes:

| Cause | How It Appears |
| --- | --- |
| Missing forecast-hour product file | A failure item with `forecast_hour` and `error`. |
| A run was selected but one hour failed to load | Detail rows for other hours may still appear; failed hour is listed in `failures[]`. |
| All products failed in a window | `dsl` or `items` may be empty, and `failures[]` contains the reasons. |

In legacy no-`windows` mode, use `data.failures[]` for `get_point_risk` and
`data.area_risk.failed[]` for `get_town_risk_dsl`.

Client recommendations:

- Treat `code != 0` as no usable payload.
- Treat `code = 0` with non-empty `data.windows[].failures[]`,
  `data.failures[]`, or `data.area_risk.failed[]` as partial data.
- For comparison answers, mention incomplete evidence if either compared window
  has failures or empty detail output.
- Do not compare physical quantities with risk-score thresholds. Use each
  physical field's own `direction`, `watch`, and `high`.

## 12. Performance Notes

The cost is roughly proportional to selected products:

```text
selected model runs * selected forecast hours * towns/points * risk fields
```

Implemented reuse:

- Multi-window town-risk calls share request-scoped `_risk_input_bundle` and
  score-detail caches for repeated `root + run_time + forecast_hour`.
- Multi-window point-risk calls share request-scoped `_risk_input_bundle` and
  `multi_hazard_score_details` caches for repeated
  `root + data_code + run_time + forecast_hour`.

Practical guidance:

- Use multi-window calls instead of making one call per day when the third party
  needs comparison evidence.
- Prefer `latest_per_valid_time` for broad windows that may cross forecast
  cycles.
- Prefer `fixed_run` only when the caller intentionally wants one model cycle.
- Keep windows to the business period needed for the question. Very broad
  windows increase product reads and response size.
- Set `include_window_summary=false` only if the client will not use summaries;
  detail evidence remains the largest part of most responses.

## 13. Deployment Checklist

Before exposing the MCP endpoint:

- Python dependencies from `backend/requirements.txt` must be installed, or the
  service must run from a Docker image built from `backend/Dockerfile`.
- `fastmcp` must be installed; otherwise the MCP server exits with
  `fastmcp is required to run this MCP server`.
- `configs/data_sources.yaml` must point enabled data sources to real online
  data roots.
- The confirmed deployment directory for this service is
  `/home/hwapp/ruiyun-bdp/bdp-dm/bdp-dm-phys-diagnosis`.
- Online EC root should be mounted/readable at
  `/data/Weather/NAFP/NAFP_ECTHIN_NC` for `NAFP_ECTHIN_NC`.
- The MCP port, default `11012`, must be allowed by local firewall and platform
  network policy.
- The caller must be told whether complex arguments should be sent as structured
  MCP values or JSON strings, depending on its MCP client implementation.

Minimum manual smoke checks after deployment:

1. Start MCP server.
2. Call `get_town_risk_dsl` with one short fixed window and verify `code=0`.
3. Call `get_point_risk` with one point and one short fixed window and verify
   `code=0`.
4. Check `failures[]`. A successful service startup does not prove all NAFP
   product paths are available.
5. Verify the returned `model_metadata[].run_time`, `forecast_hours`, and
   `valid_times` match the expected online product inventory.

## 14. Contract Checklist For Third-Party Consumers

Consumers should support:

- Outer envelope: `code`, `msg`, `data`.
- Legacy and multi-window modes.
- `data.windows[]` arrays.
- Empty `dsl`, empty `items`, and non-empty `failures[]`.
- Multiple `@T/@DT/#PHY` groups inside one `window.dsl`.
- DSL summary blocks: `#SUMMARY_RISK`, `#SUMMARY_TOWN_RISK`,
  `#SUMMARY_PHY`, `#SUMMARY_TOWN_PHY`.
- Physical values with raw units and per-field directions.
- Point summary arrays:
  `risk_summary`, `point_summary`, `physical_summary`,
  `point_physical_summary`.
- Structured `points` and `windows`, or JSON-string fallback if their MCP
  client requires string transport for complex arguments.
