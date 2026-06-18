import numpy as np

from weather_diag.io.grid_geojson import coordinate_edges, grid_to_geojson


def test_coordinate_edges_uses_midpoints_and_outer_half_steps():
    edges = coordinate_edges(np.array([10.0, 11.0, 13.0]))

    assert np.allclose(edges, [9.5, 10.5, 12.0, 14.0])


def test_grid_to_geojson_returns_cell_polygons_with_values():
    data = np.array([[1.0, np.nan], [3.0, 4.0]])
    fc = grid_to_geojson(
        "rain",
        "降水评分",
        "score",
        data,
        lat=np.array([20.0, 21.0]),
        lon=np.array([100.0, 101.0]),
    )

    assert fc["type"] == "FeatureCollection"
    assert fc["properties"]["title"] == "降水评分"
    assert fc["properties"]["unit"] == "score"
    assert fc["properties"]["min"] == 1.0
    assert fc["properties"]["max"] == 4.0
    assert len(fc["features"]) == 3
    assert fc["features"][0]["properties"]["value"] == 1.0
    assert fc["features"][0]["geometry"]["coordinates"][0] == [
        [99.5, 19.5],
        [100.5, 19.5],
        [100.5, 20.5],
        [99.5, 20.5],
        [99.5, 19.5],
    ]
