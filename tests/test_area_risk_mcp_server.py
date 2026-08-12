from __future__ import annotations

from weather_diag.mcp import area_risk_dsl_mcp


def test_town_risk_mcp_accepts_run_time_parameter(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_town_risk_dsl_payload", fake_payload)

    response = area_risk_dsl_mcp.get_town_risk_dsl(run_time="2026-06-17T20:00:00")

    assert response["code"] == 0
    assert captured["run_time"] == "2026-06-17T20:00:00"


def test_point_risk_mcp_accepts_blank_run_time_as_default(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_point_risk_payload", fake_payload)

    response = area_risk_dsl_mcp.get_point_risk(points="26.08,119.30", run_time="")

    assert response["code"] == 0
    assert captured["run_time"] is None
