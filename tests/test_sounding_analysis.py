from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


SOUNDING_FILE = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625/"
    "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv"
)


def _diagnose_sounding_situation():
    try:
        from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation
    except ModuleNotFoundError as exc:
        pytest.fail(f"optimized sounding diagnosis module is missing: {exc}")
    return diagnose_sounding_situation


def test_sounding_500hpa_analysis_uses_sounding_contract():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    payload = json.dumps(result, ensure_ascii=False, default=str)
    assert "radiosonde" not in payload.lower()
    assert result["data_type"] == "sounding"
    assert result["observation_time"] == "2026-06-25T20:00:00"
    assert result["analysis_level"] == "500hPa"

    z500 = result["analysis_fields"]["z500"]
    assert z500["unit"] == "gpm"
    assert z500["values"].shape == (51, 111)
    assert np.isfinite(z500["values"]).any()
    assert z500["quality"]["station_count"] > 150
    assert z500["quality"]["method"] == "barnes_successive_correction"
    assert 0.0 < z500["quality"]["supported_grid_ratio"] <= 1.0
    assert "support_distance_km" in z500
    assert "support_mask" in z500


def test_sounding_situation_outputs_weather_systems_and_station_winds():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    systems = result["systems"]
    feature_types = {item["feature_type"] for item in systems}
    assert {"height_high", "height_low", "warm_center", "cold_center"} <= feature_types
    assert feature_types & {"trough_candidate", "ridge_candidate"}
    assert all("confidence" in item and "evidence" in item for item in systems)

    wind_features = result["station_features"]["features"]
    assert len(wind_features) == result["analysis_fields"]["z500"]["quality"]["station_count"]
    first = wind_features[0]["properties"]
    assert {"station_id", "wind_direction_degree", "wind_speed_m_s"} <= set(first)


def test_sounding_profile_diagnostics_use_metpy_indices():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    diagnostics = result["station_diagnostics"]
    assert len(diagnostics) > 150
    valid = next(item for item in diagnostics if item["indices"]["precipitable_water_mm"] is not None)
    assert valid["source"] == "metpy"
    assert valid["quality"]["profile_level_count"] >= 10
    assert valid["indices"]["precipitable_water_mm"] > 0
    assert {"cape_j_kg", "cin_j_kg", "lcl_pressure_hpa", "lcl_temperature_c"} <= set(valid["indices"])


def test_sounding_station_risk_diagnoses_use_profile_indices():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    risk_items = result["station_risk_diagnoses"]
    assert len(risk_items) == len(result["station_diagnostics"])
    first = next(item for item in risk_items if item["risks"])
    risk = first["risks"][0]
    assert risk["score_source"] == "sounding_profile_indices"
    assert 0.0 <= risk["score"] <= 1.0
    assert risk["input_completeness"] < 1.0
    assert risk["score_cap_applied"] is True
    assert risk["dominant_factors"]
    assert {item["factor"] for item in risk["dominant_factors"]} & {"cape", "precipitable_water", "lcl"}


def test_public_sounding_situation_api_returns_map_ready_objects():
    client = TestClient(app)

    response = client.get(
        "/api/v1/sounding/situation",
        params={"csv_path": str(SOUNDING_FILE), "pressure_level": 500},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    payload = json.dumps(body["data"], ensure_ascii=False)
    assert "radiosonde" not in payload.lower()
    assert body["data"]["data_type"] == "sounding"
    assert "values" not in body["data"]["analysis_fields"]["z500"]
    assert body["data"]["analysis_fields"]["z500"]["quality"]["method"] == "barnes_successive_correction"
    assert body["data"]["systems"]
    assert body["data"]["station_features"]["features"]
    assert body["data"]["station_diagnostics"]
    assert body["data"]["station_diagnostics"][0]["source"] == "metpy"
    assert body["data"]["station_risk_diagnoses"]


def test_sounding_situation_to_feature_collection_maps_systems_and_station_risks():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    from weather_diag.diagnosis.sounding_features import sounding_situation_to_feature_collection

    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)
    collection = sounding_situation_to_feature_collection(
        result,
        requested_types=["trough", "short_duration_heavy_rain_risk"],
    )

    assert collection["type"] == "FeatureCollection"
    assert collection["properties"]["data_type"] == "sounding"
    assert collection["properties"]["observation_time"] == "2026-06-25T20:00:00"
    feature_types = {feature["properties"]["feature_type"] for feature in collection["features"]}
    assert "trough" in feature_types
    assert "short_duration_heavy_rain_risk" in feature_types
    risk_feature = next(
        feature
        for feature in collection["features"]
        if feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    )
    assert risk_feature["geometry"]["type"] == "Point"
    assert risk_feature["properties"]["score_source"] == "sounding_profile_indices"
    assert risk_feature["properties"]["evidence"]


def test_sounding_station_risk_features_keep_one_dominant_risk_per_station():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    from weather_diag.diagnosis.sounding_features import sounding_situation_to_feature_collection

    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)
    collection = sounding_situation_to_feature_collection(
        result,
        requested_types=[
            "short_duration_heavy_rain_risk",
            "rotating_storm_risk",
            "severe_convection_composite_risk",
        ],
    )

    risk_features = collection["features"]
    station_ids = [feature["properties"]["station_id"] for feature in risk_features]
    assert len(risk_features) == len(set(station_ids))
    assert len(risk_features) == len(result["station_risk_diagnoses"])


def test_public_sounding_features_api_returns_geojson_for_map():
    client = TestClient(app)

    response = client.get(
        "/api/v1/sounding/features",
        params={
            "csv_path": str(SOUNDING_FILE),
            "pressure_level": 500,
            "types": "trough,short_duration_heavy_rain_risk",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["type"] == "FeatureCollection"
    assert data["properties"]["count"] == len(data["features"])
    assert data["features"]
    assert {feature["geometry"]["type"] for feature in data["features"]} <= {"Point", "LineString"}


def test_public_sounding_z500_layer_grid_and_contours_reuse_map_contract():
    client = TestClient(app)
    params = {"csv_path": str(SOUNDING_FILE), "pressure_level": 500}

    metadata = client.get("/api/v1/sounding/layers/z500/metadata", params=params)
    grid = client.get("/api/v1/sounding/layers/z500/grid", params={**params, "max_cells": 12000})
    contours = client.get("/api/v1/sounding/layers/z500/contours", params=params)

    assert metadata.status_code == 200
    md = metadata.json()["data"]
    assert md["layer_id"] == "z500"
    assert md["title"] == "500hPa 位势高度"
    assert md["unit"] == "dagpm"
    assert md["data_type"] == "sounding"
    assert md["analysis_method"] == "barnes_successive_correction"
    assert md["station_count"] > 150
    assert 500 <= md["min"] <= md["max"] <= 600
    assert 0.0 < md["support_ratio"] <= 1.0

    assert grid.status_code == 200
    grid_data = grid.json()["data"]
    assert grid_data["type"] == "FeatureCollection"
    assert grid_data["properties"]["layer_id"] == "z500"
    assert grid_data["features"]
    assert 500 <= grid_data["features"][0]["properties"]["value"] <= 600

    assert contours.status_code == 200
    contour_data = contours.json()["data"]
    assert contour_data["type"] == "FeatureCollection"
    assert contour_data["properties"]["layer_id"] == "z500"
    assert contour_data["properties"]["smooth"] is True
    assert contour_data["features"]
    first = contour_data["features"][0]["properties"]
    assert first["line_color"] == "#3155d4"
    assert first["length_km"] >= 0


def test_public_sounding_t500_layer_and_contours_are_available():
    client = TestClient(app)
    params = {"csv_path": str(SOUNDING_FILE), "pressure_level": 500}

    metadata = client.get("/api/v1/sounding/layers/t500/metadata", params=params)
    contours = client.get("/api/v1/sounding/layers/t500/contours", params=params)

    assert metadata.status_code == 200
    md = metadata.json()["data"]
    assert md["layer_id"] == "t500"
    assert md["unit"] == "degC"
    assert md["analysis_method"] == "barnes_successive_correction"
    assert -40 <= md["min"] <= md["max"] <= 20

    assert contours.status_code == 200
    contour_data = contours.json()["data"]
    assert contour_data["properties"]["layer_id"] == "t500"
    assert contour_data["features"]
    first = contour_data["features"][0]["properties"]
    assert first["line_color"] == "#d9480f"
    assert "line_dash" in first
