from __future__ import annotations

import numpy as np

from weather_diag.features.subtropical_high import detect_subtropical_high


def test_detect_subtropical_high_reports_ridge_metrics_without_mvp_evidence():
    lat = np.array([15.0, 20.0, 25.0, 30.0])
    lon = np.array([105.0, 110.0, 115.0, 120.0, 125.0])
    z500 = np.array(
        [
            [5860.0, 5870.0, 5882.0, 5888.0, 5890.0],
            [5870.0, 5884.0, 5892.0, 5900.0, 5896.0],
            [5865.0, 5881.0, 5888.0, 5895.0, 5892.0],
            [5850.0, 5860.0, 5870.0, 5875.0, 5881.0],
        ]
    )

    features = detect_subtropical_high(
        z500,
        lat,
        lon,
        {"subtropical_high": {"contour_gpm": 5880, "min_area_grid_points": 3}},
    )

    assert features
    props = features[0]["properties"]
    assert props["ridge_point"]["lon"] <= props["center"]["lon"]
    assert props["north_boundary_lat"] >= props["south_boundary_lat"]
    assert props["area_grid_points"] >= 3
    assert props["max_height"] >= props["mean_height"] >= props["threshold_height"]
    assert props["axis_orientation"] in {"zonal", "meridional", "compact"}
    assert all("MVP" not in item for item in props["evidence"])
