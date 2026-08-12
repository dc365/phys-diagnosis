from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from backend.app.main import app
from weather_diag.config import THRESHOLD_MATRIX_PATH
from weather_diag.data.nafp import NAFP_SAMPLE_ROOT
from weather_diag.diagnosis.nafp_layers import load_nafp_layer
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


def envelope(body: dict) -> dict:
    assert set(body.keys()) == {"code", "msg", "data", "trace_id"}
    return body


def chain_by_type(result: dict, target_type: str) -> dict:
    return next(chain for chain in result["evidence_chains"] if chain["target_type"] == target_type)


def evidence_by_entry(chain: dict, entry_id: str) -> dict:
    return next(item for item in chain["evidence"] if item["entry_id"] == entry_id)


def system_evidence_by_entry(system: dict, entry_id: str) -> dict:
    return next(item for item in system["evidence"] if item["entry_id"] == entry_id)


def max_exterior_size(geometry: dict) -> int:
    coordinates = geometry["coordinates"]
    geojson_type = geometry.get("geojson_type", "Polygon")
    if geojson_type == "MultiPolygon":
        return max(len(polygon[0]) for polygon in coordinates)
    return len(coordinates[0])


def bbox_layer_max(layer: dict, bbox: list[float]) -> float:
    lon_min, lat_min, lon_max, lat_max = bbox
    lat = layer["lat"]
    lon = layer["lon"]
    lat_mask = (lat >= min(lat_min, lat_max)) & (lat <= max(lat_min, lat_max))
    lon_mask = (lon >= min(lon_min, lon_max)) & (lon <= max(lon_min, lon_max))
    values = layer["values"]
    subset = values[np.ix_(lat_mask, lon_mask)]
    if subset.size == 0 or not np.isfinite(subset).any():
        subset = values
    return round(float(np.nanmax(subset)), 3)


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


def test_nafp_situation_weather_systems_include_feature_type():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert result["systems"]
    for system in result["systems"]:
        assert system["feature_type"] == system["type"]


def test_nafp_situation_subtropical_high_reports_ridge_metrics():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    system = next(system for system in result["systems"] if system["type"] == "subtropical_high")

    assert system["geometry"]["type"] == "polygon"
    assert system["ridge_point"]["lon"] <= system["center"]["lon"]
    assert system["north_boundary_lat"] >= system["south_boundary_lat"]
    assert system["area_grid_points"] >= 20
    assert system["max_height"] >= system["mean_height"] >= system["threshold_height"]
    assert system["axis_orientation"] in {"zonal", "meridional", "compact"}
    assert "西伸脊点" in system["diagnosis"]
    assert {
        "system.subtropical_high.area_extent",
        "system.subtropical_high.ridge_point",
        "system.subtropical_high.north_boundary",
    } <= {item["entry_id"] for item in system["evidence"]}


def test_nafp_situation_weather_systems_include_primary_display_metadata():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    systems = result["systems"]
    assert systems
    assert [system["display_rank"] for system in systems] == list(range(1, len(systems) + 1))
    for system in systems:
        assert isinstance(system["primary"], bool)
        assert 0.0 <= system["salience_score"] <= 1.0

    primary_systems = [system for system in systems if system["primary"]]
    assert primary_systems
    assert len(primary_systems) < len(systems)
    assert len(primary_systems) <= 40

    primary_counts: dict[str, int] = {}
    for system in primary_systems:
        primary_counts[system["type"]] = primary_counts.get(system["type"], 0) + 1
    assert primary_counts["subtropical_high"] <= 1
    assert primary_counts["high"] <= 5
    assert primary_counts["low"] <= 5
    assert primary_counts["front_candidate"] <= 4
    assert primary_counts["moisture_transport"] <= 4


def test_nafp_situation_ranked_weather_system_confidence_reflects_salience():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    moisture_transports = [
        system for system in result["systems"] if system["type"] == "moisture_transport"
    ]
    assert len(moisture_transports) >= 2
    assert len({system["confidence"] for system in moisture_transports}) > 1
    assert moisture_transports[0]["confidence"] >= moisture_transports[-1]["confidence"]


def test_nafp_situation_summary_uses_chinese_operational_labels():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    summary = result["summary"]
    assert "subtropical_high" not in summary
    assert "heavy_rain_potential" not in summary
    assert "副高588区" in summary
    assert "低压辐合区" in summary
    assert "高压辐散区" in summary
    assert "持续性强降水" in summary
    assert "短时强降水" in summary
    assert "强降水潜势" not in summary


def test_nafp_situation_system_geometries_are_shapes_not_bboxes():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert all(system["geometry"]["type"] != "bbox" for system in result["systems"])

    polygon_systems = [
        system
        for system in result["systems"]
        if system["geometry"]["type"] == "polygon"
    ]
    assert polygon_systems
    assert all(system["geometry"]["coordinates"] for system in polygon_systems)
    assert any(max_exterior_size(system["geometry"]) > 5 for system in polygon_systems)

    for system_type in ["low_level_jet", "moisture_transport"]:
        system = next(system for system in result["systems"] if system["type"] == system_type)
        assert system["geometry"]["type"] == "line"
        assert len(system["geometry"]["coordinates"]) > 2

    for target_type in ["heavy_rain_potential", "convection_potential"]:
        region = chain_by_type(result, target_type)["region"]
        assert region["type"] == "polygon"
        assert region["coordinates"]
        assert region["bbox"]


def test_nafp_situation_detects_front_candidates_with_threshold_audit():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    fronts = [system for system in result["systems"] if system["type"] == "front_candidate"]
    assert fronts
    front = fronts[0]
    assert front["feature_type"] == "front_candidate"
    assert front["level"] == "850"
    assert front["geometry"]["type"] == "line"
    assert len(front["geometry"]["coordinates"]) > 2
    assert front["geometry"]["bbox"]
    assert front["confidence"] >= 0.55
    assert front["front_type"] in {
        "cold_front",
        "warm_front",
        "stationary_front",
        "mixed_front",
        "front_candidate",
    }
    assert front["front_type_label"].endswith("候选")
    assert front["front_motion"]
    assert front["front_motion_label"]
    assert front["front_type_confidence"] is not None
    assert front["classification_reason"]
    assert front["front_type_label"] in front["name"]
    assert front["axis_length_km"] > 0
    assert front["source_area_point_count"] > 0

    assert result["diagnostics"]["tt850"]["source_path"].endswith("/tt/850/2026/06/17/20/26061720.024")
    assert result["diagnostics"]["tt850_gradient"]["p90"] > 0
    assert result["diagnostics"]["front_candidate_score"]["p90"] > 0

    gradient = system_evidence_by_entry(front, "system.front_candidate.tt850_gradient_percentile")
    assert gradient["field"] == "tt850"
    assert gradient["statistic"] == "gradient_p80"
    assert gradient["operator"] == ">="
    assert gradient["threshold"] == 80.0
    assert gradient["raw_value"] > 0
    assert gradient["source_path"].endswith("/tt/850/2026/06/17/20/26061720.024")

    score = system_evidence_by_entry(front, "system.front_candidate.score_percentile")
    assert score["field"] == "front_candidate_score"
    assert score["statistic"] == "p82"
    assert score["threshold"] == 82.0
    assert score["raw_value"] > 0
    assert any(path.endswith("/ttadv/850/2026/06/17/20/26061720.024") for path in score["source_paths"])


def test_nafp_situation_detects_trough_ridge_axis_lines_with_threshold_audit():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    trough_lines = [
        system
        for system in result["systems"]
        if system["type"] == "trough_candidate" and system["geometry"]["type"] == "line"
    ]
    ridge_lines = [
        system
        for system in result["systems"]
        if system["type"] == "ridge_candidate" and system["geometry"]["type"] == "line"
    ]

    assert trough_lines
    assert ridge_lines
    assert all(
        system["geometry"]["type"] == "line"
        for system in result["systems"]
        if system["type"] in {"trough_candidate", "ridge_candidate"}
    )
    trough = trough_lines[0]
    ridge = ridge_lines[0]
    assert len(trough["geometry"]["coordinates"]) >= 4
    assert len(ridge["geometry"]["coordinates"]) >= 4
    assert "bbox" not in trough["geometry"]
    assert "bbox" not in ridge["geometry"]
    assert "轴线" in trough["diagnosis"]
    assert "轴线" in ridge["diagnosis"]

    trough_percentile = system_evidence_by_entry(trough, "system.trough_ridge.axis_anomaly_percentile")
    assert trough_percentile["field"] == "gh500_anomaly"
    assert trough_percentile["statistic"] == "axis_percentile"
    assert trough_percentile["operator"] == "tail_percentile"
    assert trough_percentile["threshold"] == 20.0
    assert trough_percentile["raw_value"] < 0
    assert trough_percentile["source_path"].endswith("/gh/500/2026/06/17/20/26061720.024")

    min_points = system_evidence_by_entry(trough, "system.trough_ridge.min_points_per_line")
    assert min_points["field"] == "gh500_anomaly"
    assert min_points["statistic"] == "line_point_count"
    assert min_points["threshold"] == 4.0
    assert min_points["raw_value"] >= 4


def test_nafp_situation_detects_pressure_centers_with_divergence_audit():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    lows = [system for system in result["systems"] if system["type"] == "low_pressure_convergence"]
    highs = [system for system in result["systems"] if system["type"] == "high_pressure_divergence"]

    assert lows
    assert highs
    low = lows[0]
    high = highs[0]
    assert low["feature_type"] == "low_pressure_convergence"
    assert high["feature_type"] == "high_pressure_divergence"
    assert low["geometry"]["type"] == "polygon"
    assert high["geometry"]["type"] == "polygon"
    assert "低压" in low["diagnosis"]
    assert "低层辐合" in low["diagnosis"]
    assert "高压" in high["diagnosis"]
    assert "低层辐散" in high["diagnosis"]

    low_height = system_evidence_by_entry(low, "system.low_pressure.gh500_anomaly_percentile")
    low_div = system_evidence_by_entry(low, "system.low_pressure.div850_convergence_percentile")
    assert low_height["field"] == "gh500_anomaly"
    assert low_height["operator"] == "<="
    assert low_height["raw_value"] < 0
    assert low_div["field"] == "div850"
    assert low_div["operator"] == "<="
    assert low_div["raw_value"] < 0
    assert low_div["source_path"].endswith("/div/850/2026/06/17/20/26061720.024")

    high_height = system_evidence_by_entry(high, "system.high_pressure.gh500_anomaly_percentile")
    high_div = system_evidence_by_entry(high, "system.high_pressure.div850_divergence_percentile")
    assert high_height["field"] == "gh500_anomaly"
    assert high_height["operator"] == ">="
    assert high_height["raw_value"] > 0
    assert high_div["field"] == "div850"
    assert high_div["operator"] == ">="
    assert high_div["raw_value"] > 0


def test_nafp_situation_detects_moisture_wind_and_divergence_system_extensions():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    types = {system["type"] for system in result["systems"]}
    assert {
        "low_level_jet",
        "moisture_transport",
        "moisture_convergence",
        "low_level_convergence",
        "upper_divergence",
    } <= types

    assert result["diagnostics"]["uv850_speed"]["p90"] > 0
    assert result["diagnostics"]["moisture_flux850"]["p90"] > 0
    assert result["diagnostics"]["moisture_flux_divergence850"]["min"] < 0

    low_level_jet = next(system for system in result["systems"] if system["type"] == "low_level_jet")
    assert low_level_jet["feature_type"] == "low_level_jet"
    assert low_level_jet["level"] == "850"
    assert low_level_jet["geometry"]["type"] == "line"
    assert "低空急流" in low_level_jet["diagnosis"]
    assert {
        "system.low_level_jet.wind_speed_min",
        "system.low_level_jet.moisture_flux_percentile",
    } <= {item["entry_id"] for item in low_level_jet["evidence"]}

    moisture_convergence = next(system for system in result["systems"] if system["type"] == "moisture_convergence")
    assert moisture_convergence["geometry"]["type"] == "polygon"
    assert "水汽辐合" in moisture_convergence["diagnosis"]
    assert "system.moisture_convergence.flux_divergence_percentile" in {
        item["entry_id"] for item in moisture_convergence["evidence"]
    }

    system_counts = {system_type: 0 for system_type in types}
    for system in result["systems"]:
        system_counts[system["type"]] = system_counts.get(system["type"], 0) + 1
    assert system_counts["low_level_jet"] <= 12
    assert system_counts["moisture_transport"] <= 12
    assert system_counts["moisture_convergence"] <= 12
    assert system_counts["low_level_convergence"] <= 12
    assert system_counts["upper_divergence"] <= 12


def test_nafp_situation_reports_dynamic_lift_and_phase_evidence_chains():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    chains = {chain["target_type"]: chain for chain in result["evidence_chains"]}
    assert {"dynamic_lift_potential", "precipitation_phase"} <= set(chains)
    assert result["diagnostics"]["vorticity500"]["source_path"].endswith("/uv/500/2026/06/17/20/26061720.024")
    assert result["diagnostics"]["tt850"]["source_path"].endswith("/tt/850/2026/06/17/20/26061720.024")

    dynamic = chains["dynamic_lift_potential"]
    assert dynamic["level"] in {"low", "moderate", "high"}
    assert {
        "dynamic_lift.w700",
        "dynamic_lift.vorticity500",
        "dynamic_lift.div850",
    } <= {item["entry_id"] for item in dynamic["evidence"]}

    phase = chains["precipitation_phase"]
    assert phase["phase_type"] in {"rain", "mixed", "snow", "freezing_rain", "unknown"}
    assert "phase.tt850" in {item["entry_id"] for item in phase["evidence"]}
    assert phase["diagnosis"]


def test_nafp_situation_reports_threshold_matrix_and_rule_audit_fields():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert result["threshold_matrix"]["matrix_id"] == "nafp-default"
    assert result["threshold_matrix"]["status"] == "default"

    heavy_rain = chain_by_type(result, "heavy_rain_potential")
    q850 = evidence_by_entry(heavy_rain, "heavy_rain.q850")
    assert q850["field"] == "q850"
    assert q850["statistic"] == "p75"
    assert q850["operator"] == "ramp"
    assert q850["threshold"] == 8.0
    assert q850["scale"] == 8.0
    assert q850["weight"] == 0.18
    assert q850["raw_value"] > q850["threshold"]
    assert 0 < q850["normalized_score"] <= 1
    assert q850["contribution"] == round(q850["normalized_score"] * q850["weight"], 6)


def test_nafp_evidence_chains_include_dominant_evidence_summary():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    for target_type in ["heavy_rain_potential", "convection_potential"]:
        chain = chain_by_type(result, target_type)
        dominant = chain["dominant_evidence"]
        assert 1 <= len(dominant) <= 3
        assert dominant == sorted(dominant, key=lambda item: item["contribution"], reverse=True)
        assert all(item["entry_id"] and item["signal"] for item in dominant)
        assert dominant[0]["contribution"] > 0


def test_nafp_evidence_chains_link_to_supporting_weather_systems():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    for target_type in ["heavy_rain_potential", "convection_potential"]:
        chain = chain_by_type(result, target_type)
        linked = chain["linked_systems"]
        assert linked
        assert linked[0]["system_id"]
        assert linked[0]["type"] in {
            "low_level_jet",
            "moisture_transport",
            "moisture_convergence",
            "low_level_convergence",
            "upper_divergence",
            "front_candidate",
            "trough_candidate",
            "ridge_candidate",
        }
        assert linked[0]["relation"] in {"overlap", "nearby"}
        assert linked[0]["reason"]


def test_nafp_situation_returns_multi_hazard_risk_diagnoses():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    diagnoses = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    assert set(diagnoses) == {
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    }

    persistent = diagnoses["persistent_heavy_rain"]
    assert persistent["risk_id"] == "risk-persistent_heavy_rain"
    assert persistent["risk_domain"] == ["precipitation"]
    assert persistent["label"] == "持续性强降水"
    assert persistent["risk_level"]
    assert "score_statistic" in persistent
    assert persistent["source_grid"] == "risk_persistent_heavy_rain_score"
    assert persistent["score_source"] == "source_grid"
    assert persistent["region_source"] == "source_grid"
    assert persistent["source_chain_ids"] == []
    assert persistent["region"]["type"] == "polygon"
    assert persistent["region"]["bbox"]
    assert "dominant_evidence" in persistent

    short_duration = diagnoses["short_duration_heavy_rain"]
    assert short_duration["risk_id"] == "risk-short_duration_heavy_rain"
    assert short_duration["risk_domain"] == ["precipitation", "severe_convection"]
    assert short_duration["label"] == "短时强降水"
    assert short_duration["risk_level"]
    assert "score_statistic" in short_duration
    assert short_duration["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert short_duration["score_source"] == "source_grid"
    assert short_duration["region_source"] == "source_grid"
    assert short_duration["source_chain_ids"] == []

    hail = diagnoses["hail"]
    assert hail["source_grid"] == "risk_hail_score"
    assert hail["risk_domain"] == ["severe_convection"]
    assert hail["score_source"] == "source_grid"


def test_nafp_situation_risk_score_uses_hazard_source_grid_region_statistic():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    diagnoses = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    short_duration = diagnoses["short_duration_heavy_rain"]
    layer = load_nafp_layer(
        short_duration["source_grid"],
        root=NAFP_SAMPLE_ROOT,
        run_time=result["run_time"],
        forecast_hour=result["forecast_hour"],
    )
    expected = bbox_layer_max(layer, short_duration["region"]["bbox"])

    assert short_duration["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert short_duration["score"] == expected
    assert short_duration["score_statistic"] == "bbox_max"
    assert short_duration["risk_level"] == short_duration["level"]
    assert short_duration["risk_level"]
    assert short_duration["source_chain_ids"] == []
    assert short_duration["region_source"] == "source_grid"


def test_nafp_situation_returns_diagnosis_conclusions():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    conclusions = result["diagnosis_conclusions"]
    by_type = {item["target_type"]: item for item in conclusions}
    assert {"heavy_rain_potential", "convection_potential"} <= set(by_type)
    heavy = by_type["heavy_rain_potential"]
    assert "强降水" in heavy["headline"]
    assert heavy["reasoning"]
    assert any("主导证据" in item for item in heavy["reasoning"])
    assert any("关联天气系统" in item for item in heavy["reasoning"])
    assert heavy["action_hint"]


def test_threshold_matrix_keeps_legacy_evidence_rules_internal_only():
    client = TestClient(app)
    base = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )
    base_chain = chain_by_type(base, "heavy_rain_potential")
    base_q850 = evidence_by_entry(base_chain, "heavy_rain.q850")
    matrix = client.get("/api/v1/admin/algorithms/threshold-matrix").json()["data"]

    assert base_q850["weight"] > 0
    assert base_q850["contribution"] > 0
    assert "heavy_rain.q850" not in {entry["entry_id"] for entry in matrix["entries"]}


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
    assert "source_path" not in str(body["data"])
    assert "source_paths" not in str(body["data"])
    assert "root" not in body["data"]


def test_nafp_situation_api_accepts_configured_data_code():
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnosis/nafp/situation",
        json={
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hour": 24,
        },
    )

    assert response.status_code == 200
    body = envelope(response.json())
    assert body["code"] == 0
    assert body["data"]["diagnostics"]["gh500"]["max"] > 580
    assert body["data"]["evidence_chains"]
    assert "source_path" not in str(body["data"])
    assert "source_paths" not in str(body["data"])


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
