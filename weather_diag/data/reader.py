from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np
import xarray as xr


@dataclass
class StandardDataset:
    ds: xr.Dataset
    model: str
    variable_map: Dict[str, str]
    lat_name: str = "lat"
    lon_name: str = "lon"
    level_name: str = "level"
    step_name: str = "forecast_hour"
    model_cfg: Dict[str, Any] = field(default_factory=dict)

    @property
    def lat(self) -> np.ndarray:
        return self.ds[self.lat_name].values

    @property
    def lon(self) -> np.ndarray:
        return self.ds[self.lon_name].values

    @property
    def forecast_hours(self) -> list[int]:
        if self.step_name in self.ds.coords:
            vals = self.ds[self.step_name].values
            out = []
            for v in vals:
                if hasattr(v, "astype") and "timedelta" in str(getattr(v, "dtype", "")):
                    out.append(int(v / np.timedelta64(1, "h")))
                else:
                    out.append(int(v))
            return out
        return [0]

    def has(self, standard_name: str) -> bool:
        return standard_name in self.variable_map and self.variable_map[standard_name] in self.ds.data_vars

    def var(self, standard_name: str) -> xr.DataArray:
        if not self.has(standard_name):
            raise KeyError(f"Variable not available: {standard_name}")
        return self.ds[self.variable_map[standard_name]]

    def _hour_index(self, forecast_hour: int, *, mode: str = "nearest") -> int | None:
        hours = self.forecast_hours
        if not hours:
            return None
        target = int(forecast_hour)
        if target in hours:
            return hours.index(target)
        arr = np.asarray(hours, dtype=int)
        if mode == "prior":
            prior = np.where(arr <= target)[0]
            return int(prior[-1]) if prior.size else None
        if mode == "after":
            after = np.where(arr >= target)[0]
            return int(after[0]) if after.size else None
        return int(np.argmin(np.abs(arr - target)))

    def _select_step(self, da: xr.DataArray, index: int) -> xr.DataArray:
        for dim in list(da.dims):
            if dim in {"time", "valid_time"} and da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0})
        if self.step_name in da.dims:
            da = da.isel({self.step_name: index})
        return da

    def select2d(self, standard_name: str, *, forecast_hour: int | None = None, level: int | None = None) -> xr.DataArray:
        da = self.var(standard_name)
        # Select first time-like dimension if present and not already represented by forecast_hour.
        for dim in list(da.dims):
            if dim in {"time", "valid_time"} and da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0})
        if forecast_hour is not None and self.step_name in da.dims:
            idx = self._hour_index(int(forecast_hour), mode="nearest")
            if idx is not None:
                da = da.isel({self.step_name: idx})
        if level is not None and self.level_name in da.dims:
            levels = np.asarray(self.ds[self.level_name].values, dtype=float)
            idx = int(np.argmin(np.abs(levels - float(level))))
            da = da.isel({self.level_name: idx})
        # Squeeze any remaining singleton dimensions.
        da = da.squeeze(drop=True)
        if da.ndim != 2:
            raise ValueError(f"Expected 2D field for {standard_name}, got dims={da.dims}")
        return da

    def select_precipitation_amount(
        self,
        *,
        forecast_hour: int,
        window_hours: int | None = None,
        accumulation_type: str | None = None,
    ) -> xr.DataArray:
        """Return precipitation amount in mm for the requested forecast period.

        Many EC/ECMWF NetCDF files store ``tp`` as accumulation from model start to
        the current forecast hour.  Risk algorithms, however, need interval amounts
        such as 3h/6h/24h precipitation.  This helper converts cumulative fields to
        window amounts when possible and falls back to the current field when the
        data looks like already-windowed precipitation.
        """
        if not self.has("precipitation"):
            raise KeyError("Variable not available: precipitation")
        cfg = dict(self.model_cfg.get("precipitation", {}) or {})
        kind = str(accumulation_type or cfg.get("accumulation_type") or "auto").lower()
        current = self.select2d("precipitation", forecast_hour=forecast_hour)
        if kind in {"interval", "instant", "step", "window"}:
            current.attrs["precipitation_period_hours"] = window_hours
            current.attrs["precipitation_accumulation_type"] = kind
            return current

        hours = sorted(int(h) for h in self.forecast_hours)
        if self.step_name not in self.var("precipitation").dims or len(hours) <= 1:
            current.attrs["precipitation_period_hours"] = window_hours
            current.attrs["precipitation_accumulation_type"] = "single_step"
            return current

        fh = int(forecast_hour)
        if window_hours is None:
            prior_candidates = [h for h in hours if h < fh]
            start_hour = prior_candidates[-1] if prior_candidates else 0
        else:
            start_target = max(0, fh - int(window_hours))
            prior_candidates = [h for h in hours if h <= start_target]
            start_hour = prior_candidates[-1] if prior_candidates else 0

        if start_hour >= fh:
            # Model start accumulation at fh=0 should be zero for cumulative TP.
            if kind in {"cumulative", "accumulated"}:
                out = current.copy(data=np.zeros_like(current.values, dtype=float))
                out.attrs["precipitation_period_hours"] = 0
                out.attrs["precipitation_accumulation_type"] = "cumulative_zero_step"
                return out
            current.attrs["precipitation_period_hours"] = window_hours
            current.attrs["precipitation_accumulation_type"] = "auto_current_step"
            return current

        previous = self.select2d("precipitation", forecast_hour=start_hour)
        diff_values = np.asarray(current.values, dtype=float) - np.asarray(previous.values, dtype=float)
        valid = diff_values[np.isfinite(diff_values)]
        negative_tolerance = float(cfg.get("negative_diff_tolerance_mm", -0.1))
        negative_fraction_limit = float(cfg.get("negative_diff_fraction_limit", 0.01))
        negative_fraction = float(np.mean(valid < negative_tolerance)) if valid.size else 1.0

        if kind == "auto" and negative_fraction > negative_fraction_limit:
            # A sizable negative area normally means the source is already an interval
            # amount, or the accumulation was reset.  Do not subtract in that case.
            out = current.copy()
            out.attrs["precipitation_period_hours"] = fh - start_hour
            out.attrs["requested_precipitation_window_hours"] = window_hours
            out.attrs["precipitation_accumulation_type"] = "auto_interval_fallback"
            out.attrs["negative_diff_fraction"] = negative_fraction
            return out

        diff_values = np.where(diff_values < negative_tolerance, np.nan, diff_values)
        diff_values = np.where(diff_values < 0.0, 0.0, diff_values)
        out = current.copy(data=diff_values)
        out.attrs["units"] = current.attrs.get("units", "mm")
        out.attrs["precipitation_period_hours"] = fh - start_hour
        out.attrs["requested_precipitation_window_hours"] = window_hours
        out.attrs["precipitation_accumulation_type"] = "cumulative_difference" if kind != "auto" else "auto_cumulative_difference"
        out.attrs["accumulation_start_forecast_hour"] = int(start_hour)
        out.attrs["accumulation_end_forecast_hour"] = int(fh)
        return out


def _first_existing(names: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    names_set = set(names)
    for c in candidates:
        if c in names_set:
            return c
    return None


def _standardize_dims(ds: xr.Dataset, model_cfg: Dict[str, Any]) -> xr.Dataset:
    dims_cfg = model_cfg.get("dimensions", {})
    rename = {}
    for std_name, candidates in {
        "lat": dims_cfg.get("latitude", ["latitude", "lat"]),
        "lon": dims_cfg.get("longitude", ["longitude", "lon"]),
        "level": dims_cfg.get("level", ["level", "pressure_level", "isobaricInhPa"]),
        "forecast_hour": dims_cfg.get("step", ["step", "forecast_hour", "leadtime"]),
    }.items():
        found = _first_existing(list(ds.dims) + list(ds.coords), candidates)
        if found and found != std_name:
            rename[found] = std_name
    if rename:
        ds = ds.rename(rename)

    if "lon" in ds.coords:
        lon = ds["lon"].values
        if np.nanmax(lon) > 180:
            new_lon = ((lon + 180) % 360) - 180
            ds = ds.assign_coords(lon=new_lon).sortby("lon")
    if "lat" in ds.coords:
        # Keep original sign/order for derivatives; but web rendering is easier if ascending.
        ds = ds.sortby("lat")
    return ds


def _build_variable_map(ds: xr.Dataset, model_cfg: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    variables = model_cfg.get("variables", {})
    for standard, candidates in variables.items():
        found = _first_existing(ds.data_vars, candidates)
        if found:
            out[standard] = found
    return out


def _convert_units(ds: xr.Dataset, variable_map: Dict[str, str], model_cfg: Dict[str, Any]) -> xr.Dataset:
    conv = model_cfg.get("unit_conversions", {})
    ds = ds.copy()

    def maybe_attr_units(var):
        return str(ds[var].attrs.get("units", "")).lower()

    for std, var in variable_map.items():
        c = conv.get(std, {})
        units = maybe_attr_units(var)
        if std == "mslp" and c.get("Pa_to_hPa"):
            if ("pa" in units and "hpa" not in units) or float(ds[var].max(skipna=True)) > 2000:
                ds[var] = ds[var] / 100.0
                ds[var].attrs["units"] = "hPa"
        if std in {"temperature", "t2m", "d2m"} and c.get("K_to_C"):
            if "k" == units.strip() or float(ds[var].mean(skipna=True)) > 100:
                ds[var] = ds[var] - 273.15
                ds[var].attrs["units"] = "degC"
        if std == "geopotential" and c.get("geopotential_to_gpm"):
            # ECMWF z is often geopotential m^2/s^2. If values are huge, convert to gpm.
            if float(ds[var].mean(skipna=True)) > 10000:
                ds[var] = ds[var] / 9.80665
                ds[var].attrs["units"] = "gpm"
        if std == "precipitation" and c.get("m_to_mm"):
            max_value = float(ds[var].max(skipna=True))
            units_clean = units.strip()
            is_mm = "mm" in units_clean or "millimeter" in units_clean or "millimetre" in units_clean
            is_kg_m2 = "kg" in units_clean and "m" in units_clean
            is_metre = units_clean in {"m", "meter", "meters", "metre", "metres"}
            # kg m-2 is mm-equivalent.  Avoid blindly multiplying all small native mm fields.
            if is_metre or (not is_mm and not is_kg_m2 and max_value < 2):
                ds[var] = ds[var] * 1000.0
                ds[var].attrs["units"] = "mm"
            elif is_kg_m2:
                ds[var].attrs["units"] = "mm"
    return ds


def open_standard_dataset(path: str | Path, model: str, model_cfg: Dict[str, Any]) -> StandardDataset:
    path = Path(path)
    ds = xr.open_dataset(path)
    ds = _standardize_dims(ds, model_cfg)
    variable_map = _build_variable_map(ds, model_cfg)
    ds = _convert_units(ds, variable_map, model_cfg)
    return StandardDataset(ds=ds, model=model, variable_map=variable_map, model_cfg=model_cfg)


def inspect_netcdf(path: str | Path) -> Dict[str, Any]:
    ds = xr.open_dataset(path)
    return {
        "path": str(path),
        "dimensions": {k: int(v) for k, v in ds.sizes.items()},
        "coordinates": list(ds.coords),
        "variables": {
            name: {
                "dims": list(da.dims),
                "shape": list(da.shape),
                "units": da.attrs.get("units", ""),
                "long_name": da.attrs.get("long_name", ""),
            }
            for name, da in ds.data_vars.items()
        },
    }
