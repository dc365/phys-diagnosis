from __future__ import annotations

import numpy as np

from weather_diag.features.contour_trough import detect_contour_seeded_troughs
from weather_diag.features.trough_ridge import detect_trough_ridge


def _synthetic_height_field() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lat = np.arange(5.0, 56.0, 1.0)
    lon = np.arange(50.0, 161.0, 1.0)
    lon2d, lat2d = np.meshgrid(lon, lat)
    field = 5900.0 - 5.8 * (lat2d - 20.0)

    northeast_axis_1 = 118.0 + 3.0 * np.sin((lat2d - 30.0) / 15.0 * np.pi)
    northeast_axis_2 = 132.0 + 2.0 * np.sin((lat2d - 40.0) / 12.0 * np.pi)
    hainan_axis = 109.0 + 1.5 * np.sin((lat2d - 15.0) / 12.0 * np.pi)

    field -= 55.0 * np.exp(-((lon2d - northeast_axis_1) / 2.2) ** 2) * np.exp(
        -((lat2d - 38.0) / 12.0) ** 4
    )
    field -= 48.0 * np.exp(-((lon2d - northeast_axis_2) / 2.0) ** 2) * np.exp(
        -((lat2d - 46.0) / 9.0) ** 4
    )
    field -= 28.0 * np.exp(-((lon2d - hainan_axis) / 2.0) ** 2) * np.exp(
        -((lat2d - 22.0) / 9.0) ** 4
    )
    return field, lat, lon


def test_contour_seeded_troughs_split_nearby_northeast_axes():
    field, lat, lon = _synthetic_height_field()
    features = detect_contour_seeded_troughs(field, lat, lon)

    northeast = [
        feature
        for feature in features
        if feature["properties"]["seed_lat"] >= 32.0
        and feature["properties"]["seed_lon"] >= 112.0
    ]
    assert len(northeast) >= 2

    seed_lons = sorted(feature["properties"]["seed_lon"] for feature in northeast)
    assert seed_lons[-1] - seed_lons[0] >= 8.0
    assert all(feature["properties"]["lon_span"] < 8.0 for feature in northeast)


def test_contour_seeded_trough_detects_hainan_branch_without_wind_field():
    field, lat, lon = _synthetic_height_field()
    features = detect_contour_seeded_troughs(field, lat, lon)

    hainan = []
    for feature in features:
        coords = np.asarray(feature["geometry"]["coordinates"], dtype=float)
        intersects = (
            (coords[:, 0] >= 105.0)
            & (coords[:, 0] <= 114.0)
            & (coords[:, 1] >= 13.0)
            & (coords[:, 1] <= 24.0)
        )
        if np.any(intersects):
            hainan.append(feature)

    assert hainan
    props = hainan[0]["properties"]
    assert props["seed_source"] == "contour_tip_cluster"
    assert props["seed_threshold_method"] == "otsu_between_class_variance"
    assert props["contour_support_count"] >= 2
    assert props["candidate_source"] == "meridional_valley_track"
    assert props["feature_type"] == "trough"


def test_contour_seeded_trough_does_not_promote_plain_zonal_field():
    lat = np.arange(15.0, 56.0, 1.0)
    lon = np.arange(60.0, 151.0, 1.0)
    _, lat2d = np.meshgrid(lon, lat)
    field = 5900.0 - 5.5 * (lat2d - 20.0)

    assert detect_contour_seeded_troughs(field, lat, lon) == []


def test_sounding_opt_in_uses_contour_seeds_and_keeps_shear_separate():
    field, lat, lon = _synthetic_height_field()
    troughs, _ = detect_trough_ridge(
        field,
        lat,
        lon,
        {
            "trough_ridge": {
                "analysis_lat_min": 13.0,
                "analysis_lat_max": 55.0,
                "analysis_lon_min": 60.0,
                "analysis_lon_max": 150.0,
                "smooth_radius_km": 150.0,
                "min_length_km": 320.0,
                "max_lines": 8,
                "output_points": 28,
                "enable_meridional_valley_tracks": True,
                "enable_contour_seeded_troughs": True,
                "detect_ridge": False,
            }
        },
    )

    assert troughs
    assert all(
        item["properties"].get("method_detail")
        == "contour_seeded_valley_axis_v1"
        for item in troughs
    )
    assert all(item["properties"]["feature_type"] == "trough" for item in troughs)
    assert all(item["properties"].get("feature_type") != "shear_line" for item in troughs)
