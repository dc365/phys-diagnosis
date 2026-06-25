from __future__ import annotations

import json

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
    legacy_targets = {
        "heavy_rain_potential",
        "convection_potential",
        "dynamic_lift_potential",
        "precipitation_phase",
    }
    assert legacy_targets.isdisjoint({chain["target"] for chain in data["algorithms"][0]["evidence_chains"]})
    assert {chain["target"] for chain in data["algorithms"][0]["evidence_chains"]} >= {
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    }
    assert {system["governance_domain"] for system in data["algorithms"][0]["systems"]} == {"weather-systems"}
    risk_chains = [
        chain for chain in data["algorithms"][0]["evidence_chains"]
        if chain["target"] in {
            "persistent_heavy_rain",
            "short_duration_heavy_rain",
            "thunderstorm_gale",
            "hail",
            "rotating_storm_or_supercell",
            "severe_convection_composite",
        }
    ]
    assert risk_chains
    assert {chain["governance_domain"] for chain in risk_chains} == {"risk-diagnosis"}
    assert "versions" not in data
    assert data["threshold_matrix"]["matrix_id"] == "nafp-default"
    assert data["threshold_matrix"]["status"] == "default"
    entry_ids = {entry["entry_id"] for entry in data["threshold_matrix"]["entries"]}
    legacy_entry_ids = {
        "region.risk.percentile",
        "region.risk.min_points",
        "heavy_rain.q850",
        "heavy_rain.tcwv",
        "heavy_rain.moisture_flux850",
        "heavy_rain.div850",
        "heavy_rain.w700",
        "heavy_rain.kindex",
        "heavy_rain.cape",
        "heavy_rain.rain6",
        "convection.cape",
        "convection.cin",
        "convection.kindex",
        "convection.shr850_200",
        "convection.q850",
        "convection.div850",
        "convection.upper_divergence",
        "convection.pv300",
        "convection.pvadv300",
        "convection.li",
        "convection.dcape",
        "convection.srh",
        "dynamic_lift.w700",
        "dynamic_lift.vorticity500",
        "dynamic_lift.div850",
        "dynamic_lift.upper_divergence",
        "dynamic_lift.pvadv300",
        "phase.t2m",
        "phase.tt850",
        "phase.tt925",
        "phase.tw0_height",
    }
    assert legacy_entry_ids.isdisjoint(entry_ids)
    assert {
        "风险区域",
        "强降水潜势",
        "强对流潜势",
        "动力抬升潜势",
        "雨雪相态",
    }.isdisjoint({entry.get("group") for entry in data["threshold_matrix"]["entries"]})
    risk_entries = [
        entry for entry in data["threshold_matrix"]["entries"]
        if entry.get("group") in {
            "持续性强降水",
            "短时强降水",
            "雷暴大风/下击暴流",
            "冰雹",
            "旋转风暴/超级单体潜势",
            "强对流综合风险",
        }
    ]
    assert {entry["group"] for entry in risk_entries} == {
        "持续性强降水",
        "短时强降水",
        "雷暴大风/下击暴流",
        "冰雹",
        "旋转风暴/超级单体潜势",
        "强对流综合风险",
    }
    assert {
        "risk.persistent_heavy_rain.score_threshold",
        "risk.persistent_heavy_rain.high_score_threshold",
        "risk.persistent_heavy_rain.min_area_grid_points",
        "risk.short_duration_heavy_rain.score_threshold",
        "risk.thunderstorm_gale.score_threshold",
        "risk.hail.score_threshold",
        "risk.rotating_storm_or_supercell.score_threshold",
        "risk.severe_convection_composite.score_threshold",
    } <= entry_ids
    risk_entry_lookup = {entry["entry_id"]: entry for entry in risk_entries}
    assert all("/" not in str(entry.get("field") or "") for entry in risk_entries)
    assert {
        "risk.short_duration_heavy_rain.weight.moisture.q850",
        "risk.short_duration_heavy_rain.weight.moisture.td2m",
        "risk.short_duration_heavy_rain.weight.moisture.tcwv",
        "risk.short_duration_heavy_rain.weight.moisture.rh850",
        "risk.short_duration_heavy_rain.weight.instability.cape",
        "risk.short_duration_heavy_rain.weight.instability.kindex",
        "risk.short_duration_heavy_rain.weight.instability.li",
    } <= entry_ids
    assert "risk.short_duration_heavy_rain.weight.moisture" not in entry_ids
    assert "risk.short_duration_heavy_rain.weight.instability" not in entry_ids
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.moisture.q850"]["field"] == "q850"
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.moisture.q850"]["threshold"] == 6.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.moisture.q850"]["scale"] == 8.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.moisture.q850"]["weight"] == 0.063
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.cape"]["field"] == "cape"
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.cape"]["threshold"] == 500.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.cape"]["scale"] == 2000.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.cape"]["weight"] == 0.045
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.kindex"]["threshold"] == 25.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.kindex"]["scale"] == 13.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.li"]["operator"] == "negative_ratio"
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.li"]["threshold"] == 2.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.instability.li"]["scale"] == 8.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.k_index"]["threshold"] == 25.0
    assert risk_entry_lookup["risk.short_duration_heavy_rain.weight.k_index"]["scale"] == 13.0
    assert risk_entry_lookup["risk.hail.weight.cape"]["threshold"] == 500.0
    assert risk_entry_lookup["risk.hail.weight.cape"]["scale"] == 2000.0
    assert "risk.short_duration_heavy_rain.weight.precip_short_heavy_rain_view" not in entry_ids
    assert "risk.short_duration_heavy_rain.weight.conv_short_heavy_rain_view" not in entry_ids
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
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
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
    assert by_id["subtropical_high_500"]["governance_domain"] == "weather-systems"
    for risk_rule_id in [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ]:
        assert by_id[risk_rule_id]["governance_domain"] == "risk-diagnosis"
        assert f"risk.{risk_rule_id}.score_threshold" in by_id[risk_rule_id]["threshold_entries"]
        assert f"risk.{risk_rule_id}.min_area_grid_points" in by_id[risk_rule_id]["threshold_entries"]
    short_duration = by_id["short_duration_heavy_rain"]
    assert "risk.short_duration_heavy_rain.weight.precip_short_heavy_rain_view" not in short_duration["threshold_entries"]
    assert short_duration["composition"]["mode"] == "max"
    assert short_duration["composition"]["formula"] == "max(降水型短时强降水通道, 对流型短时强降水通道)"
    assert [item["field"] for item in short_duration["composition"]["channels"]] == [
        "risk_precip_short_duration_heavy_rain_score",
        "risk_conv_short_duration_heavy_rain_score",
    ]
    assert all(item["weight"] is None for item in short_duration["composition"]["channels"])
    assert {
        "heavy_rain_potential",
        "convection_potential",
        "dynamic_lift_potential",
        "precipitation_phase",
    }.isdisjoint(by_id)
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


def test_threshold_matrix_can_update_the_default_matrix():
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    entries = active["entries"]
    for entry in entries:
        if entry["entry_id"] == "risk.persistent_heavy_rain.score_threshold":
            entry["threshold"] = 0.66

    response = client.put(
        "/api/v1/admin/algorithms/threshold-matrix",
        json={
            "algorithm_id": "nafp-situation",
            "updated_by": "duty-forecaster",
            "remark": "提高持续性强降水风险区起算阈值。",
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
        changed = next(entry for entry in saved["entries"] if entry["entry_id"] == "risk.persistent_heavy_rain.score_threshold")
        assert changed["threshold"] == 0.66

        lookup = client.get("/api/v1/admin/algorithms/threshold-matrix")
        assert lookup.status_code == 200
        assert lookup.json()["data"]["matrix_id"] == "nafp-default"
    finally:
        THRESHOLD_MATRIX_PATH.unlink(missing_ok=True)


def test_threshold_matrix_migrates_saved_weight_values_out_of_threshold_columns():
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    entries = []
    for entry in active["entries"]:
        item = dict(entry)
        if item["entry_id"] == "risk.short_duration_heavy_rain.weight.instability.cape":
            item["threshold"] = item["weight"]
            item["scale"] = None
            item["operator"] = "weight"
            item["statistic"] = "factor_component_weight"
            item["unit"] = "ratio"
        entries.append(item)
    saved = {**active, "entries": entries}
    THRESHOLD_MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLD_MATRIX_PATH.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

    try:
        response = client.get("/api/v1/admin/algorithms/threshold-matrix")
        assert response.status_code == 200
        migrated = next(
            entry
            for entry in response.json()["data"]["entries"]
            if entry["entry_id"] == "risk.short_duration_heavy_rain.weight.instability.cape"
        )
        assert migrated["threshold"] == 500.0
        assert migrated["scale"] == 2000.0
        assert migrated["operator"] == "ramp"
        assert migrated["unit"] == "J/kg"
        assert migrated["weight"] == 0.045
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


def test_threshold_matrix_rejects_legacy_evidence_chain_entries():
    active = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]
    entries = [*active["entries"], {"entry_id": "heavy_rain.q850", "threshold": 9.5}]

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
