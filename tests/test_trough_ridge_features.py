from __future__ import annotations

import numpy as np

from weather_diag.features.trough_ridge import detect_trough_ridge, trough_ridge_axis_candidates


def test_trough_axis_prefers_curved_synoptic_band_over_compact_deep_low():
    lat = np.linspace(20.0, 50.0, 31)
    lon = np.linspace(90.0, 130.0, 41)
    lon2d, lat2d = np.meshgrid(lon, lat)

    curved_axis = 105.0 + 6.0 * np.sin((lat - lat.min()) / (lat.max() - lat.min()) * np.pi)
    synoptic_trough = -80.0 * np.exp(-((lon2d - curved_axis[:, None]) / 2.3) ** 2)
    compact_low = -170.0 * np.exp(-(((lon2d - 126.0) / 1.3) ** 2 + ((lat2d - 35.0) / 3.0) ** 2))
    anomaly = synoptic_trough + compact_low

    candidates = trough_ridge_axis_candidates(
        anomaly,
        lat,
        lon,
        mode="trough",
        percentile=28,
        min_points=18,
        max_lines=1,
    )

    assert candidates
    axis = candidates[0]
    axis_lons = [point[0] for point in axis["coordinates"]]

    assert axis["method"] == "curvature_component_axis"
    assert axis["point_count"] >= 24
    assert axis["curvature_mean"] > 0
    assert max(axis_lons) < 116.0
    assert axis["vorticity_support_mean"] is None


def test_trough_axis_records_positive_vorticity_support_when_available():
    lat = np.linspace(20.0, 42.0, 23)
    lon = np.linspace(90.0, 118.0, 29)
    lon2d, _ = np.meshgrid(lon, lat)
    axis_lon = 102.0 + 4.0 * np.sin(np.linspace(0.0, np.pi, lat.size))
    anomaly = -70.0 * np.exp(-((lon2d - axis_lon[:, None]) / 2.5) ** 2)
    vorticity = 2.5e-5 * np.exp(-((lon2d - axis_lon[:, None]) / 3.5) ** 2)

    candidates = trough_ridge_axis_candidates(
        anomaly,
        lat,
        lon,
        mode="trough",
        percentile=25,
        min_points=10,
        max_lines=1,
        vorticity=vorticity,
    )

    assert candidates
    assert candidates[0]["vorticity_support_mean"] > 0


def test_trough_axis_snaps_to_local_height_minimum_and_returns_smooth_line():
    lat = np.linspace(20.0, 50.0, 31)
    lon = np.linspace(90.0, 130.0, 41)
    lon2d, _ = np.meshgrid(lon, lat)
    true_axis_lon = 107.0 + 4.0 * np.sin((lat - lat.min()) / (lat.max() - lat.min()) * np.pi)

    sharp_trough = -95.0 * np.exp(-((lon2d - true_axis_lon[:, None]) / 1.6) ** 2)
    broad_western_shoulder = -35.0 * np.exp(-((lon2d - (true_axis_lon[:, None] - 4.0)) / 4.0) ** 2)
    weak_eastern_shoulder = -10.0 * np.exp(-((lon2d - (true_axis_lon[:, None] + 6.0)) / 5.0) ** 2)
    anomaly = sharp_trough + broad_western_shoulder + weak_eastern_shoulder

    candidates = trough_ridge_axis_candidates(
        anomaly,
        lat,
        lon,
        mode="trough",
        percentile=35,
        min_points=12,
        max_lines=1,
    )

    assert candidates
    axis = candidates[0]
    errors = [point[0] - np.interp(point[1], lat, true_axis_lon) for point in axis["coordinates"]]

    assert len(axis["coordinates"]) >= 30
    assert np.nanmean(np.abs(errors)) < 1.0
    assert np.nanmax(np.abs(errors)) < 1.6


def test_trough_detection_honors_longitude_analysis_domain_before_ranking():
    lat = np.linspace(20.0, 52.0, 65)
    lon = np.linspace(50.0, 160.0, 111)
    lon2d, lat2d = np.meshgrid(lon, lat)

    background = 5900.0 - 5.0 * (lat2d - 20.0)
    axis_lon = 104.0 + 2.0 * np.sin((lat2d - 24.0) / 22.0 * np.pi)
    china_trough = -48.0 * np.exp(-((lon2d - axis_lon) / 1.8) ** 2) * np.exp(-((lat2d - 35.0) / 14.0) ** 4)
    stronger_outside_low = -180.0 * np.exp(-(((lon2d - 151.0) / 3.5) ** 2 + ((lat2d - 42.0) / 4.0) ** 2))

    troughs, _ = detect_trough_ridge(
        background + china_trough + stronger_outside_low,
        lat,
        lon,
        {
            "trough_ridge": {
                "analysis_lat_min": 20.0,
                "analysis_lat_max": 52.0,
                "analysis_lon_min": 75.0,
                "analysis_lon_max": 135.0,
                "smooth_radius_km": 160.0,
                "second_smooth_radius_km": 70.0,
                "component_percentile": 78.0,
                "seed_percentile": 88.0,
                "min_points_per_line": 5,
                "min_length_km": 350.0,
                "max_lines": 1,
                "output_points": 24,
                "detect_ridge": False,
            }
        },
    )

    assert troughs
    coordinates = np.asarray(troughs[0]["geometry"]["coordinates"], dtype=float)
    assert float(np.nanmin(coordinates[:, 0])) >= 75.0
    assert float(np.nanmax(coordinates[:, 0])) <= 135.0
