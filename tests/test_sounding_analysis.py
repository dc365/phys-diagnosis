from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
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
    assert z500["quality"]["analysis_version"] == "sounding_z500_synoptic_v2"
    assert z500["quality"]["field_role"] == "synoptic_z500"
    assert z500["quality"]["distance_method"] == "great_circle_haversine"
    assert z500["quality"]["background_used"] is True
    assert z500["quality"]["correction_radii_km"] == z500["quality"]["radii_km"]
    assert z500["quality"]["vertical_interpolated_station_count"] >= 1
    assert 0.0 < z500["quality"]["supported_grid_ratio"] <= 1.0
    assert "support_distance_km" in z500
    assert "support_mask" in z500


def test_sounding_multilevel_augmentation_preserves_primary_z500_analysis():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    from weather_diag.diagnosis.sounding_optimized import SOUNDING_ANALYSIS_CONFIG

    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)
    quality = result["analysis_fields"]["z500"]["quality"]

    assert quality["radii_km"] == list(SOUNDING_ANALYSIS_CONFIG.radii_km)
    assert quality["correction_gains"] == list(SOUNDING_ANALYSIS_CONFIG.correction_gains)
    assert quality["smoothing_sigma_grid"] == SOUNDING_ANALYSIS_CONFIG.smoothing_sigma_grid


def test_objective_analysis_applies_the_broad_correction_to_a_supplied_background():
    from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field

    frame = pd.DataFrame(
        {
            "station_lon": [100.0, 110.0, 100.0, 110.0],
            "station_lat": [25.0, 25.0, 35.0, 35.0],
            "height": [5860.0, 5840.0, 5780.0, 5740.0],
        }
    )
    config = ObjectiveAnalysisConfig(
        radii_km=(900.0, 450.0),
        correction_gains=(1.0, 0.5),
        smoothing_sigma_grid=0.0,
        max_support_distance_km=1200.0,
    )
    field = objective_analysis_field(
        frame,
        "height",
        [25.0, 30.0, 35.0],
        [100.0, 105.0, 110.0],
        config=config,
        background=np.full((3, 3), 5800.0),
    )

    assert field.quality["background_used"] is True
    assert field.quality["correction_radii_km"] == [900.0, 450.0]
    assert field.quality["correction_gains"] == [1.0, 0.5]
    assert field.quality["distance_method"] == "great_circle_haversine"
    assert not np.allclose(field.values, 5800.0)


@pytest.mark.parametrize(
    "filename",
    [
        "regional_radiosonde_5N55N_50E160E_20260624_08BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260624_20BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260625_08BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
    ],
)
def test_sounding_z500_synoptic_field_regression_across_all_reference_times(filename: str):
    diagnose_sounding_situation = _diagnose_sounding_situation()
    from weather_diag.diagnosis.objective_analysis import mask_unsupported
    from weather_diag.io.contours import contours_to_geojson

    result = diagnose_sounding_situation(SOUNDING_FILE.with_name(filename), pressure_level=500)
    field = result["analysis_fields"]["z500"]
    quality = field["quality"]
    values = np.asarray(field["values"], dtype=float)
    supported = mask_unsupported(values * 0.1, field["support_mask"])
    contours = contours_to_geojson(
        "z500",
        "500hPa 位势高度",
        "dagpm",
        supported,
        lat=field["lat"],
        lon=field["lon"],
        interval=4.0,
        min_length_km=360.0,
    )

    assert quality["station_count"] >= 180
    assert quality["station_residual_rmse"] <= 18.0
    assert quality["supported_grid_ratio"] >= 0.85
    assert quality["correction_radii_km"] == quality["radii_km"]
    assert 5400.0 <= float(np.nanmin(values)) < 5800.0
    assert 5880.0 < float(np.nanmax(values)) <= 6050.0
    assert 10 <= len(contours["features"]) <= 30
    assert any(item["properties"]["value"] == 588.0 for item in contours["features"])


def test_sounding_troughs_keep_a_meridional_axis_in_the_nmc_china_domain():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    troughs = [item for item in result["systems"] if item["feature_type"] == "trough_candidate"]
    assert troughs
    assert all(item["method"] == "nmc_style_synoptic_axis_v7" for item in troughs)
    assert all(
        item["analysis_domain"]
        == {"lon_min": 60.0, "lon_max": 150.0, "lat_min": 15.0, "lat_max": 55.0}
        for item in troughs
    )

    central_axes = []
    for item in troughs:
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        if coordinates.ndim != 2 or len(coordinates) < 2:
            continue
        lon_span = float(np.ptp(coordinates[:, 0]))
        lat_span = float(np.ptp(coordinates[:, 1]))
        intersects_central_domain = float(np.nanmin(coordinates[:, 0])) <= 112.0 and float(np.nanmax(coordinates[:, 0])) >= 98.0
        if intersects_central_domain and lat_span >= 5.0 and lat_span >= lon_span:
            central_axes.append(item)

    assert central_axes


def test_sounding_troughs_recover_the_weak_southern_china_valley_track():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    lower_axes = []
    for item in result["systems"]:
        if item["feature_type"] != "trough_candidate":
            continue
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        core = coordinates[
            (coordinates[:, 0] >= 102.0)
            & (coordinates[:, 0] <= 114.0)
            & (coordinates[:, 1] >= 22.0)
            & (coordinates[:, 1] <= 36.0)
        ]
        if len(core) >= 2 and float(np.ptp(core[:, 1])) >= 4.0:
            lower_axes.append(item)

    assert lower_axes
    assert any(item["candidate_source"] == "meridional_valley_track" for item in lower_axes)


def test_sounding_troughs_do_not_promote_low_latitude_zonal_components():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    files = [
        SOUNDING_FILE,
        SOUNDING_FILE.with_name("regional_radiosonde_5N55N_50E160E_20260624_20BJT.csv"),
    ]

    for sounding_file in files:
        result = diagnose_sounding_situation(sounding_file, pressure_level=500)
        for item in result["systems"]:
            if item["feature_type"] != "trough_candidate":
                continue
            coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
            lon_span = float(np.ptp(coordinates[:, 0]))
            lat_span = float(np.ptp(coordinates[:, 1]))
            if float(np.nanmean(coordinates[:, 1])) < 30.0:
                assert lon_span <= 1.5 * max(lat_span, 0.5)


def test_sounding_meridional_recovery_stays_in_core_china_longitudes():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    recovered = [
        item
        for item in result["systems"]
        if item.get("candidate_source") == "meridional_valley_track"
    ]
    assert recovered
    for item in recovered:
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        assert float(np.nanmin(coordinates[:, 0])) >= 95.0
        assert float(np.nanmax(coordinates[:, 0])) <= 120.0


def test_sounding_situation_outputs_weather_systems_and_station_winds():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    systems = result["systems"]
    feature_types = {item["feature_type"] for item in systems}
    assert {"height_high", "height_low", "warm_center", "cold_center"} <= feature_types
    assert feature_types & {"trough_candidate", "ridge_candidate"}
    assert all("confidence" in item and "evidence" in item for item in systems)

    wind_features = result["station_features"]["features"]
    assert 150 < len(wind_features) <= result["analysis_fields"]["z500"]["quality"]["station_count"]
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
    from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, score_level

    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)
    matrix = load_threshold_matrix()

    assert result["threshold_matrix"]["matrix_id"] == matrix["matrix_id"]
    assert result["threshold_matrix"]["algorithm_id"] == matrix["algorithm_id"]
    risk_items = result["station_risk_diagnoses"]
    assert len(risk_items) == len(result["station_diagnostics"])
    first = next(item for item in risk_items if item["risks"])
    risk = first["risks"][0]
    assert risk["score_source"] == "sounding_profile_indices"
    for item in risk_items[:10]:
        for station_risk in item["risks"]:
            assert station_risk["risk_level"] == score_level(float(station_risk["score"]), matrix)
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
    assert body["data"]["analysis_contract"] == {
        "synoptic_height_field": "z500",
        "height_contour_field": "z500",
        "height_center_field": "z500",
        "trough_ridge_field": "z500",
        "analysis_version": "sounding_z500_synoptic_v2",
    }
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


def test_public_sounding_area_risks_returns_town_risk_from_sounding_grid():
    client = TestClient(app)

    response = client.get(
        "/api/v1/sounding/area-risks",
        params={
            "csv_path": str(SOUNDING_FILE),
            "pressure_level": 500,
            "town_code": "350203005",
            "risk_type": "short_duration_heavy_rain",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["data_type"] == "sounding"
    assert data["observation_time"] == "2026-06-25T20:00:00"
    assert data["forecast_hours"] == [0]
    assert data["scope"]["type"] == "town"
    assert data["summary"]["town_count"] == 1
    assert data["items"]
    item = data["items"][0]
    assert item["forecast_hour"] == 0
    assert item["valid_time"] == "2026-06-25T20:00:00"
    risk = item["risks"][0]
    assert risk["hazard_type"] == "short_duration_heavy_rain"
    assert risk["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert risk["score_source"] == "sounding_objective_analysis_grid"
    assert risk["score_statistic"] == "station_points_max"
    assert risk["evidence_chain"]["sampling_method"] == "station_points_on_sounding_grid"
    assert risk["sample_count"] > 0


def test_public_sounding_area_risks_use_multilevel_risk_grid_for_high_risk():
    client = TestClient(app)

    response = client.get(
        "/api/v1/sounding/area-risks",
        params={
            "csv_path": str(SOUNDING_FILE),
            "pressure_level": 500,
            "region_code": "350100",
            "region_level": "city",
            "risk_type": "persistent_heavy_rain",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    risks = [risk for item in data["items"] for risk in item["risks"]]
    assert max(float(risk["score"]) for risk in risks) >= 0.7
    assert any(risk["risk_level"] == "high" for risk in risks)


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
    assert md["apply_support_mask"] is True
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
    assert contour_data["properties"]["data_smoothing_sigma"] == 0.0
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
