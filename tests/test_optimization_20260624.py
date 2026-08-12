from __future__ import annotations

import numpy as np
import xarray as xr

from weather_diag.data.reader import open_standard_dataset
from weather_diag.features.risk_scoring import score_rotating_storm_supercell
from weather_diag.features.front import detect_front_candidates


def test_ec_cumulative_precipitation_is_converted_to_period_amount(tmp_path):
    lat = np.array([20.0, 21.0])
    lon = np.array([110.0, 111.0])
    forecast_hour = np.array([0, 3, 6])
    tp = np.zeros((1, 3, 2, 2), dtype=np.float32)
    tp[0, 0] = 0.0
    tp[0, 1] = 0.003
    tp[0, 2] = 0.009
    path = tmp_path / "ec_cumulative_tp.nc"
    xr.Dataset(
        {"tp": (("time", "forecast_hour", "latitude", "longitude"), tp, {"units": "m"})},
        coords={"time": [np.datetime64("2026-06-24T00:00:00")], "forecast_hour": forecast_hour, "latitude": lat, "longitude": lon},
    ).to_netcdf(path)
    sds = open_standard_dataset(
        path,
        "ecmwf",
        {
            "variables": {"precipitation": ["tp"]},
            "dimensions": {"latitude": ["latitude"], "longitude": ["longitude"], "step": ["forecast_hour"]},
            "unit_conversions": {"precipitation": {"m_to_mm": True}},
            "precipitation": {"accumulation_type": "cumulative"},
        },
    )

    np.testing.assert_allclose(sds.select_precipitation_amount(forecast_hour=6, window_hours=3).values, 6.0)
    np.testing.assert_allclose(sds.select_precipitation_amount(forecast_hour=6, window_hours=6).values, 9.0)


def test_risk_output_reports_missing_critical_factors_and_score_cap():
    grid = np.ones((2, 2), dtype=float)
    output = score_rotating_storm_supercell(
        {
            "cape": grid * 2500.0,
            "shear_0_6km": grid * 25.0,
            "div850": grid * -4.0e-5,
            "cin": grid * -25.0,
            "lcl": grid * 600.0,
        },
        {},
    )

    assert "srh" in output["missing_critical_factors"]
    assert "low_level_shear" in output["missing_critical_factors"]
    assert float(np.nanmax(output["score_cap_grid"])) <= 55.0
    assert float(np.nanmax(output["score_grid"])) <= 55.0


def test_front_candidates_default_to_linestring_axis():
    lat = np.linspace(25.0, 45.0, 41)
    lon = np.linspace(100.0, 125.0, 51)
    _lon2d, lat2d = np.meshgrid(lon, lat)
    t850 = 12.0 - 9.0 * np.tanh((lat2d - 35.0) / 1.3)
    features = detect_front_candidates(
        t850,
        None,
        None,
        lat,
        lon,
        {"front_candidate": {"temp_gradient_percentile": 70, "score_percentile": 70, "min_area_grid_points": 5, "max_objects": 1}},
    )

    assert features
    assert features[0]["geometry"]["type"] == "LineString"
    assert features[0]["properties"]["geometry_role"] == "axis"
