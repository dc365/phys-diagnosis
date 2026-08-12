from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.data.synthetic import create_demo_ecmwf_netcdf


client = TestClient(app)
PRIVATE_PATH_KEYS = {"data_dir", "file_path", "path", "root", "source_file", "source_path", "source_paths", "stored_path"}


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    return body


def assert_no_private_paths(value):
    if isinstance(value, dict):
        assert not (PRIVATE_PATH_KEYS & set(value))
        for item in value.values():
            assert_no_private_paths(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_private_paths(item)


def test_public_file_upload_stores_netcdf_and_returns_envelope(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "upload_demo.nc")

    with source.open("rb") as fh:
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("upload_demo.nc", fh, "application/x-netcdf")},
        )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["data"]["file_id"]
    assert body["data"]["original_filename"] == "upload_demo.nc"
    assert body["data"]["size"] > 0
    assert "stored_path" not in body["data"]
    assert_no_private_paths(body["data"])


def test_public_diagnose_job_accepts_file_path_and_can_be_looked_up(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "job_demo.nc")

    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "ecmwf",
            "file_path": str(source),
            "run_id": "public_api_job_demo",
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["job_id"]
    assert data["status"] == "succeeded"
    assert data["run_id"] == "public_api_job_demo"
    assert "file_path" not in data
    assert data["result"]["run_id"] == "public_api_job_demo"
    assert data["result"]["forecast_hours"]
    assert_no_private_paths(data)

    lookup = client.get(f"/api/v1/jobs/{data['job_id']}")

    assert lookup.status_code == 200
    lookup_body = envelope(lookup.json())
    assert lookup_body["code"] == 0
    assert lookup_body["data"]["job_id"] == data["job_id"]
    assert lookup_body["data"]["status"] == "succeeded"
    assert_no_private_paths(lookup_body["data"])


def test_public_diagnose_job_records_failure_for_missing_file():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "ecmwf",
            "file_path": "data/raw/not_here.nc",
            "run_id": "missing_public_file",
        },
    )

    assert response.status_code == 500
    body = envelope(response.json())
    assert body["code"] == 50001
    assert body["msg"] == "diagnosis failed"
    assert body["data"]["status"] == "failed"
    assert body["data"]["error"]
    assert_no_private_paths(body["data"])


def test_public_run_routes_wrap_existing_product_index():
    response = client.get("/api/v1/runs/ecmwf_demo")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["data"]["run_id"] == "ecmwf_demo"
    assert 24 in body["data"]["forecast_hours"]

    hours = client.get("/api/v1/runs/ecmwf_demo/forecast-hours")
    hours_body = envelope(hours.json())
    assert hours_body["data"] == [0, 6, 12, 24, 36]


def test_public_error_uses_msg_not_message():
    response = client.get("/api/v1/jobs/not-a-real-job")

    assert response.status_code == 404
    body = response.json()
    assert "msg" in body
    assert "message" not in body
    assert body["code"] == 40402
    assert body["data"] is None


def test_public_diagnose_requires_file_reference():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={"model": "ecmwf", "run_id": "missing_file_reference"},
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40003
    assert body["msg"] == "missing file reference"


def test_public_diagnose_rejects_unsupported_model():
    response = client.post(
        "/api/v1/jobs/diagnose",
        json={
            "model": "not_supported",
            "file_path": "data/raw/ecmwf_demo.nc",
            "run_id": "unsupported_model",
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40002
    assert body["msg"] == "unsupported model"
