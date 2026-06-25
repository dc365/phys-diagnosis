from __future__ import annotations

import numpy as np

from weather_diag.diagnostics.grid import component_axis_line, mask_to_bbox_features


def _largest_exterior_size(geometry: dict) -> int:
    if geometry["type"] == "Polygon":
        return len(geometry["coordinates"][0])
    if geometry["type"] == "MultiPolygon":
        return max(len(polygon[0]) for polygon in geometry["coordinates"])
    raise AssertionError(f"unexpected geometry type: {geometry['type']}")


def test_mask_features_preserve_l_shaped_polygon_boundary():
    lat = np.array([0.0, 1.0, 2.0])
    lon = np.array([10.0, 11.0, 12.0])
    mask = np.array(
        [
            [True, False, False],
            [True, False, False],
            [True, True, True],
        ]
    )

    features = mask_to_bbox_features(mask, lat, lon, min_points=1)

    assert len(features) == 1
    feature = features[0]
    assert feature["point_count"] == 5
    assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert _largest_exterior_size(feature["geometry"]) > 5


def test_component_axis_line_follows_diagonal_component_shape():
    lat = np.array([0.0, 1.0, 2.0, 3.0])
    lon = np.array([10.0, 11.0, 12.0, 13.0])
    mask = np.array(
        [
            [True, False, False, False],
            [True, True, False, False],
            [False, True, True, False],
            [False, False, True, True],
        ]
    )
    feature = mask_to_bbox_features(mask, lat, lon, min_points=1)[0]

    line = component_axis_line(feature, lat, lon)

    assert line["type"] == "line"
    assert line["bbox"] == feature["bbox"]
    assert len(line["coordinates"]) >= 4
    assert len({round(coord[0], 6) for coord in line["coordinates"]}) > 1
    assert len({round(coord[1], 6) for coord in line["coordinates"]}) > 1
