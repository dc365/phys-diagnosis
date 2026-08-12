from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.config import THRESHOLD_MATRIX_PATH, load_thresholds
from weather_diag.diagnosis.weather_system_governance import WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH


client = TestClient(app)


def _cleanup() -> None:
    THRESHOLD_MATRIX_PATH.unlink(missing_ok=True)
    WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.unlink(missing_ok=True)


def test_algorithm_governance_exposes_new_weather_systems_and_parameters():
    _cleanup()
    catalog_response = client.get("/api/v1/admin/algorithms/catalog")
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()["data"]
    system_ids = {item["system_id"] for item in catalog["algorithms"][0]["systems"]}
    assert {
        "shear_line_850_700_500",
        "vortex_500_700_850",
        "upper_jet_200_300",
        "pv_anomaly_300",
        "surface_boundary",
        "convergence_divergence_axes",
    } <= system_ids

    matrix = catalog["threshold_matrix"]
    entry_ids = {entry["entry_id"] for entry in matrix["entries"]}
    assert {
        "system.shear_line.score_percentile",
        "system.shear_line.vorticity_min_1e5",
        "system.vortex.min_height_prominence",
        "system.vortex.vorticity_min_1e5",
        "system.upper_jet.wind_speed_min",
        "system.upper_jet.exit_divergence_min_1e5",
        "system.pv_anomaly.pv_min",
        "system.surface_boundary.temp_gradient_percentile",
    } <= entry_ids
    assert matrix["weather_system_governance"]["entry_count"] > 20

    rules_response = client.get("/api/v1/admin/algorithms/rule-explanations")
    assert rules_response.status_code == 200
    sections = {item["rule_id"]: item for item in rules_response.json()["data"]["sections"]}
    assert {
        "shear_line_850_700_500",
        "vortex_500_700_850",
        "upper_jet_200_300",
        "pv_anomaly_300",
        "surface_boundary",
    } <= set(sections)
    assert all(sections[key]["governance_domain"] == "weather-systems" for key in {
        "shear_line_850_700_500",
        "vortex_500_700_850",
        "upper_jet_200_300",
        "pv_anomaly_300",
        "surface_boundary",
    })
    assert sections["shear_line_850_700_500"]["threshold_details"]


def test_weather_system_governance_updates_runtime_feature_thresholds():
    _cleanup()
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    for entry in active["entries"]:
        if entry["entry_id"] == "system.shear_line.score_percentile":
            entry["threshold"] = 91.0
        elif entry["entry_id"] == "system.shear_line.vorticity_min_1e5":
            entry["threshold"] = 1.7
        elif entry["entry_id"] == "system.upper_jet.wind_speed_min":
            entry["threshold"] = 34.0
        elif entry["entry_id"] == "system.pv_anomaly.require_positive_pv_advection":
            entry["threshold"] = 1.0

    response = client.put(
        "/api/v1/admin/algorithms/threshold-matrix",
        json={
            "algorithm_id": "nafp-situation",
            "updated_by": "algorithm-governance-test",
            "remark": "Tune integrated weather system thresholds.",
            "entries": active["entries"],
            "level_thresholds": active["level_thresholds"],
        },
    )
    assert response.status_code == 200
    try:
        saved = response.json()["data"]
        lookup = {entry["entry_id"]: entry for entry in saved["entries"]}
        assert lookup["system.shear_line.score_percentile"]["threshold"] == 91.0
        assert lookup["system.shear_line.vorticity_min_1e5"]["threshold"] == 1.7
        assert lookup["system.upper_jet.wind_speed_min"]["threshold"] == 34.0
        assert lookup["system.pv_anomaly.require_positive_pv_advection"]["threshold"] == 1.0
        assert WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.exists()

        thresholds = load_thresholds()
        assert thresholds["shear_line"]["score_percentile"] == 91.0
        assert thresholds["shear_line"]["vorticity_min"] == 1.7e-5
        assert thresholds["upper_jet"]["wind_speed_min_ms"] == 34.0
        assert thresholds["pv_anomaly"]["require_positive_pv_advection"] is True
    finally:
        _cleanup()


def test_weather_system_governance_rejects_non_integer_count_parameter():
    _cleanup()
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    for entry in active["entries"]:
        if entry["entry_id"] == "system.shear_line.min_support_components":
            entry["threshold"] = 2.5
            break
    response = client.put(
        "/api/v1/admin/algorithms/threshold-matrix",
        json={
            "algorithm_id": "nafp-situation",
            "entries": active["entries"],
            "level_thresholds": active["level_thresholds"],
        },
    )
    try:
        assert response.status_code == 400
        assert response.json()["code"] == 40005
        assert response.json()["data"]["entry_id"] == "system.shear_line.min_support_components"
    finally:
        _cleanup()
