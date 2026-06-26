# API 说明

## Public v1 Response Envelope

第三方服务接口统一放在 `/api/v1` 下，响应结构为：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {},
  "trace_id": "..."
}
```

字段使用 `msg`，不是 `message`。

错误响应保持相同结构：

```json
{
  "code": 40402,
  "msg": "job not found",
  "data": null,
  "trace_id": "..."
}
```

## Public v1 Files

- `POST /api/v1/files/upload`
- `GET /api/v1/files/{file_id}`

上传接口接收 multipart NetCDF 文件，返回 `file_id`、原始文件名、保存路径、文件大小和创建时间。

## Public v1 Jobs

- `POST /api/v1/jobs/diagnose`
- `GET /api/v1/jobs/{job_id}`

`POST /api/v1/jobs/diagnose` 支持上传文件 ID：

```json
{
  "model": "ecmwf",
  "file_id": "uploaded-file-id",
  "run_id": "ecmwf_demo"
}
```

也支持服务端已有文件路径：

```json
{
  "model": "ecmwf",
  "file_path": "data/raw/ecmwf_demo.nc",
  "run_id": "ecmwf_demo"
}
```

当前版本同步执行诊断，但对外仍返回 `job_id`、`status`、`run_id` 和产物索引，便于后续平滑迁移到异步任务。

## Public v1 Runs

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/forecast-hours`
- `GET /api/v1/runs/{run_id}/variables`

## Public v1 NAFP Situation Diagnosis

- `POST /api/v1/diagnosis/nafp/situation`
- `POST /api/v1/diagnosis/nafp/situations`

Request:

```json
{
  "data_code": "NAFP_ECTHIN_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24
}
```

`data_code` comes from backend data-source configuration. The current default
is `NAFP_ECTHIN_NC`; future datasets such as `NAFP_GFS_NC` can be added in
the backend config without changing the admin UI. `root` is still accepted as a
compatibility/debug field, but clients should prefer `data_code`.

Responses strip local data paths such as `root`, `source_path`,
`source_paths`, `stored_path`, and `file_path`; use stable business identifiers
such as `data_code`, `source_grid`, `run_time`, and `forecast_hour` instead.

The response `data` contains `run_time`, `forecast_hour`, `valid_time`,
`domain`, `systems`, `diagnostics`, `evidence_chains`,
`risk_diagnoses`, `diagnosis_conclusions`, `missing_fields`, and `summary`.
This endpoint is backend-focused and does not return visualization tiles or
frontend-specific payloads.

`risk_diagnoses` is the canonical multi-hazard risk conclusion list. A risk item
contains at least `hazard_type`, `label`, `risk_domain`, `risk_level`, `score`,
`source_grid`, and `source_chain_ids`; area results may also include `region`,
`dominant_evidence`, `mechanism_tags`, and `supporting_systems`. The legacy
`evidence_chains` and `diagnosis_conclusions` arrays are retained for existing
clients and forecaster-facing narrative summaries.

`diagnosis_conclusions` is a forecaster-oriented conclusion layer. Each item has
`headline`, `reasoning`, and `action_hint`, generated from dominant physical
evidence and linked weather systems.

Each evidence chain may include `linked_systems`, a ranked list of spatially
overlapping or nearby weather systems that support the diagnosis. Each link
contains `system_id`, `type`, `name`, `relation`, `distance_degrees`,
`relevance`, and a concise `reason`.

`systems` may include `subtropical_high`, `low_pressure_convergence`,
`high_pressure_divergence`, `trough_candidate`, `ridge_candidate`, and
`front_candidate`. Evidence items include threshold matrix audit fields such as
`entry_id`, `statistic`, `operator`, `threshold`, and `raw_value`.

Weather-system geometry may be `bbox`, `polygon`, or `line`. The `line` type is
used for 500hPa trough/ridge axis candidates and includes `coordinates` plus a
derived `bbox`.

Batch Request:

```json
{
  "data_code": "NAFP_ECTHIN_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hours": [0, 3, 6, 9, 12, 24]
}
```

`situations` runs the same NAFP situation diagnosis for multiple forecast hours
in one request. The response contains `result_count`, `failed_count`,
`situation_evolution`, `subtropical_high_trend`, `results`, and `failed`; one
missing forecast-hour file does not fail the whole batch.

`subtropical_high_trend` summarizes the subtropical-high evolution across
successful forecast hours. It compares the first and last complete subtropical
high samples by western ridge-point longitude, northern boundary latitude, area,
and mean height. When fewer than two complete samples are available,
`available=false` and `trend_summary` explains that the sample is insufficient.

```json
{
  "system_type": "subtropical_high",
  "available": true,
  "baseline_forecast_hour": 0,
  "target_forecast_hour": 24,
  "west_extension": {"direction": "westward", "label": "西伸", "delta_lon": -9.0},
  "north_shift": {"direction": "southward", "label": "南落", "delta_lat": -0.75},
  "area_change": {"direction": "shrinking", "label": "缩小", "delta_grid_points": -1991, "delta_percent": -9.96},
  "intensity_change": {"direction": "weakening", "label": "减弱", "delta_mean_height": -0.529},
  "trend_summary": "副高从 +0h 到 +24h 西伸、南落，面积缩小，强度减弱。"
}
```

`situation_evolution` is the batch-level weather-situation evolution panel. It
keeps `subtropical_high_trend` as the first item, then adds line-system trends
for `trough_candidate`, `ridge_candidate`, `low_level_jet`, and
`moisture_transport`. Line-system items compare the first and last complete
samples by primary line-object count, mean line center, mean axis length, and
mean confidence.

```json
{
  "available": true,
  "baseline_forecast_hour": 0,
  "target_forecast_hour": 24,
  "trend_summary": "天气形势演变：副高从 +0h 到 +24h 西伸、南落，面积缩小，强度减弱；槽线从 +0h 到 +24h 西移、南落，对象持平，轴线长度少变，平均置信度少变。",
  "items": [
    {"system_type": "subtropical_high", "label": "副高", "geometry_role": "polygon"},
    {
      "system_type": "low_level_jet",
      "label": "低空急流",
      "geometry_role": "line",
      "position_change": {
        "east_west": {"direction": "westward", "label": "西移", "delta_lon": -2.205},
        "north_south": {"direction": "southward", "label": "南落", "delta_lat": -1.696}
      },
      "count_change": {"direction": "stable", "label": "持平", "delta_count": 0},
      "length_change": {"direction": "shortening", "label": "缩短", "delta_degrees": -5.268},
      "confidence_change": {"direction": "weakening", "label": "减弱", "delta_confidence": -0.06}
    }
  ]
}
```

## Public v1 NAFP Point Diagnosis

- `POST /api/v1/diagnosis/nafp/point`

Request:

```json
{
  "data_code": "NAFP_ECTHIN_NC",
  "run_time": "2026-06-17T20:00:00",
  "forecast_hour": 24,
  "lat": 30.21,
  "lon": 120.63
}
```

The point endpoint uses the same threshold matrix and evidence entry IDs as the
situation diagnosis. It samples the nearest model grid point for the requested
latitude and longitude, then returns point-level `scores`,
`risk_diagnoses`, `evidence_chains`, and `diagnosis_conclusions`.

Point-level `risk_diagnoses` uses the same canonical multi-hazard item contract:
each item contains at least `hazard_type`, `label`, `risk_domain`,
`risk_level`, `score`, `source_grid`, and `source_chain_ids`. Legacy
`evidence_chains` and `diagnosis_conclusions` remain available alongside the
canonical risk list.

The response `data.point` contains the requested coordinate, sampling method,
nearest grid latitude/longitude, grid indices, distance in degrees, and whether
the requested point is outside the model domain. Each evidence item uses
`statistic=point` and keeps the original threshold rule statistic in
`rule_statistic`, so clients can distinguish point sampling from whole-domain
percentile scoring while preserving threshold audit fields.

## Public v1 Sounding Situation Diagnosis

- `GET /api/v1/sounding/situation?csv_path=...&pressure_level=500`
- `GET /api/v1/sounding/features?csv_path=...&pressure_level=500&types=trough,short_duration_heavy_rain_risk`

Sounding uses observation time and pressure level, not model `run_time` or
`forecast_hour`. The first implementation reads the regional sounding CSV test
format, builds a 1-degree objective analysis field for 500hPa height,
temperature and wind, then returns map-ready weather-system objects and station
wind point features.

The response `data` contains `data_type=sounding`, `observation_time`,
`analysis_level`, `domain`, `analysis_fields`, `systems`, `station_features`,
`station_diagnostics`, and `summary`. `analysis_fields` exposes metadata such as
unit, min/max and quality; large grid arrays are intentionally not included in
this response.

`station_diagnostics` is computed with MetPy from each station profile. The
first set of indices includes `cape_j_kg`, `cin_j_kg`, `lcl_pressure_hpa`,
`lcl_temperature_c`, and `precipitable_water_mm`, plus a per-station quality
flag and level count. `station_risk_diagnoses` converts these indices into
station-level environment evidence for short-duration heavy rain, rotating storm
or supercell potential, and severe-convection composite risk. These are
`score_source=sounding_profile_indices` station diagnoses, not gridded
`source_grid` risk areas; missing trigger, rainrate, shear and SRH factors are
reported in `missing_critical_factors` and cap the score.

Sounding weather systems currently include `height_high`, `height_low`,
`warm_center`, `cold_center`, `trough_candidate`, and `ridge_candidate`. Each
system includes `feature_type`, `confidence`, `geometry`, and `evidence`, so it
can be compared visually with Central Meteorological Observatory analysis charts
in the map UI.

`sounding/features` returns GeoJSON for the map. It converts sounding systems to
the existing map object types (`height_high` -> `high`, `height_low` -> `low`,
`trough_candidate` -> `trough`, `ridge_candidate` -> `ridge`) and converts
station-level risk diagnoses to point features using the corresponding
multi-hazard risk `feature_type`.

## Public v1 Admin Algorithms

- `GET /api/v1/admin/data-sources`
- `GET /api/v1/admin/algorithms/catalog`
- `GET /api/v1/admin/algorithms/threshold-matrix`
- `PUT /api/v1/admin/algorithms/threshold-matrix`
- `GET /api/v1/admin/algorithms/rule-explanations`

`admin/data-sources` returns the configured NAFP data-code list and default
code:

```json
{
  "default_code": "NAFP_ECTHIN_NC",
  "items": [
    {
      "code": "NAFP_ECTHIN_NC",
      "name": "NAFP_ECTHIN_NC",
      "model": "EC",
      "format": "nc",
      "forecast_hour_range": {"start": 0, "end": 240, "step": 3},
      "forecast_hours": [0, 3, 6, 9],
      "enabled": true,
      "default": true
    }
  ]
}
```

`rule-explanations` returns the structured diagnostic basis used by the admin
backend. Each section includes `rule_id`, `title`, `category`, `basis`,
`inputs`, `method`, `threshold_entries`, `threshold_details`, `outputs`, and
`evidence_contract`, so the UI can explain each weather-system or evidence-chain
diagnosis with the same threshold IDs used by the running algorithm.

## Public v1 Error Codes

- `40001`: invalid request
- `40002`: unsupported model
- `40003`: missing file reference
- `40004`: invalid NAFP root
- `40007`: invalid sounding request
- `40401`: run not found
- `40402`: job not found
- `40403`: file not found
- `40404`: required NAFP product not found
- `40407`: sounding file not found
- `50001`: diagnosis failed
- `50002`: NAFP diagnosis failed

## 基础

- `GET /api/health`
- `GET /api/models`
- `GET /api/model-runs`
- `GET /api/forecast-times?run_id=ecmwf_demo`
- `GET /api/variables?run_id=ecmwf_demo`

## 任务

- `POST /api/jobs/generate-demo`
- `POST /api/jobs/diagnose?model=ecmwf&file_path=data/raw/ecmwf_demo.nc&run_id=ecmwf_demo`
- `GET /api/inspect?path=data/raw/ecmwf_demo.nc`

## 图层

- `GET /api/layers`
- `GET /api/layers/{layer_id}/metadata?run_id=...&forecast_hour=24`
- `GET /api/layers/{layer_id}/grid?run_id=...&forecast_hour=24`
- `GET /api/layers/{layer_id}/contours?run_id=...&forecast_hour=24`
- `GET /api/layers/{layer_id}/image?run_id=...&forecast_hour=24`（兼容旧图片渲染，不作为前端主路径）

`contours` 返回从诊断格点生成的 GeoJSON 线要素，可用于等压线、等高线和等温线。
默认间隔配置在 `configs/layers.yaml`，调用方也可以传
`levels=1000,1004` 或 `interval=2` 覆盖。

## 天气系统

- `GET /api/features?run_id=...&forecast_hour=24`
- `GET /api/features?run_id=...&forecast_hour=24&type=low_level_jet`
- `GET /api/features/{feature_id}?run_id=...&forecast_hour=24`

## 分析

- `GET /api/analysis/situation?run_id=...&forecast_hour=24`
- `GET /api/analysis/heavy-rain?run_id=...&forecast_hour=24`
- `GET /api/analysis/convection?run_id=...&forecast_hour=24`
