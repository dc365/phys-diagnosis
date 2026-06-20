from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_features import nafp_situation_to_feature_collection
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert body["code"] == 0
    return body["data"]


def test_nafp_features_endpoint_returns_filtered_geojson():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "low_pressure_convergence,high_pressure_divergence",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["type"] == "FeatureCollection"
    assert data["properties"]["data_code"] == "NAFP_ECTHIN_NEW_NC"
    assert data["properties"]["run_time"] == "2026-06-17T20:00:00"
    assert data["properties"]["forecast_hour"] == 24
    assert data["properties"]["requested_types"] == [
        "low_pressure_convergence",
        "high_pressure_divergence",
    ]
    feature_types = {feature["properties"]["feature_type"] for feature in data["features"]}
    assert feature_types == {"low_pressure_convergence", "high_pressure_divergence"}
    assert data["properties"]["count"] == len(data["features"])
    assert data["features"][0]["geometry"]["type"] == "Polygon"
    assert data["features"][0]["properties"]["evidence"]
    assert data["features"][0]["properties"]["diagnosis"]


def test_nafp_features_endpoint_returns_all_selected_map_system_types():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "low_level_jet,moisture_transport",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert {feature["geometry"]["type"] for feature in data["features"]} == {"LineString"}
    assert {feature["properties"]["feature_type"] for feature in data["features"]} == {
        "low_level_jet",
        "moisture_transport",
    }


def test_nafp_situation_features_include_hazard_specific_risk_items():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    collection = nafp_situation_to_feature_collection(
        result,
        requested_types=["short_duration_heavy_rain_risk"],
        data_code="NAFP_ECTHIN_NEW_NC",
        root=str(NAFP_SAMPLE_ROOT),
    )

    assert collection["properties"]["count"] >= 1
    feature = collection["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    assert feature["properties"]["hazard_type"] == "short_duration_heavy_rain"
    assert feature["properties"]["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert feature["properties"]["source_chain_ids"] == ["heavy_rain_potential"]


def test_nafp_features_endpoint_returns_filtered_hazard_risk_feature():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "short_duration_heavy_rain_risk",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["properties"]["count"] > 0
    feature = data["features"][0]
    assert feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    assert feature["properties"]["hazard_type"] == "short_duration_heavy_rain"
    assert feature["properties"]["source_grid"] == "risk_short_duration_heavy_rain_score"
