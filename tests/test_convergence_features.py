from __future__ import annotations

import numpy as np

from weather_diag.features.convergence import detect_low_level_convergence, detect_upper_divergence


def _grid():
    lat = np.linspace(20.0, 45.0, 51)
    lon = np.linspace(100.0, 130.0, 61)
    return lat, lon, np.meshgrid(lon, lat)


def test_low_level_convergence_limits_to_strongest_smoothed_objects():
    lat, lon, (lon2d, lat2d) = _grid()
    div850 = np.full_like(lon2d, 2.0e-6, dtype=float)
    for center_lon, center_lat, scale in [
        (108.0, 28.0, 2.8e-5),
        (119.0, 35.0, 2.4e-5),
        (125.0, 41.0, 1.9e-5),
    ]:
        div850 -= scale * np.exp(-(((lon2d - center_lon) / 2.0) ** 2 + ((lat2d - center_lat) / 2.0) ** 2))
    div850[5, 5] = -8.0e-5

    features = detect_low_level_convergence(
        div850,
        lat,
        lon,
        {
            "convergence": {
                "divergence_percentile": 20,
                "smoothing_sigma_grid": 1.0,
                "min_area_grid_points": 8,
                "max_objects": 2,
            }
        },
    )

    assert len(features) == 2
    assert [feature["properties"]["rank"] for feature in features] == [1, 2]
    assert all(feature["properties"]["point_count"] > 8 for feature in features)


def test_upper_divergence_requires_positive_support_after_smoothing():
    lat, lon, (lon2d, lat2d) = _grid()
    div300 = np.full_like(lon2d, -1.0e-6, dtype=float)
    div300 += 2.8e-5 * np.exp(-(((lon2d - 116.0) / 2.3) ** 2 + ((lat2d - 33.0) / 2.0) ** 2))
    div300[2, 2] = 9.0e-5

    features = detect_upper_divergence(
        div300,
        lat,
        lon,
        {
            "upper_divergence": {
                "divergence_percentile": 80,
                "smoothing_sigma_grid": 1.0,
                "min_area_grid_points": 8,
                "max_objects": 1,
            }
        },
        300,
    )

    assert len(features) == 1
    feature = features[0]
    assert feature["properties"]["rank"] == 1
    assert feature["properties"]["mean_smoothed_divergence"] > 0
