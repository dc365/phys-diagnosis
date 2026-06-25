from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from weather_diag.mcp import point_risk


def test_parse_point_inputs_accepts_json_and_semicolon_text():
    assert point_risk.parse_point_inputs('[{"name":"鼓楼","lat":26.08,"lon":119.30}]') == [
        {"id": "P1", "name": "鼓楼", "lat": 26.08, "lon": 119.3}
    ]

    assert point_risk.parse_point_inputs("26.08,119.30;25.98,119.45") == [
        {"id": "P1", "name": "P1", "lat": 26.08, "lon": 119.3},
        {"id": "P2", "name": "P2", "lat": 25.98, "lon": 119.45},
    ]


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
