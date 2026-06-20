from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.diagnosis.nafp_layers import load_nafp_layer


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert body["code"] == 0
    return body["data"]


def test_load_nafp_layer_reads_configured_height_field():
    layer = load_nafp_layer(
        "z500",
        data_code="NAFP_ECTHIN_NEW_NC",
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert layer["layer_id"] == "z500"
    assert layer["title"] == "500hPa 位势高度"
    assert layer["unit"] == "gpm"
    assert layer["values"].shape == (241, 361)
    assert float(layer["max"]) > 5000.0
    assert layer["lat"].shape == (241,)
    assert layer["lon"].shape == (361,)
    assert layer["source_paths"][0].endswith("/gh/500/2026/06/17/20/26061720.024")


def test_load_nafp_layer_derives_heavy_rain_score_from_raw_fields():
    layer = load_nafp_layer(
        "heavy_rain_score",
        data_code="NAFP_ECTHIN_NEW_NC",
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert layer["title"] == "强降水潜势评分"
    assert layer["unit"] == "score"
    assert layer["values"].shape == (241, 361)
    assert 0.0 <= float(layer["min"]) <= float(layer["max"]) <= 1.0
    assert any("/q/850/" in path for path in layer["source_paths"])
    assert any("/uv/850/" in path for path in layer["source_paths"])


def test_nafp_layers_include_multi_hazard_risk_scores():
    layer = load_nafp_layer(
        "risk_short_duration_heavy_rain_score",
        data_code="NAFP_ECTHIN_NEW_NC",
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert layer["layer_id"] == "risk_short_duration_heavy_rain_score"
    assert layer["unit"] == "0-1"
    assert layer["values"].shape == (241, 361)
    assert 0.0 <= float(layer["min"]) <= float(layer["max"]) <= 1.0
    assert any("/q/850/" in path or "/uv/850/" in path for path in layer["source_paths"])

    response = client.get(
        "/api/v1/diagnosis/nafp/layers/risk_short_duration_heavy_rain_score/metadata",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["layer_id"] == "risk_short_duration_heavy_rain_score"
    assert data["unit"] == "0-1"


def test_nafp_layer_metadata_endpoint_returns_enveloped_bounds():
    response = client.get(
        "/api/v1/diagnosis/nafp/layers/z500/metadata",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["layer_id"] == "z500"
    assert data["data_code"] == "NAFP_ECTHIN_NEW_NC"
    assert data["run_time"] == "2026-06-17T20:00:00"
    assert data["forecast_hour"] == 24
    assert data["lat_min"] == 0.0
    assert data["lat_max"] == 60.0
    assert data["lon_min"] == 60.0
    assert data["lon_max"] == 150.0


def test_nafp_layer_grid_endpoint_returns_sampled_geojson():
    response = client.get(
        "/api/v1/diagnosis/nafp/layers/t850/grid",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "max_cells": 500,
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["type"] == "FeatureCollection"
    assert data["properties"]["layer_id"] == "t850"
    assert data["properties"]["count"] <= 500
    assert data["features"][0]["geometry"]["type"] == "Polygon"
    assert "value" in data["features"][0]["properties"]


def test_nafp_layer_contours_endpoint_labels_values():
    response = client.get(
        "/api/v1/diagnosis/nafp/layers/mslp/contours",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "max_segments": 300,
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["type"] == "FeatureCollection"
    assert data["properties"]["layer_id"] == "mslp"
    assert data["features"]
    assert data["features"][0]["properties"]["value_text"].endswith(" hPa")
