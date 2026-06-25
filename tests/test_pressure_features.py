from __future__ import annotations

import numpy as np

from weather_diag.features.pressure import detect_high_low


def _gaussian(lon_grid, lat_grid, lon0, lat0, sx, sy):
    return np.exp(-((lon_grid - lon0) / sx) ** 2 - ((lat_grid - lat0) / sy) ** 2)


def test_detect_high_low_requires_closed_isobars_and_keeps_multiple_centers():
    lat = np.linspace(20.0, 50.0, 61)
    lon = np.linspace(80.0, 130.0, 81)
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    mslp = (
        1012.0
        - 11.0 * _gaussian(lon_grid, lat_grid, 102.0, 33.0, 5.0, 4.0)
        - 8.0 * _gaussian(lon_grid, lat_grid, 118.0, 41.0, 4.0, 3.5)
        + 9.0 * _gaussian(lon_grid, lat_grid, 91.0, 43.0, 5.5, 4.5)
        - 9.0 * _gaussian(lon_grid, lat_grid, 80.0, 50.0, 3.0, 3.0)
    )
    thresholds = {
        "pressure_system": {
            "min_distance_grid": 5,
            "max_centers": 10,
            "min_prominence_hpa": 1.5,
            "contour_interval_hpa": 1.0,
            "min_closed_contours": 2,
            "max_closed_contours": 8,
            "edge_margin_grid": 2,
            "smoothing_sigma_grid": 0.0,
        }
    }

    features = detect_high_low(mslp, lat, lon, thresholds)

    highs = [item for item in features if item["properties"]["feature_type"] == "high"]
    lows = [item for item in features if item["properties"]["feature_type"] == "low"]
    assert len(highs) == 1
    assert len(lows) == 2
    assert all(item["properties"]["closed_contour_count"] >= 2 for item in highs + lows)
    assert all(item["properties"]["pressure_difference_hpa"] >= 2.0 for item in highs + lows)
    assert all("闭合等压线" in " ".join(item["properties"]["evidence"]) for item in highs + lows)
    assert all(item["geometry"]["coordinates"][0] > 82.0 for item in lows)


def test_detect_high_low_rejects_open_boundary_extrema():
    lat = np.linspace(20.0, 50.0, 61)
    lon = np.linspace(80.0, 130.0, 81)
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    mslp = 1012.0 - 12.0 * _gaussian(lon_grid, lat_grid, 80.0, 50.0, 4.0, 4.0)
    thresholds = {
        "pressure_system": {
            "min_distance_grid": 5,
            "max_centers": 10,
            "min_prominence_hpa": 1.0,
            "contour_interval_hpa": 1.0,
            "min_closed_contours": 2,
            "max_closed_contours": 8,
            "edge_margin_grid": 1,
            "smoothing_sigma_grid": 0.0,
        }
    }

    features = detect_high_low(mslp, lat, lon, thresholds)

    assert [item for item in features if item["properties"]["feature_type"] == "low"] == []
