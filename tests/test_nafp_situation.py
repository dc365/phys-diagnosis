from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    return body


def test_diagnose_nafp_situation_returns_evidence_payload():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert result["run_time"] == "2026-06-17T20:00:00"
    assert result["forecast_hour"] == 24
    assert result["valid_time"] == "2026-06-18T20:00:00"
    assert result["domain"]["lat_min"] == 0.0
    assert result["domain"]["lat_max"] == 60.0
    assert result["domain"]["lon_min"] == 60.0
    assert result["domain"]["lon_max"] == 150.0
    assert result["diagnostics"]["gh500"]["max"] > 580
    assert any(system["type"] == "subtropical_high" for system in result["systems"])
    assert {chain["target_type"] for chain in result["evidence_chains"]} >= {
        "heavy_rain_potential",
        "convection_potential",
    }
    assert "summary" in result and result["summary"]


def test_diagnose_nafp_situation_reports_missing_optional_fields(tmp_path):
    root = tmp_path / "empty_nafp"
    required_dir = root / "gh" / "500" / "2026" / "06" / "17" / "20"
    required_dir.mkdir(parents=True)
    sample = NAFP_SAMPLE_ROOT / "gh" / "500" / "2026" / "06" / "17" / "20" / "26061720.024"
    (required_dir / "26061720.024").write_bytes(sample.read_bytes())

    result = diagnose_nafp_situation(
        root=root,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    missing = {item["field"] for item in result["missing_fields"]}
    assert "uv850" in missing
    assert "div850" in missing
    assert result["diagnostics"]["gh500"]["max"] > 580


def test_nafp_situation_api_returns_public_envelope():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/situation",
        json={
            "root": str(NAFP_SAMPLE_ROOT),
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["data"]["diagnostics"]["gh500"]["max"] > 580
    assert body["data"]["evidence_chains"]


def test_nafp_situation_api_rejects_invalid_root():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/situation",
        json={
            "root": "/not/a/real/nafp/root",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40004
    assert body["msg"] == "invalid NAFP root"
