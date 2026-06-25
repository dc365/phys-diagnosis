from __future__ import annotations

import numpy as np

from weather_diag.features.trough_ridge import trough_ridge_axis_candidates


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
