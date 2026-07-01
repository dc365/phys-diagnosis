from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.v1 import diagnosis as diagnosis_api
from backend.app.api.v1 import precompute as precompute_api
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_features import nafp_situation_to_feature_collection
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation
from weather_diag.diagnosis.nafp_situation_integrated import _feature_to_system


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert body["code"] == 0
    return body["data"]


def assert_no_private_paths(value):
    private_keys = {"data_dir", "file_path", "path", "root", "source_file", "source_path", "source_paths", "stored_path"}
    if isinstance(value, dict):
        assert not (private_keys & set(value))
        for item in value.values():
            assert_no_private_paths(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_private_paths(item)


def fake_situation_result(run_time: str, forecast_hour: int) -> dict:
    return {
        "run_time": run_time,
        "forecast_hour": forecast_hour,
        "valid_time": run_time,
        "systems": [
            {
                "id": f"high-{forecast_hour}",
                "type": "high",
                "feature_type": "high",
                "label": "H",
                "name": "高压中心",
                "level": "mslp",
                "confidence": 0.9,
                "primary": True,
                "geometry": {"type": "point", "coordinates": [110.0, 35.0]},
                "evidence": [{"name": "mslp"}],
                "diagnosis": "mock high pressure center",
            }
        ],
        "risk_diagnoses": [],
        "summary": "mock summary",
        "missing_fields": [],
    }


def test_nafp_features_endpoint_returns_filtered_geojson():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "low_pressure_convergence,high_pressure_divergence",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert_no_private_paths(data)
    assert data["type"] == "FeatureCollection"
    assert data["properties"]["data_code"] == "NAFP_ECTHIN_NC"
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


def test_nafp_features_endpoint_reuses_cached_situation_result(monkeypatch, tmp_path):
    calls = []

    def fake_diagnose_nafp_situation(*, root, run_time, forecast_hour):
        calls.append((str(root), run_time, forecast_hour))
        return fake_situation_result(run_time, forecast_hour)

    monkeypatch.setattr(diagnosis_api, "diagnose_nafp_situation", fake_diagnose_nafp_situation)
    params = {
        "root": str(tmp_path),
        "run_time": "2026-06-17T20:00:00",
        "forecast_hour": 24,
        "types": "high",
    }

    first = client.get("/api/v1/diagnosis/nafp/features", params=params)
    second = client.get("/api/v1/diagnosis/nafp/features", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert envelope(first.json())["properties"]["count"] == 1
    assert envelope(second.json())["properties"]["count"] == 1
    assert len(calls) == 1


def test_nafp_precompute_schedules_async_job_for_feature_loading(monkeypatch, tmp_path):
    jobs = []

    def fake_submit_precompute_job(**kwargs):
        jobs.append(kwargs)
        return {"status": "queued", "computed_count": 0, "total_count": 1}

    monkeypatch.setattr(precompute_api, "submit_precompute_job", fake_submit_precompute_job)

    precomputed = client.post(
        "/api/v1/diagnosis/nafp/precompute",
        json={
            "root": str(tmp_path),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24],
        },
    )

    assert precomputed.status_code == 200
    assert envelope(precomputed.json())["status"] == "queued"
    assert jobs == [
        {
            "root": tmp_path,
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24],
            "data_code": None,
            "force": False,
            "background": True,
        }
    ]


def test_precomputed_features_endpoint_computes_when_result_is_missing(monkeypatch, tmp_path):
    loads = []
    jobs = []

    def fake_load_precomputed_result(root, run_time, forecast_hour, data_code=None):
        loads.append((str(root), run_time, forecast_hour, data_code))
        if len(loads) == 1:
            raise FileNotFoundError("missing")
        return fake_situation_result(run_time, forecast_hour)

    def fake_submit_precompute_job(**kwargs):
        jobs.append(kwargs)
        return {"status": "completed", "failed_count": 0}

    monkeypatch.setattr(precompute_api, "load_precomputed_result", fake_load_precomputed_result)
    monkeypatch.setattr(precompute_api, "submit_precompute_job", fake_submit_precompute_job)

    response = client.get(
        "/api/v1/diagnosis/nafp/precompute/features",
        params={
            "root": str(tmp_path),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "high",
        },
    )

    assert response.status_code == 200
    assert envelope(response.json())["properties"]["count"] == 1
    assert len(loads) == 2
    assert jobs == [
        {
            "root": tmp_path,
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24],
            "data_code": None,
            "force": False,
            "background": False,
        }
    ]


def test_nafp_features_endpoint_returns_all_selected_map_system_types():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "trough,ridge,low_level_jet,moisture_transport",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert {feature["geometry"]["type"] for feature in data["features"]} == {"LineString"}
    assert {feature["properties"]["feature_type"] for feature in data["features"]} == {
        "trough",
        "ridge",
        "low_level_jet",
        "moisture_transport",
    }


def test_nafp_features_endpoint_returns_surface_pressure_centers_for_map_toggles():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "types": "high,low",
        },
    )

    assert response.status_code == 200
    data = envelope(response.json())
    assert data["properties"]["requested_types"] == ["high", "low"]
    feature_types = {feature["properties"]["feature_type"] for feature in data["features"]}
    assert {"high", "low"} <= feature_types
    assert {feature["geometry"]["type"] for feature in data["features"]} == {"Point"}
    assert all(feature["properties"]["level"] == "mslp" for feature in data["features"])
    assert_no_private_paths(data)


def test_nafp_situation_features_include_hazard_specific_risk_items():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    collection = nafp_situation_to_feature_collection(
        result,
        requested_types=["short_duration_heavy_rain_risk"],
        data_code="NAFP_ECTHIN_NC",
        root=str(NAFP_SAMPLE_ROOT),
    )

    assert collection["properties"]["count"] >= 1
    feature = collection["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    assert feature["properties"]["hazard_type"] == "short_duration_heavy_rain"
    assert feature["properties"]["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert feature["properties"]["source_chain_ids"] == []
    assert feature["properties"]["region_source"] == "source_grid"


def test_nafp_feature_request_maps_front_with_shear_to_shear_line():
    collection = nafp_situation_to_feature_collection(
        {
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "systems": [
                {
                    "id": "front-shear-1",
                    "type": "front_with_shear",
                    "feature_type": "front_with_shear",
                    "name": "锋区切变线",
                    "geometry": {"type": "line", "coordinates": [[110, 25], [112, 27]]},
                }
            ],
        },
        requested_types=["shear_line"],
    )

    feature = collection["features"][0]
    assert feature["properties"]["feature_type"] == "shear_line"
    assert feature["properties"]["source_feature_type"] == "front_with_shear"


def test_integrated_weather_systems_mark_display_groups():
    def system_for(feature_type: str):
        return _feature_to_system(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[110, 25], [112, 27]]},
                "properties": {"id": feature_type, "feature_type": feature_type, "title": feature_type},
            },
            1,
        )

    assert system_for("cold_vortex")["display_group"] == "primary"
    assert system_for("upper_jet")["display_group"] == "support"
    assert system_for("pv_anomaly")["display_group"] == "advanced"
    assert system_for("low_level_convergence_axis")["display_group"] == "debug"
    assert system_for("upper_jet")["map_selectable"] is True
    assert system_for("pv_anomaly")["map_selectable"] is False


def test_nafp_risk_features_hide_background_axis_supports():
    collection = nafp_situation_to_feature_collection(
        {
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
            "risk_diagnoses": [
                {
                    "hazard_type": "short_duration_heavy_rain",
                    "region": {
                        "type": "polygon",
                        "coordinates": [[[110, 25], [111, 25], [111, 26], [110, 26], [110, 25]]],
                    },
                    "supporting_systems": [
                        {"type": "low_level_convergence_axis", "name": "低层辐合轴"},
                        {"type": "low_level_convergence", "name": "低层辐合区"},
                        {"type": "upper_divergence_axis", "name": "高空辐散轴"},
                    ],
                }
            ],
        },
        requested_types=["short_duration_heavy_rain_risk"],
    )

    supports = collection["features"][0]["properties"]["supporting_systems"]
    assert [item["type"] for item in supports] == ["low_level_convergence"]


def test_nafp_features_endpoint_returns_filtered_hazard_risk_feature():
    response = client.get(
        "/api/v1/diagnosis/nafp/features",
        params={
            "data_code": "NAFP_ECTHIN_NC",
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
