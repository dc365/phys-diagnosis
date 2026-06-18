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

## Public v1 Error Codes

- `40001`: invalid request
- `40002`: unsupported model
- `40003`: missing file reference
- `40004`: invalid NAFP root
- `40401`: run not found
- `40402`: job not found
- `40403`: file not found
- `40404`: required NAFP product not found
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
- `GET /api/layers/{layer_id}/image?run_id=...&forecast_hour=24`（兼容旧图片渲染，不作为前端主路径）

## 天气系统

- `GET /api/features?run_id=...&forecast_hour=24`
- `GET /api/features?run_id=...&forecast_hour=24&type=low_level_jet`
- `GET /api/features/{feature_id}?run_id=...&forecast_hour=24`

## 分析

- `GET /api/analysis/situation?run_id=...&forecast_hour=24`
- `GET /api/analysis/heavy-rain?run_id=...&forecast_hour=24`
- `GET /api/analysis/convection?run_id=...&forecast_hour=24`
