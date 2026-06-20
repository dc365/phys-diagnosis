from __future__ import annotations

import numpy as np

from weather_diag.data.synthetic import create_demo_ecmwf_netcdf
from weather_diag.features.risk import (
    convection_score_details,
    detect_heavy_rain_risk,
    heavy_rain_score_details,
    multi_hazard_score_details,
)
from weather_diag.pipeline import diagnose_file, load_analysis, load_diagnostics, load_features


def _risk_grid():
    lat = np.linspace(20.0, 35.0, 16)
    lon = np.linspace(105.0, 123.0, 19)
    lon2d, lat2d = np.meshgrid(lon, lat)
    return lat, lon, lon2d, lat2d


def test_heavy_rain_score_details_exposes_weighted_factor_contributions():
    lat, lon, lon2d, lat2d = _risk_grid()
    moisture_axis = np.exp(-(((lon2d - 114.0) / 4.0) ** 2 + ((lat2d - 27.0) / 2.5) ** 2))
    lift_axis = np.exp(-(((lon2d - 116.0) / 3.5) ** 2 + ((lat2d - 28.0) / 2.0) ** 2))
    weak_background = np.zeros_like(lon2d) + 0.1

    details = heavy_rain_score_details(
        {
            "moisture_flux": 100.0 * moisture_axis,
            "moisture_convergence": 6.0 * moisture_axis,
            "div850": -2.0e-5 * lift_axis,
            "omega700": -0.8 * lift_axis,
            "k_index": 35.0 * moisture_axis,
            "cape": weak_background,
            "precipitation": None,
        },
        {
            "heavy_rain_risk": {
                "weights": {
                    "moisture_flux": 0.25,
                    "moisture_convergence": 0.20,
                    "low_level_convergence": 0.18,
                    "upward_motion": 0.18,
                    "k_index": 0.12,
                    "cape": 0.04,
                    "precipitation": 0.03,
                }
            }
        },
    )

    assert details["score"].shape == lon2d.shape
    assert details["available_weight"] == 0.97
    assert {"moisture_flux", "moisture_convergence", "upward_motion"} <= set(details["factors"])
    moisture = details["factors"]["moisture_flux"]
    assert moisture["weight"] == 0.25
    assert moisture["contribution"].shape == lon2d.shape
    assert float(np.nanmax(moisture["contribution"])) > 0.20
    assert np.nanmax(details["score"]) <= 1.0


def test_heavy_rain_risk_features_include_level_core_and_dominant_factors():
    lat, lon, lon2d, lat2d = _risk_grid()
    score = np.zeros_like(lon2d) + 0.2
    primary = (((lon2d - 113.0) / 3.0) ** 2 + ((lat2d - 27.0) / 2.4) ** 2) <= 1.0
    secondary = (((lon2d - 120.0) / 1.7) ** 2 + ((lat2d - 32.0) / 1.4) ** 2) <= 1.0
    score[primary] = 0.82
    score[secondary] = 0.61

    moisture_contribution = np.zeros_like(score)
    lift_contribution = np.zeros_like(score)
    moisture_contribution[primary] = 0.42
    moisture_contribution[secondary] = 0.18
    lift_contribution[primary] = 0.22
    lift_contribution[secondary] = 0.28

    features = detect_heavy_rain_risk(
        score,
        lat,
        lon,
        {
            "heavy_rain_risk": {
                "score_threshold": 0.55,
                "high_score_threshold": 0.75,
                "min_area_grid_points": 4,
                "max_objects": 2,
            }
        },
        factor_details={
            "moisture_flux": {"label": "水汽通量", "weight": 0.25, "contribution": moisture_contribution},
            "upward_motion": {"label": "700hPa 上升运动", "weight": 0.18, "contribution": lift_contribution},
        },
    )

    assert len(features) == 2
    assert [feature["properties"]["rank"] for feature in features] == [1, 2]
    assert features[0]["properties"]["risk_level"] == "high"
    assert features[0]["properties"]["core_point_count"] > 0
    assert features[1]["properties"]["risk_level"] == "moderate"
    assert features[1]["properties"]["core_point_count"] == 0
    assert features[0]["properties"]["dominant_factors"][0]["factor"] == "moisture_flux"
    assert "核心区" in "".join(features[0]["properties"]["evidence"])


def test_convection_score_details_rewards_instability_shear_and_weak_inhibition():
    lat, lon, lon2d, lat2d = _risk_grid()
    core = np.exp(-(((lon2d - 115.0) / 3.0) ** 2 + ((lat2d - 29.0) / 2.0) ** 2))
    details = convection_score_details(
        {
            "cape": 1800.0 * core,
            "cin": -20.0 - 160.0 * (1.0 - core),
            "k_index": 32.0 * core,
            "shear_0_6km": 22.0 * core,
            "div850": -2.5e-5 * core,
            "moisture": 15.0 * core,
        },
        {
            "convection_risk": {
                "weights": {
                    "cape": 0.28,
                    "cin": 0.10,
                    "k_index": 0.12,
                    "shear_0_6km": 0.22,
                    "low_level_convergence": 0.15,
                    "moisture": 0.13,
                }
            }
        },
    )

    assert details["score"].shape == lon2d.shape
    assert details["available_weight"] == 1.0
    assert details["factors"]["cin"]["score"].max() > details["factors"]["cin"]["score"].min()
    assert details["factors"]["shear_0_6km"]["weight"] == 0.22
    assert float(np.nanmax(details["score"])) > 0.75


def test_pipeline_risk_features_include_dominant_factor_evidence(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "risk_demo.nc")
    diagnose_file(source, run_id="risk_feature_details_demo")
    features = load_features("risk_feature_details_demo", 24)["features"]
    risk_features = [
        feature
        for feature in features
        if feature["properties"]["feature_type"] in {"heavy_rain_risk", "convection_risk"}
    ]

    assert {feature["properties"]["feature_type"] for feature in risk_features} == {
        "heavy_rain_risk",
        "convection_risk",
    }
    for feature in risk_features:
        props = feature["properties"]
        assert props["risk_level"] in {"moderate", "high"}
        assert props["dominant_factors"]
        assert props["core_point_count"] >= 0
        assert props["supporting_systems"]
        assert props["supporting_systems"][0]["type"] in {
            "low_level_jet",
            "moisture_transport",
            "moisture_convergence",
            "low_level_convergence",
            "upper_divergence",
            "front_candidate",
            "trough",
            "ridge",
        }
        assert props["supporting_systems"][0]["reason"]

    analysis = load_analysis("risk_feature_details_demo", 24)
    assert analysis["conclusions"]
    assert {item["target_type"] for item in analysis["conclusions"]} >= {
        "heavy_rain_risk",
        "convection_risk",
    }
    assert any("强降水" in item["headline"] for item in analysis["conclusions"])


def test_pipeline_writes_multi_hazard_risk_score_grids(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "multi_hazard_demo.nc")
    diagnose_file(source, run_id="multi_hazard_risk_demo")
    ds = load_diagnostics("multi_hazard_risk_demo", 24)

    for name in [
        "risk_persistent_heavy_rain_score",
        "risk_short_duration_heavy_rain_score",
        "risk_thunderstorm_gale_score",
        "risk_hail_score",
        "risk_rotating_storm_score",
        "risk_severe_convection_composite_score",
        "risk_precipitation_composite_score",
    ]:
        assert name in ds
        assert ds[name].attrs["units"] == "0-1"
        assert float(ds[name].max()) <= 1.0


def test_pipeline_outputs_multi_hazard_risk_features(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "multi_hazard_features.nc")
    diagnose_file(source, run_id="multi_hazard_features_demo")
    features = load_features("multi_hazard_features_demo", 24)["features"]
    feature_types = {feature["properties"]["feature_type"] for feature in features}

    assert "short_duration_heavy_rain_risk" in feature_types
    assert "severe_convection_composite_risk" in feature_types

    short_rain = next(
        feature
        for feature in features
        if feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    )
    props = short_rain["properties"]
    assert props["hazard_type"] == "short_duration_heavy_rain"
    assert props["risk_domain"] == ["precipitation", "severe_convection"]
    assert props["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert props["dominant_factors"]
    assert "supporting_systems" in props


def test_multi_hazard_score_details_outputs_independent_score_grids():
    lat, lon, lon2d, lat2d = _risk_grid()
    core = np.exp(-(((lon2d - 115.0) / 3.0) ** 2 + ((lat2d - 29.0) / 2.0) ** 2))
    fields = {
        "moisture_flux": 100.0 * core,
        "moisture_convergence": 5.0 * core,
        "div850": -2.5e-5 * core,
        "omega700": -0.8 * core,
        "k_index": 34.0 * core,
        "cape": 1600.0 * core,
        "precipitation": 35.0 * core,
        "cin": -20.0 - 100.0 * (1.0 - core),
        "shear_0_6km": 24.0 * core,
        "dcape": 900.0 * core,
        "srh": 120.0 * core,
        "shear_0_1km": 8.0 * core,
        "li": -5.0 * core,
    }

    details = multi_hazard_score_details(
        fields,
        {
            "persistent_heavy_rain_risk": {
                "weights": {
                    "moisture_flux": 0.22,
                    "moisture_convergence": 0.24,
                    "low_level_convergence": 0.16,
                    "upward_motion": 0.20,
                    "precipitation": 0.18,
                }
            },
            "short_duration_heavy_rain_risk": {
                "weights": {
                    "moisture_flux": 0.16,
                    "moisture_convergence": 0.22,
                    "low_level_convergence": 0.20,
                    "k_index": 0.18,
                    "cape": 0.18,
                    "precipitation": 0.06,
                }
            },
            "thunderstorm_gale_risk": {
                "weights": {
                    "cape": 0.20,
                    "dcape": 0.24,
                    "shear_0_6km": 0.22,
                    "low_level_convergence": 0.12,
                }
            },
            "hail_risk": {"weights": {"cape": 0.30, "shear_0_6km": 0.30, "li": 0.10}},
            "rotating_storm_risk": {
                "weights": {
                    "cape": 0.22,
                    "shear_0_6km": 0.24,
                    "srh": 0.28,
                    "shear_0_1km": 0.12,
                }
            },
        },
    )

    expected = {
        "risk_persistent_heavy_rain_score",
        "risk_short_duration_heavy_rain_score",
        "risk_thunderstorm_gale_score",
        "risk_hail_score",
        "risk_rotating_storm_score",
        "risk_severe_convection_composite_score",
        "risk_precipitation_composite_score",
    }
    assert expected <= set(details["scores"])
    assert details["scores"]["risk_short_duration_heavy_rain_score"].shape == lon2d.shape
    assert float(np.nanmax(details["scores"]["risk_precipitation_composite_score"])) > 0.5
    assert float(np.nanmax(details["scores"]["risk_severe_convection_composite_score"])) > 0.5


def test_multi_hazard_score_details_normalizes_partial_weight_hazard_scores():
    lat, lon, lon2d, lat2d = _risk_grid()
    core = np.exp(-(((lon2d - 115.0) / 3.0) ** 2 + ((lat2d - 29.0) / 2.0) ** 2))
    details = multi_hazard_score_details(
        {
            "cape": 2000.0 * core,
            "shear_0_6km": 25.0 * core,
            "li": -6.0 * core,
        },
        {
            "persistent_heavy_rain_risk": {"weights": {}},
            "short_duration_heavy_rain_risk": {"weights": {}},
            "thunderstorm_gale_risk": {"weights": {}},
            "hail_risk": {"weights": {"cape": 0.30, "shear_0_6km": 0.30, "li": 0.10}},
            "rotating_storm_risk": {"weights": {}},
        },
    )

    hail = details["scores"]["risk_hail_score"]
    assert float(np.nanmax(hail)) > 0.72
    assert float(np.nanmax(hail)) <= 1.0
