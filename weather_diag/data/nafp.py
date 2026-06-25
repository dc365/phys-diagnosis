from __future__ import annotations

import gzip
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


NAFP_SAMPLE_ROOT = Path("/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC")


@dataclass
class NafpField:
    element: str
    level: str
    key: str
    lat: np.ndarray
    lon: np.ndarray
    values: dict[str, np.ndarray]
    attrs: dict[str, Any]
    source_path: str
    exists: bool = True
    missing_reason: str | None = None
    variables: list[str] = field(default_factory=list)


def parse_run_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def nafp_product_path(
    root: str | Path,
    element: str,
    level: str | int,
    run_time: str | datetime,
    forecast_hour: int,
) -> Path:
    rt = parse_run_time(run_time)
    return (
        Path(root)
        / element
        / str(level)
        / f"{rt.year:04d}"
        / f"{rt.month:02d}"
        / f"{rt.day:02d}"
        / f"{rt.hour:02d}"
        / f"{rt:%y%m%d%H}.{int(forecast_hour):03d}"
    )


def _is_gzip(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(2) == b"\x1f\x8b"


def _normalize_coords(ds: xr.Dataset) -> xr.Dataset:
    rename = {}
    for candidate in ("latitude", "Latitude", "y"):
        if candidate in ds.coords or candidate in ds.dims:
            rename[candidate] = "lat"
            break
    for candidate in ("longitude", "Longitude", "x"):
        if candidate in ds.coords or candidate in ds.dims:
            rename[candidate] = "lon"
            break
    if rename:
        ds = ds.rename(rename)
    if "lat" in ds.coords:
        ds = ds.sortby("lat")
    if "lon" in ds.coords:
        ds = ds.sortby("lon")
    return ds


def open_nafp_dataset(path: str | Path) -> xr.Dataset:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if _is_gzip(path):
        with gzip.open(path, "rb") as src, tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
            tmp.write(src.read())
            tmp.flush()
            return _normalize_coords(xr.open_dataset(tmp.name).load())
    return _normalize_coords(xr.open_dataset(path).load())


def _numeric_attr(attrs: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in attrs:
            continue
        try:
            return float(attrs[key])
        except (TypeError, ValueError):
            continue
    return None


def _mask_declared_missing(values: np.ndarray, attrs: dict[str, Any]) -> np.ndarray:
    arr = np.asarray(values, dtype=float).copy()
    missing = _numeric_attr(attrs, "MissingValue", "missing_value", "_FillValue")
    if missing is not None and np.isfinite(missing):
        if missing >= 0:
            arr[arr >= missing] = np.nan
        else:
            arr[arr <= missing] = np.nan
    fixed = _numeric_attr(attrs, "FixedValue")
    if fixed is not None and np.isfinite(fixed):
        if fixed >= 0:
            arr[arr >= fixed] = np.nan
        else:
            arr[arr <= fixed] = np.nan
    return arr


def missing_field(
    element: str,
    level: str | int,
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
    reason: str,
) -> NafpField:
    path = nafp_product_path(root, element, level, run_time, forecast_hour)
    return NafpField(
        element=element,
        level=str(level),
        key=f"{element}{level}",
        lat=np.asarray([]),
        lon=np.asarray([]),
        values={},
        attrs={},
        source_path=str(path),
        exists=False,
        missing_reason=reason,
    )


def load_nafp_field(
    root: str | Path,
    element: str,
    level: str | int,
    run_time: str | datetime,
    forecast_hour: int,
    *,
    required: bool = True,
) -> NafpField:
    path = nafp_product_path(root, element, level, run_time, forecast_hour)
    if not path.exists():
        if required:
            raise FileNotFoundError(str(path))
        return missing_field(element, level, root, run_time, forecast_hour, "not_found")
    ds = open_nafp_dataset(path)
    lat = ds["lat"].values
    lon = ds["lon"].values
    values = {
        name: _mask_declared_missing(da.squeeze(drop=True).values, {**ds.attrs, **da.attrs})
        for name, da in ds.data_vars.items()
    }
    return NafpField(
        element=element,
        level=str(level),
        key=f"{element}{level}",
        lat=lat,
        lon=lon,
        values=values,
        attrs=dict(ds.attrs),
        source_path=str(path),
        variables=list(values),
    )
