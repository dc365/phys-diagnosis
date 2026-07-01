from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.admin import router as public_admin_router
from backend.app.api.v1.auto_diagnostics import router as public_auto_diagnostics_router
from backend.app.api.v1.data_sources import router as public_data_sources_router
from backend.app.api.v1.diagnosis import router as public_diagnosis_router
from backend.app.api.v1.files import router as public_files_router
from backend.app.api.v1.jobs import router as public_jobs_router
from backend.app.api.v1.precompute import router as public_precompute_router
from backend.app.api.v1.runs import router as public_runs_router
from backend.app.api.v1.sounding import router as public_sounding_router
from backend.app.api.v1.sounding_preprocess import router as public_sounding_preprocess_router
from backend.app.responses import ApiError, api_error_handler, strip_private_paths, validation_error_handler
from weather_diag.config import DATA_DIR, RAW_DIR, PRODUCTS_DIR, ensure_dirs, load_layers, load_yaml
from weather_diag.data.synthetic import create_demo_ecmwf_netcdf
from weather_diag.data.reader import inspect_netcdf
from weather_diag.diagnosis.auto_scheduler import start_auto_diagnosis_scheduler
from weather_diag.pipeline import diagnose_file, load_run_index, load_diagnostics, load_features, load_analysis
from weather_diag.io.contours import contours_to_geojson
from weather_diag.io.grid_geojson import grid_to_geojson
from weather_diag.io.render import render_png

ensure_dirs()
app = FastAPI(title="天气形势分析与物理量诊断工作台", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(public_admin_router, prefix="/api/v1")
app.include_router(public_auto_diagnostics_router, prefix="/api/v1")
app.include_router(public_data_sources_router, prefix="/api/v1")
# Register precompute routes before the legacy diagnosis router so POST
# /api/v1/diagnosis/nafp/precompute schedules async work instead of blocking the
# request thread with a full synchronous calculation.
app.include_router(public_precompute_router, prefix="/api/v1")
app.include_router(public_diagnosis_router, prefix="/api/v1")
app.include_router(public_files_router, prefix="/api/v1")
app.include_router(public_jobs_router, prefix="/api/v1")
app.include_router(public_runs_router, prefix="/api/v1")
app.include_router(public_sounding_router, prefix="/api/v1")
app.include_router(public_sounding_preprocess_router, prefix="/api/v1")


@app.on_event("startup")
def start_auto_diagnostics() -> None:
    start_auto_diagnosis_scheduler()


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def layer_image_title(layer_id: str, cfg: dict) -> str:
    title = str(cfg.get("title") or "")
    if title and title.isascii():
        return title
    return str(cfg.get("variable") or layer_id)


def _admin_index_html() -> HTMLResponse | FileResponse:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "admin view not found")
    html = index_path.read_text(encoding="utf-8")
    scripts = [
        '<script src="/static/precompute-admin-extension.js?v=auto-diagnosis-20260629"></script>',
        '<script src="/static/sounding-preprocess-admin-extension.js?v=auto-diagnosis-20260629"></script>',
    ]
    marker = '<script src="/static/app.js?v=auto-diagnosis-20260629"></script>'
    for script in scripts:
        if script in html:
            continue
        if marker in html:
            html = html.replace(marker, f"{marker}\n  {script}")
        else:
            html = html.replace("</body>", f"  {script}\n</body>")
    return HTMLResponse(html)


def map_public_config() -> dict:
    raw = (load_yaml("map.yaml").get("map") or {})
    config = {
        "basemap": raw.get("basemap") or "tdt-vector",
        "tiandituToken": raw.get("tianditu_token") or raw.get("tiandituToken") or "607ace490b937459cac5709cc3aef752",
    }
    local_tile_template = raw.get("local_tile_template") or raw.get("localTileTemplate")
    if local_tile_template:
        config["localTileTemplate"] = str(local_tile_template)
    return config


def _map_config_script() -> str:
    payload = json.dumps(map_public_config(), ensure_ascii=False, indent=6)
    return f'<script id="weatherMapConfig">\n    window.WEATHER_MAP_CONFIG = {payload};\n  </script>'


@app.get("/")
def index():
    if FRONTEND_DIR.exists():
        return _admin_index_html()
    return {"message": "Weather Diagnosis MVP API"}


@app.get("/map")
def map_view():
    map_path = FRONTEND_DIR / "map.html"
    if map_path.exists():
        html = map_path.read_text(encoding="utf-8")
        start = html.find('<script id="weatherMapConfig">')
        end = html.find("</script>", start)
        if start >= 0 and end >= 0:
            html = html[:start] + _map_config_script() + html[end + len("</script>"):]
        return HTMLResponse(html)
    raise HTTPException(404, "map view not found")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
    create_demo_ecmwf_netcdf(RAW_DIR / "ecmwf_demo.nc")
    return {"status": "ok", "hint": "Now call /api/jobs/diagnose with run_id=ecmwf_demo"}


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
        return strip_private_paths(result)
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
    return strip_private_paths(inspect_netcdf(p))


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


def parse_contour_levels(value: Optional[str]) -> list[float] | None:
    if not value:
        return None
    levels: list[float] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            levels.append(float(item))
    return levels or None


@app.get("/api/layers/{layer_id}/contours")
def layer_contours(
    layer_id: str,
    run_id: str,
    forecast_hour: int,
    levels: Optional[str] = Query(default=None),
    interval: Optional[float] = Query(default=None),
):
    ds = load_diagnostics(run_id, forecast_hour)
    layers_cfg = load_layers()
    cfg = layers_cfg.get(layer_id, {})
    var = cfg.get("variable", layer_id)
    if var not in ds.data_vars:
        raise HTTPException(404, f"Layer variable not found: {var}")
    contour_cfg = cfg.get("contour") or {}
    unit = ds[var].attrs.get("units", cfg.get("unit", ""))
    return contours_to_geojson(
        layer_id,
        cfg.get("title", var),
        unit,
        ds[var].values,
        lat=ds.lat.values,
        lon=ds.lon.values,
        levels=parse_contour_levels(levels) or contour_cfg.get("levels"),
        interval=interval or contour_cfg.get("interval"),
        max_segments=int(contour_cfg.get("max_segments", 12000)),
    )


@app.get("/api/features")
def features(run_id: str, forecast_hour: int, type: Optional[str] = Query(default=None)):
    fc = load_features(run_id, forecast_hour)
    if type:
        fc["features"] = [f for f in fc.get("features", []) if f.get("properties", {}).get("feature_type") == type]
    return strip_private_paths(fc)


@app.get("/api/features/{feature_id}")
def feature_detail(feature_id: str, run_id: str, forecast_hour: int):
    fc = load_features(run_id, forecast_hour)
    for f in fc.get("features", []):
        if f.get("properties", {}).get("id") == feature_id:
            return strip_private_paths(f)
    raise HTTPException(404, f"feature not found: {feature_id}")


@app.get("/api/analysis/situation")
def situation(run_id: str, forecast_hour: int, region: str = "default"):
    return strip_private_paths(load_analysis(run_id, forecast_hour))


@app.get("/api/analysis/heavy-rain")
def heavy_rain(run_id: str, forecast_hour: int):
    analysis = load_analysis(run_id, forecast_hour)
    counts = analysis.get("feature_counts", {})
    return {
        "summary": analysis.get("summary"),
        "precipitation_risk_count": counts.get("persistent_heavy_rain_risk", 0) + counts.get("short_duration_heavy_rain_risk", 0),
        "detail": strip_private_paths(analysis.get("detail")),
        "disclaimer": analysis.get("disclaimer"),
    }


@app.get("/api/analysis/convection")
def convection(run_id: str, forecast_hour: int):
    analysis = load_analysis(run_id, forecast_hour)
    counts = analysis.get("feature_counts", {})
    return {
        "summary": analysis.get("summary"),
        "severe_convection_risk_count": (
            counts.get("short_duration_heavy_rain_risk", 0)
            + counts.get("thunderstorm_gale_risk", 0)
            + counts.get("hail_risk", 0)
            + counts.get("rotating_storm_risk", 0)
            + counts.get("severe_convection_composite_risk", 0)
        ),
        "detail": strip_private_paths(analysis.get("detail")),
        "disclaimer": analysis.get("disclaimer"),
    }
