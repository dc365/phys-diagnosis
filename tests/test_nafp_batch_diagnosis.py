from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.v1.diagnosis import _subtropical_high_trend
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    return body


def test_nafp_batch_diagnosis_generates_multiple_forecast_hours():
    response = client.post(
        "/api/v1/diagnosis/nafp/situations",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [0, 24],
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["run_time"] == "2026-06-17T20:00:00"
    assert data["forecast_hours"] == [0, 24]
    assert data["result_count"] == 2
    assert data["failed_count"] == 0
    assert [item["forecast_hour"] for item in data["results"]] == [0, 24]
    assert data["results"][0]["systems"]
    assert data["results"][1]["evidence_chains"]


def test_nafp_batch_diagnosis_reports_subtropical_high_trend():
    response = client.post(
        "/api/v1/diagnosis/nafp/situations",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [0, 24],
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    trend = data["subtropical_high_trend"]

    assert trend["system_type"] == "subtropical_high"
    assert trend["baseline_forecast_hour"] == 0
    assert trend["target_forecast_hour"] == 24
    assert len(trend["samples"]) == 2
    assert {sample["forecast_hour"] for sample in trend["samples"]} == {0, 24}
    assert trend["west_extension"]["direction"] in {"westward", "eastward", "stable", "unknown"}
    assert trend["north_shift"]["direction"] in {"northward", "southward", "stable", "unknown"}
    assert trend["area_change"]["direction"] in {"expanding", "shrinking", "stable", "unknown"}
    assert trend["intensity_change"]["direction"] in {"strengthening", "weakening", "stable", "unknown"}
    assert trend["trend_summary"]
    assert "副高" in trend["trend_summary"]


def test_nafp_batch_diagnosis_reports_weather_situation_evolution_panel():
    response = client.post(
        "/api/v1/diagnosis/nafp/situations",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [0, 24],
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    evolution = data["situation_evolution"]

    assert evolution["baseline_forecast_hour"] == 0
    assert evolution["target_forecast_hour"] == 24
    assert "天气形势" in evolution["trend_summary"]
    items = {item["system_type"]: item for item in evolution["items"]}
    assert {
        "subtropical_high",
        "trough_candidate",
        "ridge_candidate",
        "low_level_jet",
        "moisture_transport",
    } <= set(items)
    assert items["subtropical_high"]["trend_summary"] == data["subtropical_high_trend"]["trend_summary"]

    for system_type in ["trough_candidate", "ridge_candidate", "low_level_jet", "moisture_transport"]:
        item = items[system_type]
        assert item["available"] is True
        assert item["geometry_role"] == "line"
        assert len(item["samples"]) == 2
        assert {sample["forecast_hour"] for sample in item["samples"]} == {0, 24}
        assert all(sample["object_count"] >= 1 for sample in item["samples"])
        assert item["position_change"]["east_west"]["direction"] in {"eastward", "westward", "stable", "unknown"}
        assert item["position_change"]["north_south"]["direction"] in {"northward", "southward", "stable", "unknown"}
        assert item["count_change"]["direction"] in {"increasing", "decreasing", "stable", "unknown"}
        assert item["length_change"]["direction"] in {"lengthening", "shortening", "stable", "unknown"}
        assert item["confidence_change"]["direction"] in {"strengthening", "weakening", "stable", "unknown"}
        assert item["trend_summary"]
        assert item["label"] in item["trend_summary"]


def test_subtropical_high_trend_skips_incomplete_metric_samples():
    trend = _subtropical_high_trend(
        [
            {
                "forecast_hour": 0,
                "systems": [
                    {
                        "type": "subtropical_high",
                        "ridge_point": {"lon": 120.0, "lat": 25.0},
                        "north_boundary_lat": 30.0,
                        "area_grid_points": 100,
                    }
                ],
            },
            {
                "forecast_hour": 24,
                "systems": [
                    {
                        "type": "subtropical_high",
                        "ridge_point": {"lon": 118.0, "lat": 26.0},
                        "north_boundary_lat": 31.0,
                        "area_grid_points": 110,
                        "mean_height": 5890.0,
                    }
                ],
            },
        ]
    )

    assert trend["available"] is False
    assert len(trend["samples"]) == 1
    assert trend["samples"][0]["forecast_hour"] == 24
    assert trend["trend_summary"] == "副高时效演变样本不足。"


def test_nafp_batch_diagnosis_accepts_configured_data_code():
    response = client.post(
        "/api/v1/diagnosis/nafp/situations",
        json={
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24, 24, 0],
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    data = body["data"]
    assert data["forecast_hours"] == [24, 0]
    assert data["result_count"] == 2
    assert data["failed_count"] == 0


def test_nafp_batch_diagnosis_rejects_empty_forecast_hours():
    response = client.post(
        "/api/v1/diagnosis/nafp/situations",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [],
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40001
    assert body["msg"] == "forecast_hours is required"
