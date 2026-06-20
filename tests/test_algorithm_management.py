from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.config import DATA_DIR


client = TestClient(app)
THRESHOLD_MATRIX_PATH = DATA_DIR / "admin" / "threshold_matrix.json"


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    return body


def test_algorithm_catalog_exposes_nafp_rules_and_default_matrix():
    response = client.get("/api/v1/admin/algorithms/catalog")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["algorithms"][0]["algorithm_id"] == "nafp-situation"
    assert data["algorithms"][0]["name"] == "NAFP 天气形势诊断"
    assert {system["system_id"] for system in data["algorithms"][0]["systems"]} >= {
        "low_pressure_convergence_500",
        "high_pressure_divergence_500",
        "low_level_jet_850",
        "moisture_transport_850",
        "moisture_convergence_850",
    }
    assert {chain["chain_id"] for chain in data["algorithms"][0]["evidence_chains"]} >= {
        "heavy_rain_potential",
        "convection_potential",
        "dynamic_lift_potential",
        "precipitation_phase",
    }
    assert {chain["target"] for chain in data["algorithms"][0]["evidence_chains"]} >= {
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    }
    assert "versions" not in data
    assert data["threshold_matrix"]["matrix_id"] == "nafp-default"
    assert data["threshold_matrix"]["status"] == "default"
    entry_ids = {entry["entry_id"] for entry in data["threshold_matrix"]["entries"]}
    assert "heavy_rain.q850" in entry_ids
    assert {
        "system.front_candidate.tt850_gradient_percentile",
        "system.front_candidate.score_percentile",
        "system.front_candidate.dynamic_support_percentile",
        "system.front_candidate.min_support_components",
        "system.front_candidate.max_objects",
        "system.front_candidate.min_points",
        "system.trough_ridge.axis_anomaly_percentile",
        "system.trough_ridge.curvature_percentile",
        "system.trough_ridge.vorticity_support",
        "system.trough_ridge.min_points_per_line",
        "system.trough_ridge.max_lines",
        "system.low_pressure.gh500_anomaly_percentile",
        "system.low_pressure.div850_convergence_percentile",
        "system.high_pressure.gh500_anomaly_percentile",
        "system.high_pressure.div850_divergence_percentile",
        "system.pressure_center.min_points",
        "system.pressure_center.max_centers",
        "system.low_level_jet.wind_speed_min",
        "system.low_level_jet.moisture_flux_percentile",
        "system.low_level_jet.min_direction_coherence",
        "system.low_level_jet.max_objects",
        "system.moisture_transport.flux_percentile",
        "system.moisture_transport.min_direction_coherence",
        "system.moisture_transport.max_objects",
        "system.moisture_convergence.flux_divergence_percentile",
        "system.moisture_convergence.smoothing_sigma_grid",
        "system.moisture_convergence.max_objects",
        "system.low_level_convergence.div850_percentile",
        "system.low_level_convergence.smoothing_sigma_grid",
        "system.low_level_convergence.max_objects",
        "system.upper_divergence.divergence_percentile",
        "system.upper_divergence.smoothing_sigma_grid",
        "system.upper_divergence.max_objects",
        "dynamic_lift.w700",
        "dynamic_lift.vorticity500",
        "dynamic_lift.div850",
        "dynamic_lift.upper_divergence",
        "dynamic_lift.pvadv300",
        "phase.t2m",
        "phase.tt850",
        "phase.tt925",
        "phase.tw0_height",
    } <= entry_ids


def test_rule_explanations_describe_algorithm_basis_and_threshold_links():
    response = client.get("/api/v1/admin/algorithms/rule-explanations")

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    data = body["data"]
    assert data["algorithm_id"] == "nafp-situation"
    assert data["matrix_id"] == "nafp-default"

    sections = data["sections"]
    by_id = {section["rule_id"]: section for section in sections}
    assert {
        "subtropical_high_500",
        "trough_ridge_500",
        "low_pressure_convergence_500",
        "high_pressure_divergence_500",
        "front_candidate_850",
        "low_level_jet_850",
        "moisture_transport_850",
        "moisture_convergence_850",
        "low_level_convergence_850",
        "upper_divergence",
        "heavy_rain_potential",
        "convection_potential",
        "dynamic_lift_potential",
        "precipitation_phase",
    } <= set(by_id)

    for rule_id, section in by_id.items():
        assert section["title"]
        assert section["category"]
        assert section["basis"]
        assert section["inputs"]
        assert section["method"]
        assert section["threshold_entries"], rule_id
        assert section["outputs"]
        assert section["evidence_contract"]

    assert "system.subtropical_high.gh500_dam" in by_id["subtropical_high_500"]["threshold_entries"]
    assert "system.trough_ridge.axis_anomaly_percentile" in by_id["trough_ridge_500"]["threshold_entries"]
    assert "system.trough_ridge.curvature_percentile" in by_id["trough_ridge_500"]["threshold_entries"]
    assert "system.low_pressure.div850_convergence_percentile" in by_id["low_pressure_convergence_500"]["threshold_entries"]
    assert "system.high_pressure.div850_divergence_percentile" in by_id["high_pressure_divergence_500"]["threshold_entries"]
    assert "system.front_candidate.score_percentile" in by_id["front_candidate_850"]["threshold_entries"]
    assert "system.front_candidate.dynamic_support_percentile" in by_id["front_candidate_850"]["threshold_entries"]
    assert "system.front_candidate.max_objects" in by_id["front_candidate_850"]["threshold_entries"]
    assert "system.low_level_jet.wind_speed_min" in by_id["low_level_jet_850"]["threshold_entries"]
    assert "system.low_level_jet.max_objects" in by_id["low_level_jet_850"]["threshold_entries"]
    assert "system.moisture_transport.max_objects" in by_id["moisture_transport_850"]["threshold_entries"]
    assert "system.moisture_convergence.flux_divergence_percentile" in by_id["moisture_convergence_850"]["threshold_entries"]
    assert "system.moisture_convergence.max_objects" in by_id["moisture_convergence_850"]["threshold_entries"]
    assert "system.low_level_convergence.max_objects" in by_id["low_level_convergence_850"]["threshold_entries"]
    assert "system.upper_divergence.max_objects" in by_id["upper_divergence"]["threshold_entries"]
    assert "front_score" in " ".join(by_id["front_candidate_850"]["method"])
    assert "heavy_rain.q850" in by_id["heavy_rain_potential"]["threshold_entries"]
    assert "convection.cape" in by_id["convection_potential"]["threshold_entries"]
    assert "dynamic_lift.vorticity500" in by_id["dynamic_lift_potential"]["threshold_entries"]
    assert "phase.tt850" in by_id["precipitation_phase"]["threshold_entries"]


def test_threshold_matrix_can_update_the_default_matrix():
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    entries = active["entries"]
    for entry in entries:
        if entry["entry_id"] == "heavy_rain.q850":
            entry["threshold"] = 9.5
            entry["weight"] = 0.2

    response = client.put(
        "/api/v1/admin/algorithms/threshold-matrix",
        json={
            "algorithm_id": "nafp-situation",
            "updated_by": "duty-forecaster",
            "remark": "提高 q850 起算阈值，增强水汽证据权重。",
            "entries": entries,
            "level_thresholds": active["level_thresholds"],
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    saved = body["data"]
    try:
        assert saved["matrix_id"] == "nafp-default"
        assert saved["status"] == "default"
        changed = next(entry for entry in saved["entries"] if entry["entry_id"] == "heavy_rain.q850")
        assert changed["threshold"] == 9.5
        assert changed["weight"] == 0.2

        lookup = client.get("/api/v1/admin/algorithms/threshold-matrix")
        assert lookup.status_code == 200
        assert lookup.json()["data"]["matrix_id"] == "nafp-default"
    finally:
        THRESHOLD_MATRIX_PATH.unlink(missing_ok=True)


def test_threshold_matrix_rejects_invalid_weight():
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    entries = active["entries"]
    entries[0]["weight"] = 2

    response = client.put(
        "/api/v1/admin/algorithms/threshold-matrix",
        json={
            "algorithm_id": "nafp-situation",
            "entries": entries,
            "level_thresholds": active["level_thresholds"],
        },
    )

    assert response.status_code == 400
    body = envelope(response.json())
    assert body["code"] == 40005
    assert body["msg"] == "invalid threshold matrix"
