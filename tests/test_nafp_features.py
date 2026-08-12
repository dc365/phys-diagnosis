from __future__ import annotations

import queue
import threading
import time

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.v1 import diagnosis as diagnosis_api
from backend.app.api.v1 import precompute as precompute_api
from backend.app.services import data_sources as data_sources_service
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis import nafp_cache
from weather_diag.diagnosis import nafp_precompute
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


def test_precomputed_features_endpoint_waits_for_shared_precompute_when_result_is_missing(monkeypatch, tmp_path):
    waits = []

    def fake_wait_for_precomputed_result(root, run_time, forecast_hour, data_code=None):
        waits.append((str(root), run_time, forecast_hour, data_code))
        return fake_situation_result(run_time, forecast_hour)

    monkeypatch.setattr(precompute_api, "wait_for_precomputed_result", fake_wait_for_precomputed_result)

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
    assert waits == [
        (str(tmp_path), "2026-06-17T20:00:00", 24, None),
    ]


def test_nafp_situation_cache_coalesces_concurrent_cold_requests(monkeypatch, tmp_path):
    nafp_cache.clear_nafp_situation_cache()
    monkeypatch.setattr(nafp_cache, "_extend_result_safely", lambda result, _key: result)
    started = threading.Event()
    release = threading.Event()
    contender_entered = threading.Event()
    calls = []
    results = []

    def slow_compute(*, root, run_time, forecast_hour):
        calls.append((str(root), run_time, forecast_hour))
        started.set()
        assert release.wait(2)
        return fake_situation_result(run_time, forecast_hour)

    def invoke(mark_contender=False):
        if mark_contender:
            contender_entered.set()
        results.append(
            nafp_cache.get_or_compute_nafp_situation(
                root=tmp_path,
                run_time="2026-06-17T20:00:00",
                forecast_hour=24,
                compute=slow_compute,
            )
        )

    owner = threading.Thread(target=invoke)
    contender = threading.Thread(target=invoke, kwargs={"mark_contender": True})
    owner.start()
    assert started.wait(1)
    contender.start()
    assert contender_entered.wait(1)
    time.sleep(0.05)

    assert len(calls) == 1

    release.set()
    owner.join(2)
    contender.join(2)

    assert not owner.is_alive()
    assert not contender.is_alive()
    assert len(calls) == 1
    assert {meta["cache_status"] for _, meta in results} == {"computed", "waited"}


def _prepare_precompute_runtime(monkeypatch, tmp_path, *, start_worker: bool):
    precompute_dir = tmp_path / "nafp_precompute"
    monkeypatch.setattr(nafp_precompute, "PRECOMPUTE_DIR", precompute_dir)
    monkeypatch.setattr(nafp_precompute, "RESULT_DIR", precompute_dir / "results")
    monkeypatch.setattr(nafp_precompute, "STATE_PATH", precompute_dir / "state.json")
    monkeypatch.setattr(nafp_precompute, "_jobs", {})
    monkeypatch.setattr(nafp_precompute, "_current_job_id", None)
    monkeypatch.setattr(nafp_precompute, "_last_loaded", True)
    monkeypatch.setattr(nafp_precompute, "_active_flights", {})
    monkeypatch.setattr(nafp_precompute, "_active_job_ids", set())
    monkeypatch.setattr(nafp_precompute, "_job_queue", queue.Queue())
    monkeypatch.setattr(nafp_precompute, "_worker_thread", None)
    if not start_worker:
        monkeypatch.setattr(nafp_precompute, "_ensure_worker_locked", lambda: None)


def test_precompute_uses_isolated_process_compute_by_default(monkeypatch, tmp_path):
    _prepare_precompute_runtime(monkeypatch, tmp_path, start_worker=False)
    calls = []

    def fake_isolated_compute(*, root, run_time, forecast_hour):
        calls.append((str(root), run_time, forecast_hour))
        return fake_situation_result(run_time, forecast_hour)

    monkeypatch.setattr(nafp_precompute, "diagnose_nafp_situation_isolated", fake_isolated_compute)
    monkeypatch.setattr(nafp_cache, "_extend_result_safely", lambda result, _key: result)

    job = nafp_precompute.submit_precompute_job(
        root=tmp_path,
        run_time="2026-06-17T20:00:00",
        forecast_hours=[24],
        data_code="TEST",
        background=False,
    )

    assert job["status"] == "completed"
    assert calls == [(str(tmp_path.resolve()), "2026-06-17T20:00:00", 24)]
    assert job["execution_mode"] == "isolated_process"


def test_precompute_reuses_active_job_for_the_same_forecast_hour(monkeypatch, tmp_path):
    _prepare_precompute_runtime(monkeypatch, tmp_path, start_worker=False)

    first = nafp_precompute.submit_precompute_job(
        root=tmp_path,
        run_time="2026-06-17T20:00:00",
        forecast_hours=[24],
        data_code="TEST",
        background=True,
    )
    second = nafp_precompute.submit_precompute_job(
        root=tmp_path,
        run_time="2026-06-17T20:00:00",
        forecast_hours=[24],
        data_code="TEST",
        background=True,
    )

    assert second["job_id"] == first["job_id"]
    assert second["deduplicated"] is True
    assert len(nafp_precompute._jobs) == 1


def test_precompute_background_jobs_run_with_one_worker(monkeypatch, tmp_path):
    _prepare_precompute_runtime(monkeypatch, tmp_path, start_worker=True)
    monkeypatch.setattr(nafp_cache, "_extend_result_safely", lambda result, _key: result)
    active = 0
    max_active = 0
    guard = threading.Lock()

    def slow_compute(*, root, run_time, forecast_hour):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return fake_situation_result(run_time, forecast_hour)

    monkeypatch.setattr(nafp_precompute, "diagnose_nafp_situation_isolated", slow_compute)
    jobs = [
        nafp_precompute.submit_precompute_job(
            root=tmp_path,
            run_time="2026-06-17T20:00:00",
            forecast_hours=[hour],
            data_code="TEST",
            background=True,
        )
        for hour in (3, 6)
    ]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if all(nafp_precompute._jobs[job["job_id"]]["status"] == "completed" for job in jobs):
            break
        time.sleep(0.01)

    assert all(nafp_precompute._jobs[job["job_id"]]["status"] == "completed" for job in jobs)
    assert max_active == 1


def test_auto_precompute_defaults_to_the_map_initial_forecast_hour(monkeypatch, tmp_path):
    submitted = []
    monkeypatch.delenv("WEATHER_DIAG_PRECOMPUTE_MAX_HOURS", raising=False)
    monkeypatch.delenv("WEATHER_DIAG_PRECOMPUTE_DEFAULT_HOUR", raising=False)
    monkeypatch.setattr(
        data_sources_service,
        "discover_nafp_run_inventory",
        lambda **_kwargs: {
            "run_times": [
                {
                    "run_time": "2026-06-17T20:00:00",
                    "forecast_hours": [0, 3, 6, 24, 48],
                }
            ]
        },
    )
    monkeypatch.setattr(data_sources_service, "resolve_data_root", lambda _code: tmp_path)
    monkeypatch.setattr(
        nafp_precompute,
        "submit_precompute_job",
        lambda **kwargs: submitted.append(kwargs) or {"status": "queued"},
    )

    result = nafp_precompute.autostart_precompute_for_latest(
        {
            "default_code": "TEST",
            "items": [{"code": "TEST", "forecast_hours": [0, 3, 6, 24, 48]}],
        }
    )

    assert result["status"] == "queued"
    assert submitted[0]["forecast_hours"] == [24]


def test_nafp_run_inventory_reuses_short_ttl_cache(monkeypatch, tmp_path):
    data_sources_service.clear_nafp_run_inventory_cache()
    calls = []

    def fake_discover(*, data_root, data_code, element, level, max_run_times):
        calls.append((data_root, data_code, element, level, max_run_times))
        return {
            "data_code": data_code,
            "root": str(data_root),
            "probe": {"element": element, "level": level},
            "default_run_time": "2026-06-17T20:00:00",
            "run_times": [{"run_time": "2026-06-17T20:00:00", "forecast_hours": [0, 24]}],
        }

    monkeypatch.setattr(data_sources_service, "_discover_nafp_run_inventory_uncached", fake_discover)

    first = data_sources_service.discover_nafp_run_inventory(root=tmp_path, data_code="TEST")
    second = data_sources_service.discover_nafp_run_inventory(root=tmp_path, data_code="TEST")

    assert first == second
    assert len(calls) == 1


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
