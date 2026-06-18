from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.diagnosis import router as public_diagnosis_router
from backend.app.api.v1.files import router as public_files_router
from backend.app.api.v1.jobs import router as public_jobs_router
from backend.app.api.v1.runs import router as public_runs_router
from backend.app.responses import ApiError, api_error_handler, validation_error_handler
from weather_diag.config import DATA_DIR, RAW_DIR, PRODUCTS_DIR, ensure_dirs, load_layers
from weather_diag.data.synthetic import create_demo_ecmwf_netcdf
from weather_diag.data.reader import inspect_netcdf
from weather_diag.pipeline import diagnose_file, load_run_index, load_diagnostics, load_features, load_analysis
from weather_diag.io.grid_geojson import grid_to_geojson
from weather_diag.io.render import render_png

ensure_dirs()
app = FastAPI(title="天气形势智能诊断与物理量分析系统 MVP", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(public_diagnosis_router, prefix="/api/v1")
app.include_router(public_files_router, prefix="/api/v1")
app.include_router(public_jobs_router, prefix="/api/v1")
app.include_router(public_runs_router, prefix="/api/v1")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def layer_image_title(layer_id: str, cfg: dict) -> str:
    title = str(cfg.get("title") or "")
    if title and title.isascii():
        return title
    return str(cfg.get("variable") or layer_id)


@app.get("/")
def index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Weather Diagnosis MVP API"}


@app.get("/map")
def map_view():
    map_path = FRONTEND_DIR / "map.html"
    if map_path.exists():
        return FileResponse(map_path)
    raise HTTPException(404, "map view not found")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/api/health")
def health():
    return {"status": "ok", "data_dir": str(DATA_DIR)}


@app.get("/api/models")
def models():
    return [{"id": "ecmwf", "name": "ECMWF / EC 模式"}]


@app.get("/api/model-runs")
def model_runs():
    runs = []
    if PRODUCTS_DIR.exists():
        for p in sorted(PRODUCTS_DIR.iterdir()):
            idx = p / "index.json"
            if idx.exists():
                try:
                    data = json.loads(idx.read_text(encoding="utf-8"))
                    runs.append({"run_id": data.get("run_id", p.name), "model": data.get("model"), "forecast_hours": data.get("forecast_hours", [])})
                except Exception:
                    pass
    return runs


@app.get("/api/forecast-times")
def forecast_times(run_id: str):
    idx = load_run_index(run_id)
    return idx.get("forecast_hours", [])


@app.get("/api/variables")
def variables(run_id: str):
    idx = load_run_index(run_id)
    return idx.get("variable_map", {})


@app.get("/api/layers")
def layers():
    return load_layers()


@app.post("/api/jobs/generate-demo")
def generate_demo():
    path = create_demo_ecmwf_netcdf(RAW_DIR / "ecmwf_demo.nc")
    return {"status": "ok", "file_path": str(path), "hint": "Now call /api/jobs/diagnose with run_id=ecmwf_demo"}


@app.post("/api/jobs/diagnose")
def diagnose(model: str = "ecmwf", file_path: str = "data/raw/ecmwf_demo.nc", run_id: Optional[str] = None):
    p = Path(file_path)
    if not p.is_absolute():
        # Resolve relative to project root first, then current working directory.
        project_root = Path(__file__).resolve().parents[2]
        if (project_root / p).exists():
            p = project_root / p
    if not p.exists():
        raise HTTPException(404, f"NetCDF file not found: {file_path}")
    try:
        result = diagnose_file(p, model=model, run_id=run_id)
        return result
    except Exception as e:
        raise HTTPException(500, f"diagnose failed: {e}")


@app.get("/api/inspect")
def inspect(path: str):
    p = Path(path)
    if not p.is_absolute():
        project_root = Path(__file__).resolve().parents[2]
        if (project_root / p).exists():
            p = project_root / p
    if not p.exists():
        raise HTTPException(404, f"file not found: {path}")
    return inspect_netcdf(p)


@app.get("/api/layers/{layer_id}/metadata")
def layer_metadata(layer_id: str, run_id: str, forecast_hour: int):
    ds = load_diagnostics(run_id, forecast_hour)
    layers_cfg = load_layers()
    var = layers_cfg.get(layer_id, {}).get("variable", layer_id)
    if var not in ds.data_vars:
        raise HTTPException(404, f"Layer variable not found: {var}")
    arr = ds[var].values
    import numpy as np
    valid = arr[np.isfinite(arr)]
    return {
        "layer_id": layer_id,
        "variable": var,
        "title": layers_cfg.get(layer_id, {}).get("title", var),
        "unit": ds[var].attrs.get("units", layers_cfg.get(layer_id, {}).get("unit", "")),
        "lat_min": float(ds.lat.min()), "lat_max": float(ds.lat.max()),
        "lon_min": float(ds.lon.min()), "lon_max": float(ds.lon.max()),
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
    }


@app.get("/api/layers/{layer_id}/image")
def layer_image(layer_id: str, run_id: str, forecast_hour: int):
    ds = load_diagnostics(run_id, forecast_hour)
    layers_cfg = load_layers()
    cfg = layers_cfg.get(layer_id, {})
    var = cfg.get("variable", layer_id)
    if var not in ds.data_vars:
        raise HTTPException(404, f"Layer variable not found: {var}")
    cmap = "viridis"
    if "risk" in layer_id or "score" in layer_id:
        cmap = "YlOrRd"
    elif "div" in layer_id or "adv" in layer_id or "vort" in layer_id or "omega" in layer_id:
        cmap = "RdBu_r"
    elif "moisture" in layer_id:
        cmap = "YlGnBu"
    png = render_png(ds[var].values, ds.lat.values, ds.lon.values, title=layer_image_title(layer_id, cfg), unit=ds[var].attrs.get("units", ""), cmap=cmap)
    return Response(content=png, media_type="image/png")


@app.get("/api/layers/{layer_id}/grid")
def layer_grid(layer_id: str, run_id: str, forecast_hour: int):
    ds = load_diagnostics(run_id, forecast_hour)
    layers_cfg = load_layers()
    cfg = layers_cfg.get(layer_id, {})
    var = cfg.get("variable", layer_id)
    if var not in ds.data_vars:
        raise HTTPException(404, f"Layer variable not found: {var}")
    unit = ds[var].attrs.get("units", cfg.get("unit", ""))
    return grid_to_geojson(
        layer_id,
        cfg.get("title", var),
        unit,
        ds[var].values,
        lat=ds.lat.values,
        lon=ds.lon.values,
    )


@app.get("/api/features")
def features(run_id: str, forecast_hour: int, type: Optional[str] = Query(default=None)):
    fc = load_features(run_id, forecast_hour)
    if type:
        fc["features"] = [f for f in fc.get("features", []) if f.get("properties", {}).get("feature_type") == type]
    return fc


@app.get("/api/features/{feature_id}")
def feature_detail(feature_id: str, run_id: str, forecast_hour: int):
    fc = load_features(run_id, forecast_hour)
    for f in fc.get("features", []):
        if f.get("properties", {}).get("id") == feature_id:
            return f
    raise HTTPException(404, f"feature not found: {feature_id}")


@app.get("/api/analysis/situation")
def situation(run_id: str, forecast_hour: int, region: str = "default"):
    return load_analysis(run_id, forecast_hour)


@app.get("/api/analysis/heavy-rain")
def heavy_rain(run_id: str, forecast_hour: int):
    analysis = load_analysis(run_id, forecast_hour)
    return {
        "summary": analysis.get("summary"),
        "heavy_rain_risk_count": analysis.get("feature_counts", {}).get("heavy_rain_risk", 0),
        "detail": analysis.get("detail"),
        "disclaimer": analysis.get("disclaimer"),
    }


@app.get("/api/analysis/convection")
def convection(run_id: str, forecast_hour: int):
    analysis = load_analysis(run_id, forecast_hour)
    return {
        "summary": analysis.get("summary"),
        "convection_risk_count": analysis.get("feature_counts", {}).get("convection_risk", 0),
        "detail": analysis.get("detail"),
        "disclaimer": analysis.get("disclaimer"),
    }
