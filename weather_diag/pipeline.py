from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import xarray as xr

from weather_diag.config import PRODUCTS_DIR, load_model_config, load_thresholds, ensure_dirs
from weather_diag.data.reader import open_standard_dataset
from weather_diag.diagnostics.wind import wind_speed, wind_direction_from
from weather_diag.diagnostics.divergence import divergence
from weather_diag.diagnostics.vorticity import relative_vorticity
from weather_diag.diagnostics.advection import scalar_advection
from weather_diag.diagnostics.moisture import moisture_flux, moisture_convergence
from weather_diag.diagnostics.instability import k_index, deep_layer_shear
from weather_diag.features.pressure import detect_high_low
from weather_diag.features.subtropical_high import detect_subtropical_high
from weather_diag.features.convergence import detect_low_level_convergence, detect_upper_divergence
from weather_diag.features.low_level_jet import detect_low_level_jet
from weather_diag.features.moisture_transport import detect_moisture_transport
from weather_diag.features.trough_ridge import detect_trough_ridge
from weather_diag.features.front import detect_front_candidates
from weather_diag.features.risk import (
    detect_hazard_risk_features,
    multi_hazard_score_details,
)
from weather_diag.diagnosis.system_links import attach_feature_supporting_systems
from weather_diag.io.geojson import feature_collection
from weather_diag.analysis.report import generate_situation_report


MULTI_HAZARD_SCORE_LABELS = {
    "risk_persistent_heavy_rain_score": "持续性强降水风险评分",
    "risk_short_duration_heavy_rain_score": "短时强降水风险评分",
    "risk_thunderstorm_gale_score": "雷暴大风/下击暴流风险评分",
    "risk_hail_score": "冰雹风险评分",
    "risk_rotating_storm_score": "旋转风暴/超级单体潜势评分",
    "risk_severe_convection_composite_score": "强对流综合风险评分",
}


def _available_level(sds, standard_name: str, level: int) -> bool:
    if not sds.has(standard_name):
        return False
    da = sds.var(standard_name)
    if "level" not in da.dims:
        return level is None
    levels = np.asarray(sds.ds["level"].values, dtype=float)
    return np.nanmin(np.abs(levels - level)) < 5


def _safe_select(sds, name, fh, level=None):
    try:
        return sds.select2d(name, forecast_hour=fh, level=level).values.astype(float)
    except Exception:
        return None


def _add_var(data_vars: dict, name: str, arr, lat, lon, attrs: dict | None = None):
    if arr is not None:
        data_vars[name] = (("lat", "lon"), np.asarray(arr, dtype=np.float32), attrs or {})


def _safe_select_precipitation(sds, fh, window_hours: int | None = None):
    try:
        da = sds.select_precipitation_amount(forecast_hour=int(fh), window_hours=window_hours)
        if window_hours is not None:
            actual_period = da.attrs.get("precipitation_period_hours")
            try:
                actual_period = float(actual_period)
            except (TypeError, ValueError):
                actual_period = float(window_hours)
            # Do not label a 6h or 12h accumulation as 1h/3h short-duration rain.
            if actual_period > max(float(window_hours) * 1.5, float(window_hours) + 1.0):
                return None
        return da.values.astype(float)
    except Exception:
        if window_hours is None:
            return _safe_select(sds, "precipitation", fh)
        return None


def diagnose_file(file_path: str | Path, *, model: str = "ecmwf", run_id: str | None = None) -> Dict[str, Any]:
    ensure_dirs()
    file_path = Path(file_path)
    if run_id is None:
        run_id = file_path.stem
    model_cfg = load_model_config(model)
    thresholds = load_thresholds()
    sds = open_standard_dataset(file_path, model, model_cfg)
    lat, lon = sds.lat, sds.lon
    run_dir = PRODUCTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "run_id": run_id,
        "model": model,
        "source_file": str(file_path),
        "forecast_hours": [],
        "variable_map": sds.variable_map,
        "products": {},
    }

    for fh in sds.forecast_hours:
        fh_dir = run_dir / f"fh_{int(fh):03d}"
        fh_dir.mkdir(parents=True, exist_ok=True)
        data_vars = {}
        features: list[dict] = []

        # Base fields
        mslp = _safe_select(sds, "mslp", fh)
        z500 = _safe_select(sds, "geopotential", fh, 500)
        if z500 is None:
            z500 = _safe_select(sds, "geopotential_height", fh, 500)
        z700 = _safe_select(sds, "geopotential", fh, 700)
        if z700 is None:
            z700 = _safe_select(sds, "geopotential_height", fh, 700)
        t850 = _safe_select(sds, "temperature", fh, 850)
        t700 = _safe_select(sds, "temperature", fh, 700)
        t500 = _safe_select(sds, "temperature", fh, 500)
        t2m = _safe_select(sds, "t2m", fh)
        td2m = _safe_select(sds, "d2m", fh)
        u850 = _safe_select(sds, "u_wind", fh, 850)
        v850 = _safe_select(sds, "v_wind", fh, 850)
        u925 = _safe_select(sds, "u_wind", fh, 925)
        v925 = _safe_select(sds, "v_wind", fh, 925)
        u500 = _safe_select(sds, "u_wind", fh, 500)
        v500 = _safe_select(sds, "v_wind", fh, 500)
        u300 = _safe_select(sds, "u_wind", fh, 300)
        v300 = _safe_select(sds, "v_wind", fh, 300)
        u200 = _safe_select(sds, "u_wind", fh, 200)
        v200 = _safe_select(sds, "v_wind", fh, 200)
        u10 = _safe_select(sds, "u10", fh)
        v10 = _safe_select(sds, "v10", fh)
        q850 = _safe_select(sds, "specific_humidity", fh, 850)
        rh850 = _safe_select(sds, "relative_humidity", fh, 850)
        rh700 = _safe_select(sds, "relative_humidity", fh, 700)
        rh500 = _safe_select(sds, "relative_humidity", fh, 500)
        omega700 = _safe_select(sds, "vertical_velocity", fh, 700)
        precip = _safe_select_precipitation(sds, fh)
        precip_1h = _safe_select_precipitation(sds, fh, 1)
        precip_3h = _safe_select_precipitation(sds, fh, 3)
        precip_6h = _safe_select_precipitation(sds, fh, 6)
        precip_24h = _safe_select_precipitation(sds, fh, 24)
        cape = _safe_select(sds, "cape", fh)
        cin = _safe_select(sds, "cin", fh)

        # Diagnostics
        wind850_speed = wind500_speed = wind_direction850 = div850 = vort500 = vort850 = None
        moisture_flux850 = moisture_conv850 = temp_adv850 = vort_adv500 = kidx = shear06 = None
        shear01 = mean_wind_850_500 = None
        div_upper = upper_level = None

        if u850 is not None and v850 is not None:
            wind850_speed = wind_speed(u850, v850)
            wind_direction850 = wind_direction_from(u850, v850)
            div850 = divergence(u850, v850, lat, lon)
            vort850 = relative_vorticity(u850, v850, lat, lon)
        if u500 is not None and v500 is not None:
            wind500_speed = wind_speed(u500, v500)
            vort500 = relative_vorticity(u500, v500, lat, lon)
            if vort500 is not None:
                vort_adv500 = scalar_advection(u500, v500, vort500, lat, lon)
        if u850 is not None and v850 is not None and t850 is not None:
            temp_adv850 = scalar_advection(u850, v850, t850, lat, lon)
        if u850 is not None and v850 is not None and q850 is not None:
            fu, fv, moisture_flux850 = moisture_flux(u850, v850, q850)
            moisture_conv850 = moisture_convergence(fu, fv, lat, lon)
        if t850 is not None and t700 is not None and t500 is not None and rh850 is not None and rh700 is not None:
            try:
                kidx = k_index(t850, t700, t500, rh850=rh850, rh700=rh700)
            except Exception:
                kidx = None
        if u850 is not None and v850 is not None and u500 is not None and v500 is not None:
            shear06 = deep_layer_shear(u850, v850, u500, v500)
            mean_wind_850_500 = wind_speed((u850 + u500) / 2.0, (v850 + v500) / 2.0)
        if u10 is not None and v10 is not None and u850 is not None and v850 is not None:
            shear01 = deep_layer_shear(u10, v10, u850, v850)
        if u200 is not None and v200 is not None:
            div_upper = divergence(u200, v200, lat, lon); upper_level = 200
        elif u300 is not None and v300 is not None:
            div_upper = divergence(u300, v300, lat, lon); upper_level = 300

        # Hazard-specific risk scores.
        multi_hazard_fields = {
            "q850": q850,
            "td2m": td2m,
            "t2m": t2m,
            "rh850": rh850,
            "rh700": rh700,
            "rh500": rh500,
            "t700": t700,
            "t500": t500,
            "z700": z700,
            "z500": z500,
            "moisture_flux": moisture_flux850,
            "moisture_convergence": moisture_conv850,
            "div850": div850,
            "omega700": omega700,
            "k_index": kidx,
            "cape": cape,
            "precipitation": precip,
            "precip_1h": precip_1h,
            "precip_3h": precip_3h,
            "precip_6h": precip_6h,
            "precip_24h": precip_24h,
            "cin": cin,
            "shear_0_6km": shear06,
            "shear_0_1km": shear01,
            "wind500": wind500_speed,
            "mean_wind_850_500": mean_wind_850_500,
            "pva500": vort_adv500,
            "upper_divergence": div_upper,
            "dcape": None,
            "srh": None,
            "li": None,
        }
        multi_hazard_details = (
            multi_hazard_score_details(multi_hazard_fields, thresholds)
            if any(x is not None for x in multi_hazard_fields.values())
            else None
        )

        # Save diagnostic variables
        _add_var(data_vars, "mslp", mslp, lat, lon, {"units": "hPa"})
        _add_var(data_vars, "z500", z500, lat, lon, {"units": "gpm"})
        _add_var(data_vars, "z700", z700, lat, lon, {"units": "gpm"})
        _add_var(data_vars, "t2m", t2m, lat, lon, {"units": "degC"})
        _add_var(data_vars, "td2m", td2m, lat, lon, {"units": "degC"})
        _add_var(data_vars, "t850", t850, lat, lon, {"units": "degC"})
        _add_var(data_vars, "t700", t700, lat, lon, {"units": "degC"})
        _add_var(data_vars, "t500", t500, lat, lon, {"units": "degC"})
        _add_var(data_vars, "rh850", rh850, lat, lon, {"units": "%"})
        _add_var(data_vars, "rh700", rh700, lat, lon, {"units": "%"})
        _add_var(data_vars, "rh500", rh500, lat, lon, {"units": "%"})
        _add_var(data_vars, "wind850_speed", wind850_speed, lat, lon, {"units": "m/s"})
        _add_var(data_vars, "wind500_speed", wind500_speed, lat, lon, {"units": "m/s"})
        _add_var(data_vars, "wind850_direction", wind_direction850, lat, lon, {"units": "degree_from"})
        _add_var(data_vars, "div850", div850, lat, lon, {"units": "s^-1"})
        _add_var(data_vars, "vort850", vort850, lat, lon, {"units": "s^-1"})
        _add_var(data_vars, "vort500", vort500, lat, lon, {"units": "s^-1"})
        _add_var(data_vars, "vort_adv500", vort_adv500, lat, lon, {"units": "s^-2"})
        _add_var(data_vars, "moisture_flux850", moisture_flux850, lat, lon, {"units": "q*m/s"})
        _add_var(data_vars, "moisture_conv850", moisture_conv850, lat, lon, {"units": "s^-1"})
        _add_var(data_vars, "omega700", omega700, lat, lon, {"units": "Pa/s"})
        _add_var(data_vars, "temp_adv850", temp_adv850, lat, lon, {"units": "K/s"})
        _add_var(data_vars, "k_index", kidx, lat, lon, {"units": "degC"})
        _add_var(data_vars, "shear_0_6km", shear06, lat, lon, {"units": "m/s"})
        _add_var(data_vars, "shear_0_1km", shear01, lat, lon, {"units": "m/s"})
        _add_var(data_vars, "mean_wind_850_500", mean_wind_850_500, lat, lon, {"units": "m/s"})
        _add_var(data_vars, "cape", cape, lat, lon, {"units": "J/kg"})
        _add_var(data_vars, "cin", cin, lat, lon, {"units": "J/kg"})
        _add_var(data_vars, "precipitation", precip, lat, lon, {"units": "mm", "long_name": "current available precipitation amount"})
        _add_var(data_vars, "precip_1h", precip_1h, lat, lon, {"units": "mm", "long_name": "1h precipitation amount"})
        _add_var(data_vars, "precip_3h", precip_3h, lat, lon, {"units": "mm", "long_name": "3h precipitation amount"})
        _add_var(data_vars, "precip_6h", precip_6h, lat, lon, {"units": "mm", "long_name": "6h precipitation amount"})
        _add_var(data_vars, "precip_24h", precip_24h, lat, lon, {"units": "mm", "long_name": "24h precipitation amount"})
        if multi_hazard_details is not None:
            for name, score in multi_hazard_details["scores"].items():
                _add_var(
                    data_vars,
                    name,
                    score,
                    lat,
                    lon,
                    {"units": "0-1", "long_name": MULTI_HAZARD_SCORE_LABELS.get(name, name)},
                )
        if div_upper is not None:
            _add_var(data_vars, f"div{upper_level}", div_upper, lat, lon, {"units": "s^-1"})

        diag_ds = xr.Dataset(data_vars=data_vars, coords={"lat": lat, "lon": lon}, attrs={"run_id": run_id, "forecast_hour": int(fh)})
        diag_path = fh_dir / "diagnostics.nc"
        diag_ds.to_netcdf(diag_path)

        # Features
        if mslp is not None:
            features.extend(detect_high_low(mslp, lat, lon, thresholds))
        if z500 is not None:
            features.extend(detect_subtropical_high(z500, lat, lon, thresholds))
            troughs, ridges = detect_trough_ridge(z500, lat, lon, thresholds, vorticity500=vort500)
            features.extend(troughs); features.extend(ridges)
        if div850 is not None:
            features.extend(detect_low_level_convergence(div850, lat, lon, thresholds, u850=u850, v850=v850))
        if div_upper is not None:
            if upper_level == 200:
                features.extend(detect_upper_divergence(div_upper, lat, lon, thresholds, upper_level, u_upper=u200, v_upper=v200))
            else:
                features.extend(detect_upper_divergence(div_upper, lat, lon, thresholds, upper_level, u_upper=u300, v_upper=v300))
        if wind850_speed is not None:
            features.extend(detect_low_level_jet(wind850_speed, moisture_flux850, lat, lon, thresholds, u850=u850, v850=v850))
        if moisture_flux850 is not None:
            features.extend(detect_moisture_transport(moisture_flux850, lat, lon, thresholds, u850=u850, v850=v850))
        if t850 is not None:
            features.extend(
                detect_front_candidates(
                    t850,
                    div850,
                    temp_adv850,
                    lat,
                    lon,
                    thresholds,
                    u850=u850,
                    v850=v850,
                    rh850=rh850,
                )
            )
        if multi_hazard_details is not None:
            for hazard_type, score_grid in [
                ("persistent_heavy_rain", "risk_persistent_heavy_rain_score"),
                ("short_duration_heavy_rain", "risk_short_duration_heavy_rain_score"),
                ("thunderstorm_gale", "risk_thunderstorm_gale_score"),
                ("hail", "risk_hail_score"),
                ("rotating_storm_or_supercell", "risk_rotating_storm_score"),
                ("severe_convection_composite", "risk_severe_convection_composite_score"),
            ]:
                features.extend(
                    detect_hazard_risk_features(
                        hazard_type,
                        multi_hazard_details["scores"][score_grid],
                        lat,
                        lon,
                        thresholds,
                        factor_details=multi_hazard_details["factors"].get(score_grid),
                        risk_metadata=multi_hazard_details.get("metadata", {}).get(score_grid),
                    )
                )

        features = attach_feature_supporting_systems(features)
        features_json = feature_collection(features)
        features_path = fh_dir / "features.geojson"
        features_path.write_text(json.dumps(features_json, ensure_ascii=False, indent=2), encoding="utf-8")

        report = generate_situation_report(features_json, diag_ds, forecast_hour=int(fh))
        report_path = fh_dir / "analysis.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        index["forecast_hours"].append(int(fh))
        index["products"][str(int(fh))] = {
            "diagnostics": str(diag_path),
            "features": str(features_path),
            "analysis": str(report_path),
        }

    (run_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def run_product_dir(run_id: str) -> Path:
    return PRODUCTS_DIR / run_id


def load_run_index(run_id: str) -> Dict[str, Any]:
    path = run_product_dir(run_id) / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def forecast_dir(run_id: str, forecast_hour: int) -> Path:
    return run_product_dir(run_id) / f"fh_{int(forecast_hour):03d}"


def load_diagnostics(run_id: str, forecast_hour: int) -> xr.Dataset:
    path = forecast_dir(run_id, forecast_hour) / "diagnostics.nc"
    if not path.exists():
        raise FileNotFoundError(f"Diagnostics not found: {run_id} fh={forecast_hour}")
    return xr.open_dataset(path)


def load_features(run_id: str, forecast_hour: int) -> Dict[str, Any]:
    path = forecast_dir(run_id, forecast_hour) / "features.geojson"
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_analysis(run_id: str, forecast_hour: int) -> Dict[str, Any]:
    path = forecast_dir(run_id, forecast_hour) / "analysis.json"
    if not path.exists():
        return {"summary": "暂无分析结果"}
    return json.loads(path.read_text(encoding="utf-8"))
