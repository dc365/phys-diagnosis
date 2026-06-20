from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from weather_diag.config import load_layers, load_thresholds
from weather_diag.data.nafp import NafpField, load_nafp_field, parse_run_time
from weather_diag.diagnostics.moisture import moisture_convergence, moisture_flux
from weather_diag.diagnostics.vorticity import relative_vorticity
from weather_diag.diagnostics.wind import wind_speed
from weather_diag.features.risk import convection_score_details, heavy_rain_score_details, multi_hazard_score_details


ValueTransform = Callable[[np.ndarray], np.ndarray]


def _resolve_root(data_code: str | None, root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    from backend.app.services.data_sources import resolve_data_root

    return resolve_data_root(data_code)


def _finite_range(values: np.ndarray) -> tuple[float | None, float | None]:
    valid = np.asarray(values, dtype=float)[np.isfinite(values)]
    if valid.size == 0:
        return None, None
    return float(valid.min()), float(valid.max())


def _field(
    root: Path,
    element: str,
    level: str,
    run_time: str,
    forecast_hour: int,
    *,
    required: bool = True,
) -> NafpField:
    return load_nafp_field(root, element, level, run_time, forecast_hour, required=required)


def _array(field: NafpField, preferred: str | None = None) -> np.ndarray | None:
    if not field.exists:
        return None
    if preferred and preferred in field.values:
        return field.values[preferred]
    if len(field.values) == 1:
        return next(iter(field.values.values()))
    return None


def _scaled_gh(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if np.nanmedian(arr) < 1000:
        return arr * 10.0
    return arr


DIRECT_LAYERS: dict[str, tuple[str, str, str, ValueTransform | None]] = {
    "z500": ("gh", "500", "gh", _scaled_gh),
    "mslp": ("seap", "999", "seap", None),
    "t850": ("tt", "850", "tt", None),
    "div850": ("div", "850", "div", None),
    "omega700": ("w", "700", "w", None),
    "temp_adv850": ("ttadv", "850", "ttadv", None),
    "k_index": ("kindex", "999", "kindex", None),
    "shear_0_6km": ("shr6km", "999", "shr6km", None),
}


MULTI_HAZARD_RISK_SCORE_LAYERS = {
    "risk_persistent_heavy_rain_score",
    "risk_short_duration_heavy_rain_score",
    "risk_thunderstorm_gale_score",
    "risk_hail_score",
    "risk_rotating_storm_score",
    "risk_severe_convection_composite_score",
    "risk_precipitation_composite_score",
}


def _direct_layer(
    root: Path,
    layer_id: str,
    run_time: str,
    forecast_hour: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    element, level, variable, transform = DIRECT_LAYERS[layer_id]
    field = _field(root, element, level, run_time, forecast_hour)
    values = _array(field, variable)
    if values is None:
        raise FileNotFoundError(field.source_path)
    if transform:
        values = transform(values)
    return np.asarray(values, dtype=float), field.lat, field.lon, [field.source_path]


def _wind850_speed(root: Path, _layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    field = _field(root, "uv", "850", run_time, forecast_hour)
    if "u" not in field.values or "v" not in field.values:
        raise FileNotFoundError(field.source_path)
    return wind_speed(field.values["u"], field.values["v"]), field.lat, field.lon, [field.source_path]


def _vort500(root: Path, _layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    field = _field(root, "uv", "500", run_time, forecast_hour)
    if "u" not in field.values or "v" not in field.values:
        raise FileNotFoundError(field.source_path)
    values = relative_vorticity(field.values["u"], field.values["v"], field.lat, field.lon) * 100000.0
    return values, field.lat, field.lon, [field.source_path]


def _moisture_fields(root: Path, run_time: str, forecast_hour: int) -> tuple[NafpField, NafpField, np.ndarray, np.ndarray, np.ndarray]:
    uv850 = _field(root, "uv", "850", run_time, forecast_hour)
    q850 = _field(root, "q", "850", run_time, forecast_hour)
    if "u" not in uv850.values or "v" not in uv850.values or "q" not in q850.values:
        raise FileNotFoundError(f"{uv850.source_path}; {q850.source_path}")
    return uv850, q850, uv850.values["u"], uv850.values["v"], q850.values["q"]


def _moisture_flux850(root: Path, _layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    uv850, q850, u850, v850, q = _moisture_fields(root, run_time, forecast_hour)
    _, _, values = moisture_flux(u850, v850, q)
    return values, q850.lat, q850.lon, [uv850.source_path, q850.source_path]


def _moisture_conv850(root: Path, _layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    uv850, q850, u850, v850, q = _moisture_fields(root, run_time, forecast_hour)
    fu, fv, _ = moisture_flux(u850, v850, q)
    values = moisture_convergence(fu, fv, q850.lat, q850.lon)
    return values, q850.lat, q850.lon, [uv850.source_path, q850.source_path]


def _optional_array(
    root: Path,
    element: str,
    level: str,
    variable: str,
    run_time: str,
    forecast_hour: int,
) -> tuple[np.ndarray | None, str]:
    field = _field(root, element, level, run_time, forecast_hour, required=False)
    return _array(field, variable), field.source_path


def _first_optional_array(
    root: Path,
    candidates: list[tuple[str, str, str]],
    run_time: str,
    forecast_hour: int,
) -> tuple[np.ndarray | None, str]:
    fallback_path = ""
    for element, level, variable in candidates:
        values, path = _optional_array(root, element, level, variable, run_time, forecast_hour)
        if not fallback_path:
            fallback_path = path
        if values is not None:
            return values, path
    return None, fallback_path


def _risk_scores(root: Path, layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    thresholds = load_thresholds()
    uv850, q850, u850, v850, q = _moisture_fields(root, run_time, forecast_hour)
    fu, fv, mflux = moisture_flux(u850, v850, q)
    mconv = moisture_convergence(fu, fv, q850.lat, q850.lon)
    div850, div850_path = _optional_array(root, "div", "850", "div", run_time, forecast_hour)
    omega700, omega700_path = _optional_array(root, "w", "700", "w", run_time, forecast_hour)
    kindex, kindex_path = _optional_array(root, "kindex", "999", "kindex", run_time, forecast_hour)
    cape, cape_path = _optional_array(root, "cape", "999", "cape", run_time, forecast_hour)
    rain6, rain6_path = _optional_array(root, "rain6", "999", "rain6", run_time, forecast_hour)
    cin, cin_path = _optional_array(root, "cin", "999", "cin", run_time, forecast_hour)
    shear, shear_path = _optional_array(root, "shr6km", "999", "shr6km", run_time, forecast_hour)
    dcape, dcape_path = _optional_array(root, "dcape", "999", "dcape", run_time, forecast_hour)
    li, li_path = _optional_array(root, "li", "999", "li", run_time, forecast_hour)
    srh, srh_path = _optional_array(root, "srh", "999", "srh", run_time, forecast_hour)
    shear01, shear01_path = _first_optional_array(
        root,
        [("shr0-1", "999", "shr0-1"), ("shr1km", "999", "shr1km")],
        run_time,
        forecast_hour,
    )
    if layer_id == "heavy_rain_score":
        details = heavy_rain_score_details(
            {
                "moisture_flux": mflux,
                "moisture_convergence": mconv,
                "div850": div850,
                "omega700": omega700,
                "k_index": kindex,
                "cape": cape,
                "precipitation": rain6,
            },
            thresholds,
        )
        values = details["score"]
    elif layer_id == "convection_score":
        details = convection_score_details(
            {
                "cape": cape,
                "cin": cin,
                "k_index": kindex,
                "shear_0_6km": shear,
                "div850": div850,
                "moisture": q,
            },
            thresholds,
        )
        values = details["score"]
    else:
        details = multi_hazard_score_details(
            {
                "moisture_flux": mflux,
                "moisture_convergence": mconv,
                "div850": div850,
                "omega700": omega700,
                "k_index": kindex,
                "cape": cape,
                "cin": cin,
                "precipitation": rain6,
                "shear_0_6km": shear,
                "moisture": q,
                "dcape": dcape,
                "li": li,
                "srh": srh,
                "shear_0_1km": shear01,
            },
            thresholds,
        )
        values = details["scores"][layer_id]
    return values, q850.lat, q850.lon, [
        path
        for path in [
            uv850.source_path,
            q850.source_path,
            div850_path,
            omega700_path,
            kindex_path,
            cape_path,
            rain6_path,
            cin_path,
            shear_path,
            dcape_path,
            li_path,
            srh_path,
            shear01_path,
        ]
        if path
    ]


DERIVED_LAYERS = {
    "wind850_speed": _wind850_speed,
    "vort500": _vort500,
    "moisture_flux850": _moisture_flux850,
    "moisture_conv850": _moisture_conv850,
    "heavy_rain_score": _risk_scores,
    "convection_score": _risk_scores,
    **{layer_id: _risk_scores for layer_id in MULTI_HAZARD_RISK_SCORE_LAYERS},
}


def load_nafp_layer(
    layer_id: str,
    *,
    data_code: str | None = None,
    root: str | Path | None = None,
    run_time: str,
    forecast_hour: int,
) -> dict[str, Any]:
    layers = load_layers()
    cfg = layers.get(layer_id)
    if not cfg:
        raise KeyError(layer_id)
    data_root = _resolve_root(data_code, root)
    rt = parse_run_time(run_time).isoformat()
    if layer_id in DIRECT_LAYERS:
        values, lat, lon, source_paths = _direct_layer(data_root, layer_id, rt, forecast_hour)
    elif layer_id in DERIVED_LAYERS:
        values, lat, lon, source_paths = DERIVED_LAYERS[layer_id](data_root, layer_id, rt, forecast_hour)
    else:
        raise KeyError(layer_id)
    min_value, max_value = _finite_range(values)
    return {
        "layer_id": layer_id,
        "title": cfg.get("title", layer_id),
        "unit": cfg.get("unit", ""),
        "values": np.asarray(values, dtype=float),
        "lat": np.asarray(lat, dtype=float),
        "lon": np.asarray(lon, dtype=float),
        "min": min_value,
        "max": max_value,
        "data_code": data_code,
        "root": str(data_root),
        "run_time": rt,
        "forecast_hour": int(forecast_hour),
        "source_paths": source_paths,
        "contour": cfg.get("contour") or {},
    }


def layer_metadata(layer: dict[str, Any]) -> dict[str, Any]:
    lat = layer["lat"]
    lon = layer["lon"]
    return {
        "layer_id": layer["layer_id"],
        "title": layer["title"],
        "unit": layer["unit"],
        "data_code": layer["data_code"],
        "run_time": layer["run_time"],
        "forecast_hour": layer["forecast_hour"],
        "lat_min": float(np.nanmin(lat)),
        "lat_max": float(np.nanmax(lat)),
        "lon_min": float(np.nanmin(lon)),
        "lon_max": float(np.nanmax(lon)),
        "min": layer["min"],
        "max": layer["max"],
        "source_paths": layer["source_paths"],
    }
