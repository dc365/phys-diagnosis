from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_layers import load_nafp_layer
from weather_diag.diagnosis.point import _sample_value, diagnose_nafp_point


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    return body


def chain_by_type(result: dict, target_type: str) -> dict:
    return next(chain for chain in result["evidence_chains"] if chain["target_type"] == target_type)


def evidence_by_entry(chain: dict, entry_id: str) -> dict:
    return next(item for item in chain["evidence"] if item["entry_id"] == entry_id)


def test_diagnose_nafp_point_returns_scores_and_point_evidence_chain():
    result = diagnose_nafp_point(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
        lat=30.21,
        lon=120.63,
    )

    assert result["run_time"] == "2026-06-17T20:00:00"
    assert result["forecast_hour"] == 24
    assert result["valid_time"] == "2026-06-18T20:00:00"
    assert result["point"]["requested"] == {"lat": 30.21, "lon": 120.63}
    assert result["point"]["sample_method"] == "nearest_grid_point"
    assert result["point"]["nearest_grid_point"]["lat_index"] >= 0
    assert result["point"]["nearest_grid_point"]["lon_index"] >= 0
    assert result["point"]["nearest_grid_point"]["distance_degrees"] >= 0
    assert result["scores"]

    heavy_rain = chain_by_type(result, "heavy_rain_potential")
    assert heavy_rain["score"] == round(sum(item["contribution"] for item in heavy_rain["evidence"]), 3)
    assert heavy_rain["dominant_evidence"]

    q850 = evidence_by_entry(heavy_rain, "heavy_rain.q850")
    assert q850["field"] == "q850"
    assert q850["statistic"] == "point"
    assert q850["rule_statistic"] == "p75"
    assert q850["sample_method"] == "nearest_grid_point"
    assert q850["sample_point"]["lat"] == result["point"]["nearest_grid_point"]["lat"]
    assert q850["raw_value"] >= 0
    assert 0 <= q850["normalized_score"] <= 1
    assert q850["weight"] == 0.18
    assert q850["source_path"].endswith("/q/850/2026/06/17/20/26061720.024")

    assert {score["target_type"] for score in result["scores"]} >= {
        "heavy_rain_potential",
        "convection_potential",
        "dynamic_lift_potential",
        "precipitation_phase",
    }
    assert result["diagnosis_conclusions"]
    assert "summary" in result and "点位" in result["summary"]


def test_nafp_point_returns_multi_hazard_scores():
    result = diagnose_nafp_point(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
        lat=30.21,
        lon=120.63,
    )

    diagnoses = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    assert {"persistent_heavy_rain", "hail"} <= set(diagnoses)

    heavy_chain = chain_by_type(result, "heavy_rain_potential")
    persistent = diagnoses["persistent_heavy_rain"]
    assert persistent["risk_id"] == "point-risk-persistent_heavy_rain"
    assert persistent["risk_domain"] == ["precipitation"]
    assert persistent["label"] == "持续性强降水"
    assert persistent["risk_level"]
    assert "level" in persistent
    assert "sample_point" in persistent
    assert persistent["source_chain_ids"] == ["heavy_rain_potential"]
    assert persistent["dominant_evidence"] == heavy_chain["dominant_evidence"]
    assert "region" not in persistent
    assert "geometry" not in persistent

    convection_chain = chain_by_type(result, "convection_potential")
    hail = diagnoses["hail"]
    assert hail["risk_id"] == "point-risk-hail"
    assert hail["risk_domain"] == ["severe_convection"]
    assert hail["label"] == "冰雹"
    assert hail["risk_level"]
    assert "level" in hail
    assert "sample_point" in hail
    assert hail["source_chain_ids"] == ["convection_potential"]
    assert hail["dominant_evidence"] == convection_chain["dominant_evidence"]


def test_nafp_point_risk_score_uses_hazard_source_grid_sample():
    lat = 30.21
    lon = 120.63
    result = diagnose_nafp_point(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
        lat=lat,
        lon=lon,
    )

    diagnoses = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    hail = diagnoses["hail"]
    layer = load_nafp_layer(
        hail["source_grid"],
        root=NAFP_SAMPLE_ROOT,
        run_time=result["run_time"],
        forecast_hour=result["forecast_hour"],
    )
    expected, sample_point = _sample_value(layer["values"], layer["lat"], layer["lon"], lat, lon)
    assert expected is not None

    convection_chain = chain_by_type(result, "convection_potential")
    assert hail["score"] == round(float(expected), 3)
    assert hail["risk_level"] == hail["level"]
    assert hail["sample_method"] == "nearest_grid_point"
    assert hail["sample_point"] == sample_point
    assert hail["score"] != convection_chain["score"]


def test_nafp_point_api_accepts_lat_lon_and_data_code():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/point",
        json={
            "data_code": "NAFP_ECTHIN_NEW_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "lat": 30.21,
            "lon": 120.63,
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["data"]["point"]["requested"] == {"lat": 30.21, "lon": 120.63}
    assert body["data"]["scores"]
    assert body["data"]["evidence_chains"]

    convection = chain_by_type(body["data"], "convection_potential")
    cape = evidence_by_entry(convection, "convection.cape")
    assert cape["statistic"] == "point"
    assert cape["threshold"] == 0.0
    assert "source_path" in cape
