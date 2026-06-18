from __future__ import annotations

from dataclasses import dataclass
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

    def select2d(self, standard_name: str, *, forecast_hour: int | None = None, level: int | None = None) -> xr.DataArray:
        da = self.var(standard_name)
        # Select first time-like dimension if present and not already represented by forecast_hour.
        for dim in list(da.dims):
            if dim in {"time", "valid_time"} and da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0})
        if forecast_hour is not None and self.step_name in da.dims:
            coords = self.ds[self.step_name].values
            hours = []
            for v in coords:
                if hasattr(v, "dtype") and "timedelta" in str(v.dtype):
                    hours.append(int(v / np.timedelta64(1, "h")))
                else:
                    hours.append(int(v))
            if forecast_hour in hours:
                da = da.isel({self.step_name: hours.index(forecast_hour)})
            else:
                # nearest fallback
                idx = int(np.argmin(np.abs(np.asarray(hours) - forecast_hour)))
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
            if "pa" in units and "hpa" not in units or float(ds[var].max(skipna=True)) > 2000:
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
            if "m" in units and "mm" not in units or float(ds[var].max(skipna=True)) < 5:
                ds[var] = ds[var] * 1000.0
                ds[var].attrs["units"] = "mm"
    return ds


def open_standard_dataset(path: str | Path, model: str, model_cfg: Dict[str, Any]) -> StandardDataset:
    path = Path(path)
    ds = xr.open_dataset(path)
    ds = _standardize_dims(ds, model_cfg)
    variable_map = _build_variable_map(ds, model_cfg)
    ds = _convert_units(ds, variable_map, model_cfg)
    return StandardDataset(ds=ds, model=model, variable_map=variable_map)


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
