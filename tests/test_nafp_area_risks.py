from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT


client = TestClient(app)
PRIVATE_PATH_KEYS = {"data_dir", "file_path", "path", "root", "source_file", "source_path", "source_paths", "stored_path"}


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    return body


def assert_no_private_paths(value):
    if isinstance(value, dict):
        assert not (PRIVATE_PATH_KEYS & set(value))
        for item in value.values():
            assert_no_private_paths(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_private_paths(item)


def test_nafp_area_risks_returns_town_risk_with_metadata_and_evidence():
    response = client.get(
        "/api/v1/diagnosis/nafp/area-risks",
        params={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "town_code": "350203005",
            "forecast_hour_start": 24,
            "forecast_hour_end": 24,
            "risk_type": "short_duration_heavy_rain",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    assert_no_private_paths(data)
    metadata = data["risk_metadata"]["short_duration_heavy_rain"]
    assert metadata["hazard_type"] == "short_duration_heavy_rain"
    assert metadata["label"] == "短时强降水"
    assert metadata["description"]
    assert metadata["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert metadata["score_range"] == [0, 1]
    assert metadata["score_unit"] == "risk_score"

    assert data["scope"] == {
        "type": "town",
        "town_code": "350203005",
        "region_code": None,
        "region_level": None,
    }
    assert data["forecast_hours"] == [24]
    assert data["risk_types"] == ["short_duration_heavy_rain"]
    assert data["failed"] == []
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["area"]["town_code"] == "350203005"
    assert item["area"]["town_name"] == "滨海街道"
    assert item["forecast_hour"] == 24
    assert item["valid_time"] == "2026-06-18T20:00:00"
    assert len(item["risks"]) == 1

    risk = item["risks"][0]
    assert risk["hazard_type"] == "short_duration_heavy_rain"
    assert risk["metadata"] == metadata
    assert risk["score_source"] == "source_grid"
    assert risk["score_statistic"] == "station_points_max"
    assert 0 <= risk["score"] <= 1
    assert 0 <= risk["mean_score"] <= 1
    assert risk["sample_count"] == 7
    assert risk["evidence_chain"]["source_grid"] == risk["source_grid"]
    assert risk["evidence_chain"]["sampling_method"] == "station_points"
    assert isinstance(risk["evidence_chain"]["dominant_factors"], list)


def test_nafp_area_catalog_lists_regions_and_towns_for_ui_filters():
    response = client.get("/api/v1/diagnosis/nafp/areas")

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    assert_no_private_paths(data)

    assert data["town_count"] >= 21
    assert data["city_count"] >= 2
    assert "risk_metadata" in data
    assert data["risk_metadata"]["hail"]["label"] == "冰雹"
    assert any(city["city_code"] == "350200" and city["town_count"] >= 7 for city in data["cities"])
    assert any(town["town_code"] == "350203005" and town["town_name"] == "滨海街道" for town in data["towns"])


def test_nafp_area_risks_returns_all_towns_for_region_and_single_risk_type():
    response = client.get(
        "/api/v1/diagnosis/nafp/area-risks",
        params={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "region_code": "350200",
            "region_level": "city",
            "forecast_hour_start": 24,
            "forecast_hour_end": 24,
            "risk_type": "hail",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    assert_no_private_paths(data)

    assert data["scope"]["type"] == "region"
    assert data["scope"]["region_code"] == "350200"
    assert data["risk_types"] == ["hail"]
    assert data["risk_metadata"]["hail"]["label"] == "冰雹"
    assert len(data["items"]) >= 7
    assert {item["area"]["town_code"] for item in data["items"]} >= {"350203005"}
    assert all(len(item["risks"]) == 1 for item in data["items"])
    assert {item["risks"][0]["hazard_type"] for item in data["items"]} == {"hail"}


def test_nafp_area_risks_filters_forecast_hours_by_valid_time_window():
    response = client.get(
        "/api/v1/diagnosis/nafp/area-risks",
        params={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "town_code": "350203005",
            "start_time": "2026-06-18T20:00:00",
            "end_time": "2026-06-18T20:00:00",
            "risk_type": "persistent_heavy_rain",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())["data"]
    assert data["forecast_hours"] == [24]
    assert [item["forecast_hour"] for item in data["items"]] == [24]
    assert data["items"][0]["valid_time"] == "2026-06-18T20:00:00"
