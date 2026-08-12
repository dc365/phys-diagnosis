from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from weather_diag.mcp import area_risk_dsl_mcp, point_risk


def test_parse_point_inputs_accepts_json_and_semicolon_text():
    assert point_risk.parse_point_inputs('[{"name":"鼓楼","lat":26.08,"lon":119.30}]') == [
        {"id": "P1", "name": "鼓楼", "lat": 26.08, "lon": 119.3}
    ]

    assert point_risk.parse_point_inputs("26.08,119.30;25.98,119.45") == [
        {"id": "P1", "name": "P1", "lat": 26.08, "lon": 119.3},
        {"id": "P2", "name": "P2", "lat": 25.98, "lon": 119.45},
    ]


def test_parse_point_inputs_rejects_duplicate_point_ids():
    try:
        point_risk.parse_point_inputs(
            [
                {"id": "P1", "name": "station-a", "lat": 26.0, "lon": 119.0},
                {"id": "P1", "name": "station-b", "lat": 26.1, "lon": 119.1},
            ]
        )
    except ValueError as exc:
        assert "duplicate point id" in str(exc)
    else:
        raise AssertionError("duplicate point ids should be rejected")


def test_get_point_risk_payload_returns_json_risk_and_evidence(monkeypatch):
    lat = np.array([25.0, 26.0], dtype=float)
    lon = np.array([119.0, 120.0], dtype=float)
    zero = np.zeros((2, 2), dtype=float)
    scores = {
        "risk_persistent_heavy_rain_score": zero.copy(),
        "risk_short_duration_heavy_rain_score": np.array([[0.1, 0.2], [0.3, 0.72]], dtype=float),
        "risk_thunderstorm_gale_score": zero.copy(),
        "risk_hail_score": zero.copy(),
        "risk_rotating_storm_score": zero.copy(),
        "risk_severe_convection_composite_score": np.array([[0.1, 0.2], [0.3, 0.66]], dtype=float),
    }
    details = {
        "scores": scores,
        "factors": {
            "risk_short_duration_heavy_rain_score": {
                "instability": {
                    "field": "cape",
                    "label": "CAPE",
                    "weight": 0.1,
                    "score": np.array([[0.1, 0.2], [0.3, 0.8]], dtype=float),
                    "contribution": np.array([[0.01, 0.02], [0.03, 0.08]], dtype=float),
                }
            },
            "risk_severe_convection_composite_score": {
                "short_duration_heavy_rain": {
                    "field": "risk_short_duration_heavy_rain_score",
                    "label": "短时强降水",
                    "weight": 0.25,
                    "score": scores["risk_short_duration_heavy_rain_score"],
                    "contribution": scores["risk_short_duration_heavy_rain_score"] * 0.25,
                }
            },
        },
    }

    monkeypatch.setattr(
        point_risk,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
        },
    )
    monkeypatch.setattr(
        point_risk,
        "resolve_forecast_context",
        lambda **_kwargs: {"run_time": datetime(2026, 6, 17, 20), "forecast_hours": [24]},
    )
    monkeypatch.setattr(
        point_risk,
        "_risk_input_bundle",
        lambda root, run_time, forecast_hour: (
            {
                "cape": np.array([[900.0, 1200.0], [1400.0, 1600.25]], dtype=float),
                "cin": np.array([[100.0, 80.0], [60.0, -42.5]], dtype=float),
            },
            lat,
            lon,
            ["/private/data/source-path-should-not-leak"],
        ),
    )
    monkeypatch.setattr(point_risk, "multi_hazard_score_details", lambda fields, thresholds: details)

    payload = point_risk.get_point_risk_payload(
        points=[{"name": "测试点", "lat": 25.9, "lon": 119.9}],
        start_time=datetime(2026, 6, 18, 20),
        end_time=datetime(2026, 6, 18, 23),
        models="EC",
    )

    assert "dsl" not in payload
    assert "model_results" not in payload
    assert payload["model_metadata"] == [
        {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24],
        }
    ]
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["point"]["name"] == "测试点"
    assert item["nearest_grid_point"]["lat"] == 26.0
    short_rain = next(risk for risk in item["risks"] if risk["hazard_type"] == "short_duration_heavy_rain")
    assert short_rain["score"] == 0.72
    assert short_rain["risk_level"] == "high"
    assert short_rain["evidence_chain"]["dominant_factors"][0]["field"] == "cape"
    assert short_rain["evidence_chain"]["dominant_factors"][0]["score"] == 0.8
    assert item["physical_evidence"]["CAPE"]["value"] == 1600.25
    assert item["physical_evidence"]["CIN"]["value"] == -42.5
    assert "source_paths" not in str(payload)


def test_get_point_risk_payload_multi_window_summarizes_and_reuses_products(monkeypatch):
    lat = np.array([25.0, 26.0], dtype=float)
    lon = np.array([119.0, 120.0], dtype=float)
    zero = np.zeros((2, 2), dtype=float)
    severe = np.array([[0.1, 0.2], [0.66, 0.9]], dtype=float)
    details = {
        "scores": {
            "risk_persistent_heavy_rain_score": zero.copy(),
            "risk_short_duration_heavy_rain_score": zero.copy(),
            "risk_thunderstorm_gale_score": zero.copy(),
            "risk_hail_score": zero.copy(),
            "risk_rotating_storm_score": zero.copy(),
            "risk_severe_convection_composite_score": severe,
        },
        "factors": {},
    }
    calls = {"bundle": 0, "score": 0}

    monkeypatch.setattr(
        point_risk,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
        },
    )
    monkeypatch.setattr(
        point_risk,
        "resolve_forecast_contexts",
        lambda **_kwargs: [
            {
                "run_time": datetime(2026, 7, 4, 8),
                "forecast_hours": [3],
                "valid_times": ["2026-07-04T11:00:00"],
            }
        ],
    )

    def fake_bundle(root, run_time, forecast_hour):
        calls["bundle"] += 1
        return (
            {
                "cape": np.array([[900.0, 1200.0], [1400.0, 1600.0]], dtype=float),
                "cin": np.array([[100.0, 80.0], [60.0, -40.0]], dtype=float),
            },
            lat,
            lon,
            [],
        )

    def fake_score(fields, thresholds):
        calls["score"] += 1
        return details

    monkeypatch.setattr(point_risk, "_risk_input_bundle", fake_bundle)
    monkeypatch.setattr(point_risk, "multi_hazard_score_details", fake_score)

    payload = point_risk.get_point_risk_payload(
        points=[
            {"id": "P1", "name": "station-a", "lat": 26.0, "lon": 120.0},
            {"id": "P2", "name": "station-b", "lat": 26.0, "lon": 119.0},
        ],
        models="EC",
        windows=[
            {
                "label": "today",
                "start_time": "2026-07-04T10:00:00",
                "end_time": "2026-07-04T12:00:00",
            },
            {
                "label": "overlap",
                "start_time": "2026-07-04T10:30:00",
                "end_time": "2026-07-04T12:30:00",
            },
        ],
    )

    assert payload["mode"] == "multi_window_point_risk"
    assert [window["label"] for window in payload["windows"]] == ["today", "overlap"]
    assert calls == {"bundle": 1, "score": 1}

    window = payload["windows"][0]
    assert len(window["items"]) == 2
    severe_summary = next(
        item for item in window["risk_summary"] if item["hazard_type"] == "severe_convection_composite"
    )
    assert severe_summary["max"] == 0.9
    assert severe_summary["max_level"] == "high"
    assert severe_summary["max_point_id"] == "P1"
    assert severe_summary["high_point_peak"] == 1
    assert severe_summary["watch_point_peak"] == 2
    assert severe_summary["watch_point_any"] == 2
    assert severe_summary["active_valid_time_count"] == 1
    assert severe_summary["item_count"] == 2

    point_summaries = [
        item for item in window["point_summary"] if item["hazard_type"] == "severe_convection_composite"
    ]
    by_point = {item["point_id"]: item for item in point_summaries}
    assert by_point["P1"]["high_valid_time_count"] == 1
    assert by_point["P1"]["watch_valid_time_count"] == 1
    assert by_point["P2"]["high_valid_time_count"] == 0
    assert by_point["P2"]["watch_valid_time_count"] == 1

    cape_summary = next(item for item in window["physical_summary"] if item["field"] == "CAPE")
    assert cape_summary["extreme"] == 1600.0
    assert cape_summary["extreme_level"] == "watch"
    assert cape_summary["extreme_point_id"] == "P1"
    assert cape_summary["high_point_peak"] == 0
    assert cape_summary["watch_point_peak"] == 2
    assert cape_summary["watch_point_any"] == 2
    assert cape_summary["active_valid_time_count"] == 1
    assert cape_summary["item_count"] == 2

    cin_summary = next(item for item in window["physical_summary"] if item["field"] == "CIN")
    assert cin_summary["extreme"] == -40.0
    assert cin_summary["extreme_level"] == "high"
    assert cin_summary["extreme_point_id"] == "P1"
    assert cin_summary["high_point_peak"] == 1
    assert cin_summary["watch_point_peak"] == 2
    assert cin_summary["watch_point_any"] == 2

    physical_by_point = {
        (item["point_id"], item["field"]): item
        for item in window["point_physical_summary"]
    }
    assert physical_by_point[("P1", "CAPE")]["watch_valid_time_count"] == 1
    assert physical_by_point[("P1", "CAPE")]["high_valid_time_count"] == 0
    assert physical_by_point[("P1", "CIN")]["extreme_level"] == "high"
    assert physical_by_point[("P1", "CIN")]["high_valid_time_count"] == 1
    assert physical_by_point[("P2", "CIN")]["extreme_level"] == "watch"
    assert physical_by_point[("P2", "CIN")]["high_valid_time_count"] == 0


def test_get_point_risk_payload_fixed_run_requires_run_time():
    try:
        point_risk.get_point_risk_payload(
            points=[{"id": "P1", "name": "station-a", "lat": 26.0, "lon": 119.0}],
            models="EC",
            windows=[
                {
                    "label": "today",
                    "start_time": "2026-07-04T20:00:00",
                    "end_time": "2026-07-04T23:00:00",
                }
            ],
            time_match_policy="fixed_run",
        )
    except ValueError as exc:
        assert "run_time is required when time_match_policy=fixed_run" in str(exc)
    else:
        raise AssertionError("fixed_run without run_time should fail before window evaluation")


def test_get_point_risk_mcp_passes_multi_window_arguments(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_point_risk_payload", fake_payload)

    response = area_risk_dsl_mcp.get_point_risk(
        points="26.0,119.0",
        models="EC",
        data_code="NAFP_ECTHIN_NC",
        windows="[]",
        time_match_policy="fixed_run",
        run_time="2026-07-04T08:00:00",
        include_window_summary=False,
    )

    assert response == {"code": 0, "msg": "success", "data": {"ok": True}}
    assert captured["windows"] == "[]"
    assert captured["time_match_policy"] == "fixed_run"
    assert captured["run_time"] == "2026-07-04T08:00:00"
    assert captured["include_window_summary"] is False


def test_get_point_risk_mcp_accepts_structured_points_and_windows(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_point_risk_payload", fake_payload)

    points = [{"id": "P1", "name": "station-a", "lat": 26.0, "lon": 119.0}]
    windows = [{"label": "today", "start_time": "2026-07-04T00:00:00", "end_time": "2026-07-04T23:59:59"}]

    response = area_risk_dsl_mcp.get_point_risk(points=points, windows=windows, run_time="")

    assert response == {"code": 0, "msg": "success", "data": {"ok": True}}
    assert captured["points"] == points
    assert captured["windows"] == windows
    assert captured["run_time"] is None
