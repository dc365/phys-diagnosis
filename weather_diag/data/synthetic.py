from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr


def create_demo_ecmwf_netcdf(path: str | Path) -> Path:
    """Create a small synthetic EC-like NetCDF file for MVP demonstration."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lat = np.linspace(15, 55, 81)
    lon = np.linspace(70, 140, 101)
    levels = np.array([200, 300, 500, 700, 850, 925], dtype=np.int32)
    forecast_hour = np.array([0, 6, 12, 24, 36], dtype=np.int32)
    time = pd.to_datetime(["2026-06-16T00:00:00"])
    LON, LAT = np.meshgrid(lon, lat)

    shape4 = (1, len(forecast_hour), len(levels), len(lat), len(lon))
    t = np.zeros(shape4, dtype=np.float32)
    z = np.zeros(shape4, dtype=np.float32)
    u = np.zeros(shape4, dtype=np.float32)
    v = np.zeros(shape4, dtype=np.float32)
    q = np.zeros(shape4, dtype=np.float32)
    r = np.zeros(shape4, dtype=np.float32)
    w = np.zeros(shape4, dtype=np.float32)

    for si, fh in enumerate(forecast_hour):
        phase = fh / 24.0
        # Moving low/trough center.
        low_lon = 105 + 0.25 * fh
        low_lat = 33 + 1.5 * np.sin(phase)
        dist2 = ((LON - low_lon) / 10) ** 2 + ((LAT - low_lat) / 7) ** 2
        moist_band = np.exp(-((LAT - (28 + 0.08 * fh)) / 6) ** 2) * np.exp(-((LON - 110) / 28) ** 2)
        for li, lev in enumerate(levels):
            height_base = {925: 780, 850: 1480, 700: 3100, 500: 5800, 300: 9400, 200: 12300}[int(lev)]
            temp_base = {925: 24, 850: 18, 700: 6, 500: -8, 300: -35, 200: -52}[int(lev)]
            z_anom = -120 * np.exp(-dist2) if lev in [500, 700, 850] else -50 * np.exp(-dist2)
            ridge = 100 * np.exp(-((LAT - 24) / 8) ** 2) if lev == 500 else 20 * np.exp(-((LAT - 24) / 8) ** 2)
            z[0, si, li] = (height_base + 8 * (LON - 100) / 40 + z_anom + ridge).astype(np.float32)
            t[0, si, li] = (temp_base - 0.18 * (LAT - 30) + 2 * moist_band - 2 * np.exp(-dist2)).astype(np.float32)
            # Background southwest low-level flow and stronger westerly aloft.
            u_bg = {925: 4, 850: 8, 700: 12, 500: 18, 300: 28, 200: 35}[int(lev)]
            v_bg = {925: 4, 850: 7, 700: 5, 500: 2, 300: 0, 200: -2}[int(lev)]
            # Add cyclonic perturbation around low.
            dx = (LON - low_lon) / 10
            dy = (LAT - low_lat) / 7
            swirl = np.exp(-dist2)
            u[0, si, li] = (u_bg - 7 * dy * swirl).astype(np.float32)
            v[0, si, li] = (v_bg + 7 * dx * swirl).astype(np.float32)
            q_base = {925: 0.014, 850: 0.012, 700: 0.006, 500: 0.002, 300: 0.0005, 200: 0.0001}[int(lev)]
            q[0, si, li] = (q_base * (1 + 1.3 * moist_band)).astype(np.float32)
            r[0, si, li] = np.clip(45 + 45 * moist_band + 25 * np.exp(-dist2) - 5 * (lev == 500), 10, 100).astype(np.float32)
            # omega: negative upward motion near low/moist band at 700/500.
            amp = -0.45 if lev == 700 else (-0.25 if lev == 500 else -0.08)
            w[0, si, li] = (amp * np.exp(-dist2) * (1 + moist_band)).astype(np.float32)

    # Surface fields
    msl = np.zeros((1, len(forecast_hour), len(lat), len(lon)), dtype=np.float32)
    tp = np.zeros_like(msl)
    cape = np.zeros_like(msl)
    cin = np.zeros_like(msl)
    t2m = np.zeros_like(msl)
    d2m = np.zeros_like(msl)
    u10 = np.zeros_like(msl)
    v10 = np.zeros_like(msl)
    for si, fh in enumerate(forecast_hour):
        low_lon = 105 + 0.25 * fh
        low_lat = 33 + 1.5 * np.sin(fh / 24)
        dist2 = ((LON - low_lon) / 10) ** 2 + ((LAT - low_lat) / 7) ** 2
        high = np.exp(-((LON - 85) / 15) ** 2 - ((LAT - 42) / 10) ** 2)
        moist_band = np.exp(-((LAT - (28 + 0.08 * fh)) / 6) ** 2) * np.exp(-((LON - 110) / 28) ** 2)
        msl[0, si] = (1012 - 10 * np.exp(-dist2) + 12 * high).astype(np.float32) * 100.0
        rain_core = np.exp(-dist2) * moist_band
        tp[0, si] = (5 + 45 * rain_core + 8 * moist_band * (fh / 36)).astype(np.float32) / 1000.0
        cape[0, si] = (200 + 1800 * moist_band + 500 * np.exp(-dist2)).astype(np.float32)
        cin[0, si] = (-20 - 80 * np.exp(-((LAT - 27) / 7) ** 2)).astype(np.float32)
        t2m[0, si] = (25 + 5 * np.exp(-((LAT - 28) / 8) ** 2) - 3 * np.exp(-dist2)).astype(np.float32) + 273.15
        d2m[0, si] = (18 + 6 * moist_band).astype(np.float32) + 273.15
        u10[0, si] = (2 + 4 * moist_band - 2 * (LAT > 38)).astype(np.float32)
        v10[0, si] = (3 + 3 * moist_band - 4 * (LAT > 38)).astype(np.float32)

    ds = xr.Dataset(
        data_vars={
            "msl": (("time", "forecast_hour", "latitude", "longitude"), msl, {"units": "Pa"}),
            "z": (("time", "forecast_hour", "level", "latitude", "longitude"), z * 9.80665, {"units": "m**2 s**-2"}),
            "t": (("time", "forecast_hour", "level", "latitude", "longitude"), t + 273.15, {"units": "K"}),
            "u": (("time", "forecast_hour", "level", "latitude", "longitude"), u, {"units": "m s**-1"}),
            "v": (("time", "forecast_hour", "level", "latitude", "longitude"), v, {"units": "m s**-1"}),
            "q": (("time", "forecast_hour", "level", "latitude", "longitude"), q, {"units": "kg kg**-1"}),
            "r": (("time", "forecast_hour", "level", "latitude", "longitude"), r, {"units": "%"}),
            "w": (("time", "forecast_hour", "level", "latitude", "longitude"), w, {"units": "Pa s**-1"}),
            "tp": (("time", "forecast_hour", "latitude", "longitude"), tp, {"units": "m"}),
            "cape": (("time", "forecast_hour", "latitude", "longitude"), cape, {"units": "J kg**-1"}),
            "cin": (("time", "forecast_hour", "latitude", "longitude"), cin, {"units": "J kg**-1"}),
            "t2m": (("time", "forecast_hour", "latitude", "longitude"), t2m, {"units": "K"}),
            "d2m": (("time", "forecast_hour", "latitude", "longitude"), d2m, {"units": "K"}),
            "u10": (("time", "forecast_hour", "latitude", "longitude"), u10, {"units": "m s**-1"}),
            "v10": (("time", "forecast_hour", "latitude", "longitude"), v10, {"units": "m s**-1"}),
        },
        coords={"time": time, "forecast_hour": forecast_hour, "level": levels, "latitude": lat, "longitude": lon},
        attrs={"model": "ecmwf-demo", "description": "Synthetic EC-like dataset for Weather Diagnosis MVP"},
    )
    ds.to_netcdf(path)
    return path
