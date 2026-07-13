from __future__ import annotations

from pathlib import Path

import numpy as np

from weather_diag.features.sounding_geometry_refine import (
    _branch_axis_from_tips,
    polyline_roughness,
    smooth_shear_systems,
)


SOUNDING_FILE = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625/"
    "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv"
)


def test_closed_low_branch_connects_a_z500_contour_tip_family():
    system = {
        "candidate_source": "closed_low_north_branch",
        "closed_low_center": [126.0, 40.0],
        "geometry": {
            "type": "line",
            "coordinates": [[126.0, 40.0], [126.0, 49.0]],
        },
    }
    tips = [
        {
            "level": 5680.0,
            "score": 0.4,
            "prominence_deg": 0.35,
            "lon": 137.0,
            "lat": 45.8,
        },
        {
            "level": 5640.0,
            "score": 0.5,
            "prominence_deg": 0.48,
            "lon": 137.2,
            "lat": 48.4,
        },
    ]

    axis, accepted = _branch_axis_from_tips(
        system,
        center_height=5716.0,
        interval=40.0,
        tips=tips,
    )

    assert axis is not None
    assert len(accepted) == 2
    assert float(np.nanmax(axis[:, 0])) >= 136.5
    assert np.all(np.diff(axis[:, 1]) > 0.0)
    assert np.allclose(axis[0], [126.0, 40.0], atol=0.15)


def test_shear_axis_smoothing_removes_grid_zigzags():
    latitude = np.arange(15.0, 31.0)
    longitude = 108.0 + np.asarray(
        [0.0, 1.0, -0.8, 0.9, -1.0, 0.7, -0.5, 0.8, -0.7, 0.6, -0.5, 0.5, -0.4, 0.3, -0.2, 0.0]
    )
    coordinates = np.column_stack([longitude, latitude])
    system = {
        "id": "synthetic-shear",
        "feature_type": "shear_line",
        "geometry": {"type": "line", "coordinates": coordinates.tolist()},
        "evidence": [],
    }

    smoothed = smooth_shear_systems([system])[0]
    output = np.asarray(smoothed["geometry"]["coordinates"], dtype=float)

    assert smoothed["display_smoothing"] == "arc_length_median_gaussian_v5"
    assert output.shape[0] >= 8
    assert polyline_roughness(output) < 0.40 * polyline_roughness(coordinates)
    assert np.allclose(output[0], coordinates[0], atol=0.08)
    assert np.allclose(output[-1], coordinates[-1], atol=0.08)


def test_real_25_20_northeast_branch_follows_z500_contour_tips():
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)
    north = next(
        item
        for item in result["systems"]
        if item.get("candidate_source") == "closed_low_north_branch"
    )
    coordinates = np.asarray(north["geometry"]["coordinates"], dtype=float)
    center = np.asarray(north["closed_low_center"], dtype=float)

    assert north["method"] == "sounding_multitrack_axis_v4"
    assert north["method_detail"] == "equatorward_z500_contour_tip_family_v5"
    assert north["geometry_refinement_version"] == "sounding_z500_geometry_v5"
    assert north["path_metrics"]["contour_tip_level_count"] >= 2
    assert set(north["contour_tip_levels"]) >= {5640.0, 5680.0}
    assert float(np.nanmax(coordinates[:, 0])) >= float(center[0]) + 8.0
    assert float(np.nanmax(coordinates[:, 1])) >= 47.0
