from __future__ import annotations

import importlib

import numpy as np
import xarray as xr
from fastapi.testclient import TestClient

import backend.app.main as main
from backend.app.main import app


client = TestClient(app)


def test_contours_to_geojson_generates_line_segments_from_grid_crossing():
    contours = importlib.import_module("weather_diag.io.contours")
    data = np.array([[0.0, 2.0], [0.0, 2.0]])
    lat = np.array([0.0, 1.0])
    lon = np.array([100.0, 101.0])

    result = contours.contours_to_geojson(
        "mslp",
        "海平面气压",
        "hPa",
        data,
        lat=lat,
        lon=lon,
        levels=[1.0],
    )

    assert result["type"] == "FeatureCollection"
    assert result["properties"]["layer_id"] == "mslp"
    assert result["properties"]["levels"] == [1.0]
    assert len(result["features"]) == 1
    feature = result["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["properties"]["value"] == 1.0
    assert feature["properties"]["value_text"] == "1 hPa"
    assert sorted(feature["geometry"]["coordinates"], key=lambda item: item[1]) == [[100.5, 0.0], [100.5, 1.0]]


def test_risk_contour_value_text_omits_score_range_unit():
    contours = importlib.import_module("weather_diag.io.contours")
    data = np.array([[0.0, 1.0], [0.0, 1.0]])
    lat = np.array([0.0, 1.0])
    lon = np.array([100.0, 101.0])

    result = contours.contours_to_geojson(
        "risk_short_duration_heavy_rain_score",
        "短时强降水风险评分",
        "0-1",
        data,
        lat=lat,
        lon=lon,
        levels=[0.5],
    )

    feature = result["features"][0]
    assert feature["properties"]["unit"] == "0-1"
    assert feature["properties"]["value"] == 0.5
    assert feature["properties"]["value_text"] == "0.50"


def test_contours_to_geojson_merges_cell_segments_into_continuous_lines():
    contours = importlib.import_module("weather_diag.io.contours")
    data = np.array([
        [0.0, 2.0, 4.0],
        [0.0, 2.0, 4.0],
        [0.0, 2.0, 4.0],
    ])
    lat = np.array([0.0, 1.0, 2.0])
    lon = np.array([100.0, 101.0, 102.0])

    result = contours.contours_to_geojson(
        "z500",
        "500hPa 位势高度",
        "dagpm",
        data,
        lat=lat,
        lon=lon,
        levels=[1.0],
    )

    assert len(result["features"]) == 1
    line = result["features"][0]["geometry"]
    assert line["type"] == "LineString"
    assert len(line["coordinates"]) >= 3


def test_layer_contours_endpoint_returns_configured_isobars(monkeypatch):
    ds = xr.Dataset(
        data_vars={"mslp": (("lat", "lon"), np.array([[1000.0, 1004.0], [1000.0, 1004.0]]))},
        coords={"lat": np.array([0.0, 1.0]), "lon": np.array([100.0, 101.0])},
    )
    monkeypatch.setattr(main, "load_diagnostics", lambda run_id, forecast_hour: ds)
    monkeypatch.setattr(
        main,
        "load_layers",
        lambda: {
            "mslp": {
                "title": "海平面气压",
                "variable": "mslp",
                "unit": "hPa",
                "contour": {"enabled": True, "levels": [1002]},
            }
        },
    )

    response = client.get("/api/layers/mslp/contours?run_id=demo&forecast_hour=24")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["properties"]["layer_id"] == "mslp"
    assert body["properties"]["levels"] == [1002.0]
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["value_text"] == "1002 hPa"
