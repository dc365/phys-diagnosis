from __future__ import annotations

import numpy as np

from weather_diag.features.shear_line import detect_shear_lines, shear_line_fields


def _synthetic_shear_line():
    lat = np.linspace(25.0, 45.0, 81)
    lon = np.linspace(100.0, 125.0, 101)
    lon2d, lat2d = np.meshgrid(lon, lat)
    # Opposite zonal flow on the two sides of 35N creates a cyclonic shear and
    # convergence-like transition belt.
    u = -8.0 * np.tanh((lat2d - 35.0) / 0.9)
    v = 1.5 * np.exp(-((lat2d - 35.0) / 1.8) ** 2)
    q = 12.0 + 2.0 * np.exp(-((lat2d - 35.0) / 2.0) ** 2)
    return lat, lon, u, v, q


def test_shear_line_fields_identify_dynamic_belt():
    lat, lon, u, v, q = _synthetic_shear_line()
    derived = shear_line_fields(
        u,
        v,
        lat,
        lon,
        {
            "shear_line": {
                "score_percentile": 70,
                "dynamic_percentile": 60,
                "vorticity_min": 1.0e-8,
                "convergence_min": 0.0,
                "min_support_components": 1,
            }
        },
        moisture=q,
    )
    assert derived["mask"].sum() > 0
    assert np.nanmax(derived["positive_vorticity"]) > 0
    assert np.nanmax(derived["shear_deformation"]) > 0


def test_detect_shear_lines_returns_linestring_features():
    lat, lon, u, v, q = _synthetic_shear_line()
    features = detect_shear_lines(
        u,
        v,
        lat,
        lon,
        {
            "shear_line": {
                "score_percentile": 70,
                "dynamic_percentile": 60,
                "vorticity_min": 1.0e-8,
                "convergence_min": 0.0,
                "min_support_components": 1,
                "min_area_grid_points": 8,
                "min_length_km": 200,
                "max_objects": 2,
            }
        },
        level=850,
        moisture=q,
    )
    assert features
    assert all(feature["geometry"]["type"] == "LineString" for feature in features)
    assert features[0]["properties"]["feature_type"] in {"shear_line", "front_with_shear"}
    assert features[0]["properties"]["axis_length_km"] >= 200
