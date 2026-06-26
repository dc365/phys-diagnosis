from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from weather_diag.config import load_layers, load_thresholds
from weather_diag.data.nafp import NafpField, load_nafp_field, parse_run_time
from weather_diag.diagnostics.moisture import moisture_convergence, moisture_flux
from weather_diag.diagnostics.vorticity import relative_vorticity
from weather_diag.diagnostics.wind import wind_speed
from weather_diag.features.risk import multi_hazard_score_details


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
    "z500": ("gh", "500", "gh", None),
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


def _add_source_path(source_paths: list[str], path: str | None) -> None:
    if path and path not in source_paths:
        source_paths.append(path)


def _add_risk_input(
    fields: dict[str, np.ndarray],
    source_paths: list[str],
    key: str,
    values: np.ndarray | None,
    source_path: str | None = None,
) -> None:
    if values is None:
        return
    fields[key] = np.asarray(values, dtype=float)
    _add_source_path(source_paths, source_path)


def _align_to_grid(
    values: np.ndarray,
    src_lat: np.ndarray,
    src_lon: np.ndarray,
    ref_lat: np.ndarray,
    ref_lon: np.ndarray,
) -> np.ndarray:
    arr = np.asarray(values, dtype=float).squeeze()
    src_lat_arr = np.asarray(src_lat, dtype=float)
    src_lon_arr = np.asarray(src_lon, dtype=float)
    ref_lat_arr = np.asarray(ref_lat, dtype=float)
    ref_lon_arr = np.asarray(ref_lon, dtype=float)
    if arr.shape == (ref_lat_arr.size, ref_lon_arr.size):
        return arr
    if arr.shape == (ref_lon_arr.size, ref_lat_arr.size):
        return arr.T
    if arr.shape == (src_lon_arr.size, src_lat_arr.size):
        arr = arr.T
    if arr.shape != (src_lat_arr.size, src_lon_arr.size):
        return arr
    lat_order = np.argsort(src_lat_arr)
    lon_order = np.argsort(src_lon_arr)
    sorted_lat = src_lat_arr[lat_order]
    sorted_lon = src_lon_arr[lon_order]
    sorted_values = arr[np.ix_(lat_order, lon_order)]
    lon_interp = np.vstack([np.interp(ref_lon_arr, sorted_lon, row) for row in sorted_values])
    return np.vstack([np.interp(ref_lat_arr, sorted_lat, lon_interp[:, idx]) for idx in range(ref_lon_arr.size)]).T


def _optional_existing_array(
    root: Path,
    element: str,
    level: str,
    variable: str,
    run_time: str,
    forecast_hour: int,
    *,
    ref_lat: np.ndarray | None = None,
    ref_lon: np.ndarray | None = None,
) -> tuple[np.ndarray | None, str]:
    field = _field(root, element, level, run_time, forecast_hour, required=False)
    values = _array(field, variable)
    if values is None:
        return None, ""
    arr = np.asarray(values, dtype=float)
    if ref_lat is not None and ref_lon is not None:
        arr = _align_to_grid(arr, field.lat, field.lon, ref_lat, ref_lon)
    return arr, field.source_path




def _precip_units_to_mm(values: np.ndarray, attrs: dict[str, Any] | None = None) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    units = ""
    if attrs:
        units = str(attrs.get("units") or attrs.get("Units") or attrs.get("unit") or "").lower().strip()
    # ECMWF tp is often meters. NAFP rain and kg m-2 products are usually already mm-equivalent.
    if "mm" in units or "millimeter" in units or "millimetre" in units:
        return arr
    if "kg" in units and "m" in units:
        return arr
    if units in {"m", "meter", "meters", "metre", "metres"}:
        return arr * 1000.0
    valid = np.abs(arr[np.isfinite(arr)])
    # Fallback for unitless EC-like total precipitation in meters; native NAFP interval rain is usually much larger than 2.
    if valid.size and float(np.nanmax(valid)) < 2.0:
        return arr * 1000.0
    return arr


def _align_field_values(field: NafpField, variable: str, ref_lat: np.ndarray, ref_lon: np.ndarray) -> np.ndarray | None:
    values = _array(field, variable)
    if values is None:
        return None
    return _align_to_grid(np.asarray(values, dtype=float), field.lat, field.lon, ref_lat, ref_lon)


def _precip_delta_or_current(
    current: np.ndarray,
    previous: np.ndarray | None,
    *,
    prefer_cumulative: bool,
) -> tuple[np.ndarray, str]:
    current_mm = np.asarray(current, dtype=float)
    if previous is None:
        return np.maximum(current_mm, 0.0), "single_interval_or_missing_previous"
    previous_mm = np.asarray(previous, dtype=float)
    delta = current_mm - previous_mm
    finite = np.isfinite(delta) & np.isfinite(current_mm) & np.isfinite(previous_mm)
    if not finite.any():
        return np.maximum(current_mm, 0.0), "current_interval_no_valid_delta"
    negative_fraction = float(np.count_nonzero(delta[finite] < -0.1) / np.count_nonzero(finite))
    positive_fraction = float(np.count_nonzero(delta[finite] >= -0.1) / np.count_nonzero(finite))
    # Known cumulative fields use the differenced amount unless the run clearly reset.
    if prefer_cumulative and negative_fraction <= 0.20:
        return np.maximum(delta, 0.0), "cumulative_difference"
    # For unknown fields, cumulative series usually have non-negative increments and current totals >= previous totals.
    if positive_fraction >= 0.92 and float(np.nanmean(current_mm[finite])) >= float(np.nanmean(previous_mm[finite])):
        return np.maximum(delta, 0.0), "auto_cumulative_difference"
    return np.maximum(current_mm, 0.0), "native_interval"


def _optional_precip_interval_array(
    root: Path,
    candidates: list[tuple[str, str, str, int]],
    run_time: str,
    forecast_hour: int,
    *,
    ref_lat: np.ndarray,
    ref_lon: np.ndarray,
) -> tuple[np.ndarray | None, list[str], dict[str, Any]]:
    """Load an interval precipitation field and protect EC cumulative totals.

    Each candidate is ``(element, level, variable, window_hours)``. Native products
    such as rain3/rain6/rain24 are used directly when no previous file is needed.
    Cumulative EC-like fields such as tp are converted to interval amounts by
    subtracting the previous forecast hour matching ``window_hours``.
    """
    for element, level, variable, window_hours in candidates:
        field = _field(root, element, level, run_time, forecast_hour, required=False)
        current_raw = _array(field, variable)
        if current_raw is None:
            continue
        current = _align_to_grid(_precip_units_to_mm(current_raw, field.attrs), field.lat, field.lon, ref_lat, ref_lon)
        element_key = element.lower()
        native_interval_elements = {
            "rain1", "rain3", "rain6", "rain12", "rain24", "rainmax1", "rainmax3", "rainmax6"
        }
        prefer_cumulative = element_key in {"tp", "total_precipitation", "precip"} or str(field.attrs.get("stepType", "")).lower() == "accum"
        previous = None
        previous_path = ""
        if element_key not in native_interval_elements and forecast_hour - int(window_hours) >= 0:
            prev_field = _field(root, element, level, run_time, forecast_hour - int(window_hours), required=False)
            prev_raw = _array(prev_field, variable)
            if prev_raw is not None:
                previous = _align_to_grid(_precip_units_to_mm(prev_raw, prev_field.attrs), prev_field.lat, prev_field.lon, ref_lat, ref_lon)
                previous_path = prev_field.source_path
        values, method = _precip_delta_or_current(current, previous, prefer_cumulative=prefer_cumulative)
        source_paths = [field.source_path] + ([previous_path] if previous_path else [])
        meta = {
            "element": element,
            "level": level,
            "variable": variable,
            "window_hours": int(window_hours),
            "method": method,
            "prefer_cumulative": prefer_cumulative,
            "current_forecast_hour": int(forecast_hour),
            "previous_forecast_hour": int(forecast_hour - int(window_hours)) if previous_path else None,
        }
        return values, source_paths, meta
    return None, [], {}


def _first_existing_array(
    root: Path,
    candidates: list[tuple[str, str, str]],
    run_time: str,
    forecast_hour: int,
    *,
    ref_lat: np.ndarray | None = None,
    ref_lon: np.ndarray | None = None,
) -> tuple[np.ndarray | None, str]:
    for element, level, variable in candidates:
        values, path = _optional_existing_array(
            root,
            element,
            level,
            variable,
            run_time,
            forecast_hour,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
        )
        if values is not None:
            return values, path
    return None, ""


def _optional_wind_speed(
    root: Path,
    element: str,
    level: str,
    run_time: str,
    forecast_hour: int,
    *,
    ref_lat: np.ndarray | None = None,
    ref_lon: np.ndarray | None = None,
) -> tuple[np.ndarray | None, str]:
    field = _field(root, element, level, run_time, forecast_hour, required=False)
    if "u" not in field.values or "v" not in field.values:
        return None, ""
    values = wind_speed(field.values["u"], field.values["v"])
    if ref_lat is not None and ref_lon is not None:
        values = _align_to_grid(values, field.lat, field.lon, ref_lat, ref_lon)
    return values, field.source_path


def _optional_10m_wind(
    root: Path,
    run_time: str,
    forecast_hour: int,
    *,
    ref_lat: np.ndarray | None = None,
    ref_lon: np.ndarray | None = None,
) -> tuple[np.ndarray | None, np.ndarray | None, list[str]]:
    u10, u10_path = _optional_existing_array(root, "10u", "999", "10u", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    v10, v10_path = _optional_existing_array(root, "10v", "999", "10v", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    return u10, v10, [path for path in [u10_path, v10_path] if path]


def _nanmax_available(values: list[np.ndarray | None]) -> np.ndarray | None:
    arrays = [np.asarray(item, dtype=float) for item in values if item is not None]
    if not arrays:
        return None
    return np.nanmax(np.stack(arrays), axis=0)


def _nanmean_available(values: list[np.ndarray | None]) -> np.ndarray | None:
    arrays = [np.asarray(item, dtype=float) for item in values if item is not None]
    if not arrays:
        return None
    return np.nanmean(np.stack(arrays), axis=0)


def _risk_input_bundle(root: Path, run_time: str, forecast_hour: int) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, list[str]]:
    uv850, q850, u850, v850, q = _moisture_fields(root, run_time, forecast_hour)
    ref_lat = q850.lat
    ref_lon = q850.lon
    fu, fv, mflux = moisture_flux(u850, v850, q)
    mconv = moisture_convergence(fu, fv, ref_lat, ref_lon)
    fields: dict[str, np.ndarray] = {}
    source_paths: list[str] = []
    _add_risk_input(fields, source_paths, "q850", q, q850.source_path)
    _add_risk_input(fields, source_paths, "moisture", q, q850.source_path)
    _add_risk_input(fields, source_paths, "moisture_flux", mflux, uv850.source_path)
    _add_source_path(source_paths, q850.source_path)
    _add_risk_input(fields, source_paths, "moisture_convergence", mconv, uv850.source_path)
    _add_source_path(source_paths, q850.source_path)

    for key, element, level, variable in [
        ("div850", "div", "850", "div"),
        ("omega700", "w", "700", "w"),
        ("k_index", "kindex", "999", "kindex"),
        ("cape", "cape", "999", "cape"),
        ("cin", "cin", "999", "cin"),
        ("dcape", "dcape", "999", "dcape"),
        ("li", "li", "999", "li"),
        ("srh", "srh", "999", "srh"),
        ("rh850", "rh", "850", "rh"),
        ("rh700", "rh", "700", "rh"),
        ("rh500", "rh", "500", "rh"),
        ("t700", "tt", "700", "tt"),
        ("t500", "tt", "500", "tt"),
        ("td2m", "td2", "999", "td2"),
        ("t2m", "t2m", "999", "t2m"),
        ("pw", "tcwv", "999", "tcwv"),
        ("lcl", "lcl", "999", "lcl"),
        ("z0_c_m", "deg0l", "999", "deg0l"),
    ]:
        values, path = _optional_existing_array(
            root,
            element,
            level,
            variable,
            run_time,
            forecast_hour,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
        )
        _add_risk_input(fields, source_paths, key, values, path)

    z500, z500_path = _optional_existing_array(root, "gh", "500", "gh", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    z700, z700_path = _optional_existing_array(root, "gh", "700", "gh", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    _add_risk_input(fields, source_paths, "z500", _scaled_gh(z500) if z500 is not None else None, z500_path)
    _add_risk_input(fields, source_paths, "z700", _scaled_gh(z700) if z700 is not None else None, z700_path)

    precip24, precip24_paths, precip24_meta = _optional_precip_interval_array(
        root,
        [("rain24", "999", "rain24", 24), ("tp", "999", "tp", 24), ("rain", "999", "rain", 24)],
        run_time,
        forecast_hour,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
    )
    _add_risk_input(fields, source_paths, "precip_24h", precip24, precip24_paths[0] if precip24_paths else None)
    for path in precip24_paths[1:]:
        _add_source_path(source_paths, path)
    precip6, precip6_paths, precip6_meta = _optional_precip_interval_array(
        root,
        [("rain6", "999", "rain6", 6), ("tp", "999", "tp", 6), ("rain", "999", "rain", 6)],
        run_time,
        forecast_hour,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
    )
    _add_risk_input(fields, source_paths, "precipitation", precip6, precip6_paths[0] if precip6_paths else None)
    _add_risk_input(fields, source_paths, "precip_6h", precip6, precip6_paths[0] if precip6_paths else None)
    for path in precip6_paths[1:]:
        _add_source_path(source_paths, path)
    precip3, precip3_paths, precip3_meta = _optional_precip_interval_array(
        root,
        [("rain3", "999", "rain3", 3), ("rainmax3", "999", "rainmax3", 3), ("tp", "999", "tp", 3), ("rain", "999", "rain", 3)],
        run_time,
        forecast_hour,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
    )
    _add_risk_input(fields, source_paths, "precip_3h", precip3, precip3_paths[0] if precip3_paths else None)
    for path in precip3_paths[1:]:
        _add_source_path(source_paths, path)
    shear, shear_path = _first_existing_array(
        root,
        [("shr6km", "999", "shr6km"), ("shr850-200", "999", "shr850-200")],
        run_time,
        forecast_hour,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
    )
    _add_risk_input(fields, source_paths, "shear_0_6km", shear, shear_path)
    shear01, shear01_path = _first_existing_array(
        root,
        [("shr1km", "999", "shr1km"), ("shr0-1", "999", "shr0-1")],
        run_time,
        forecast_hour,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
    )
    _add_risk_input(fields, source_paths, "shear_0_1km", shear01, shear01_path)

    wind500, uv500_path = _optional_wind_speed(root, "uv", "500", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    wind850 = wind_speed(u850, v850)
    _add_risk_input(fields, source_paths, "wind500", wind500, uv500_path)
    mean_wind = _nanmean_available([wind850, wind500])
    _add_risk_input(fields, source_paths, "mean_wind_850_500", mean_wind, uv850.source_path)
    _add_source_path(source_paths, uv500_path)

    u10, v10, wind10_paths = _optional_10m_wind(root, run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    if shear01 is None and u10 is not None and v10 is not None:
        low_level_shear = wind_speed(u850 - u10, v850 - v10)
        _add_risk_input(fields, source_paths, "shear_0_1km", low_level_shear, wind10_paths[0] if wind10_paths else None)
    for path in wind10_paths:
        _add_source_path(source_paths, path)

    div200, div200_path = _optional_existing_array(root, "div", "200", "div", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    div300, div300_path = _optional_existing_array(root, "div", "300", "div", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    upper_divergence = _nanmax_available([div200, div300])
    _add_risk_input(fields, source_paths, "upper_divergence", upper_divergence, div200_path)
    _add_source_path(source_paths, div300_path)
    pva300, pva300_path = _optional_existing_array(root, "pvadv", "300", "pvadv", run_time, forecast_hour, ref_lat=ref_lat, ref_lon=ref_lon)
    _add_risk_input(fields, source_paths, "pva500", pva300, pva300_path)

    return fields, ref_lat, ref_lon, source_paths


def nafp_multi_hazard_score_details(
    root: Path,
    run_time: str,
    forecast_hour: int,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, list[str]]:
    fields, lat, lon, source_paths = _risk_input_bundle(root, run_time, forecast_hour)
    details = multi_hazard_score_details(fields, load_thresholds())
    return details, lat, lon, source_paths


def _risk_scores(root: Path, layer_id: str, run_time: str, forecast_hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    details, lat, lon, source_paths = nafp_multi_hazard_score_details(root, run_time, forecast_hour)
    return details["scores"][layer_id], lat, lon, source_paths


DERIVED_LAYERS = {
    "wind850_speed": _wind850_speed,
    "vort500": _vort500,
    "moisture_flux850": _moisture_flux850,
    "moisture_conv850": _moisture_conv850,
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
