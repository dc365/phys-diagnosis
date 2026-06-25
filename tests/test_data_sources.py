from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.data_sources import discover_nafp_run_inventory


client = TestClient(app)


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    return body


def test_admin_data_sources_exposes_configured_nafp_codes(monkeypatch):
    monkeypatch.setenv("WEATHER_DIAG_NAFP_ROOT", "/tmp/not-configured")
    monkeypatch.setenv("NAFP_ROOT", "/tmp/not-configured")

    response = client.get("/api/v1/admin/data-sources")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["default_code"] == "NAFP_ECTHIN_NC"
    assert {item["code"] for item in data["items"]} >= {
        "NAFP_ECTHIN_NC",
        "NAFP_CMA_GFS_NC",
    }

    ecthin = next(item for item in data["items"] if item["code"] == "NAFP_ECTHIN_NC")
    assert ecthin["label"] == "ECTHIN"
    assert ecthin["name"] == "NAFP_ECTHIN_NC"
    assert ecthin["model"] == "EC"
    assert ecthin["format"] == "nc"
    assert ecthin["enabled"] is True
    assert "root" not in ecthin
    assert ecthin["forecast_hour_range"] == {"start": 0, "end": 240, "step": 3}
    assert ecthin["forecast_hours"][:4] == [0, 3, 6, 9]
    assert ecthin["forecast_hours"][-1] == 240

    cma_gfs = next(item for item in data["items"] if item["code"] == "NAFP_CMA_GFS_NC")
    assert cma_gfs["label"] == "CMA-GFS"
    assert cma_gfs["name"] == "NAFP_CMA_GFS_NC"
    assert cma_gfs["model"] == "CMA-GFS"
    assert cma_gfs["format"] == "nc"
    assert cma_gfs["enabled"] is True
    assert "root" not in cma_gfs
    assert cma_gfs["forecast_hour_range"] == {"start": 0, "end": 240, "step": 3}


def test_discover_nafp_run_inventory_reads_times_and_hours_from_grid_files(tmp_path):
    root = tmp_path / "NAFP_ECTHIN_NC"
    run_dir = root / "gh" / "500" / "2026" / "06" / "17" / "20"
    run_dir.mkdir(parents=True)
    (run_dir / "26061720.000").write_bytes(b"demo")
    (run_dir / "26061720.024").write_bytes(b"demo")
    (run_dir / "ignore.txt").write_text("not a forecast file", encoding="utf-8")

    data = discover_nafp_run_inventory(root=root, data_code="TEST_CODE")

    assert data["data_code"] == "TEST_CODE"
    assert data["default_run_time"] == "2026-06-17T20:00:00"
    assert data["run_times"] == [
        {"run_time": "2026-06-17T20:00:00", "forecast_hours": [0, 24]}
    ]


def test_admin_data_source_nafp_runs_endpoint_wraps_inventory(monkeypatch):
    def fake_inventory(*, data_code, root=None, element="gh", level="500", max_run_times=20):
        return {
            "data_code": data_code,
            "root": "/tmp/NAFP_ECTHIN_NC",
            "probe": {"element": element, "level": level},
            "default_run_time": "2026-06-17T20:00:00",
            "run_times": [
                {"run_time": "2026-06-17T20:00:00", "forecast_hours": [0, 24, 36]},
            ],
        }

    monkeypatch.setattr(
        "backend.app.api.v1.data_sources.discover_nafp_run_inventory",
        fake_inventory,
    )

    response = client.get("/api/v1/admin/data-sources/NAFP_ECTHIN_NC/nafp-runs")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["data"]["data_code"] == "NAFP_ECTHIN_NC"
    assert "root" not in body["data"]
    assert body["data"]["default_run_time"] == "2026-06-17T20:00:00"
    assert body["data"]["run_times"][0]["forecast_hours"] == [0, 24, 36]
