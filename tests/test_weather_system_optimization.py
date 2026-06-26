from __future__ import annotations

import numpy as np

from weather_diag.features.subtropical_high import detect_subtropical_high
from weather_diag.features.upper_jet import detect_upper_jet
from weather_diag.features.vortex import detect_cold_vortex


def test_subtropical_high_auto_unit_accepts_dagpm():
    lat = np.linspace(15.0, 35.0, 21)
    lon = np.linspace(100.0, 130.0, 31)
    lon2d, lat2d = np.meshgrid(lon, lat)
    z = 586.0 + 8.0 * np.exp(-(((lon2d - 118.0) / 8.0) ** 2 + ((lat2d - 24.0) / 4.0) ** 2))
    features = detect_subtropical_high(z, lat, lon, {"subtropical_high": {"auto_unit": True, "min_area_grid_points": 4}})
    assert features
    assert features[0]["properties"]["height_unit"] == "dagpm"
    assert features[0]["properties"]["contour_value"] == 588.0


def test_vortex_detector_returns_cold_vortex_point():
    lat = np.linspace(30.0, 50.0, 61)
    lon = np.linspace(105.0, 130.0, 71)
    lon2d, lat2d = np.meshgrid(lon, lat)
    r2 = ((lon2d - 118.0) / 5.0) ** 2 + ((lat2d - 40.0) / 4.0) ** 2
    z = 5600.0 + 2.0 * (lat2d - 40.0) - 120.0 * np.exp(-r2)
    t = -12.0 - 6.0 * np.exp(-r2)
    # A simple cyclonic wind pattern around the center.
    u = -(lat2d - 40.0) * 1.2
    v = (lon2d - 118.0) * 1.2
    features = detect_cold_vortex(
        z,
        lat,
        lon,
        {"vortex": {"min_height_prominence": 1, "closed_height_interval": 1, "min_closed_area_km2": 1000, "vorticity_min": 1.0e-8}},
        u=u,
        v=v,
        temperature=t,
        level=500,
    )
    assert features
    assert features[0]["geometry"]["type"] == "Point"
    assert features[0]["properties"]["feature_type"] in {"cold_vortex", "mid_level_vortex"}


def test_vortex_detector_uses_dagpm_thresholds_for_dagpm_height():
    lat = np.linspace(30.0, 50.0, 61)
    lon = np.linspace(105.0, 130.0, 71)
    lon2d, lat2d = np.meshgrid(lon, lat)
    r2 = ((lon2d - 118.0) / 5.0) ** 2 + ((lat2d - 40.0) / 4.0) ** 2
    z_dagpm = (5600.0 + 2.0 * (lat2d - 40.0) - 120.0 * np.exp(-r2)) / 10.0
    u = -(lat2d - 40.0) * 1.2
    v = (lon2d - 118.0) * 1.2

    features = detect_cold_vortex(
        z_dagpm,
        lat,
        lon,
        {"vortex": {"min_height_prominence": 2, "closed_height_interval": 2, "min_closed_area_km2": 1000, "vorticity_min": 1.0e-8}},
        u=u,
        v=v,
        level=500,
    )

    assert features
    assert features[0]["properties"]["height_unit"] == "dagpm"


def test_upper_jet_returns_axis_linestring():
    lat = np.linspace(20.0, 50.0, 61)
    lon = np.linspace(90.0, 140.0, 101)
    _, lat2d = np.meshgrid(lon, lat)
    u = 20.0 + 35.0 * np.exp(-((lat2d - 35.0) / 3.0) ** 2)
    v = np.zeros_like(u)
    features = detect_upper_jet(
        u,
        v,
        lat,
        lon,
        {"upper_jet": {"wind_speed_min_ms": 25, "wind_speed_percentile": 70, "min_area_grid_points": 6, "max_objects": 2}},
        level=200,
    )
    assert features
    assert all(feature["geometry"]["type"] == "LineString" for feature in features)
