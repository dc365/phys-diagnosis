from __future__ import annotations

import numpy as np

from weather_diag.data.synthetic import create_demo_ecmwf_netcdf
from weather_diag.features.risk import (
    multi_hazard_score_details,
)
from weather_diag.features.risk_scoring import (
    risk_level,
    score_conv_short_duration_heavy_rain,
    score_neg,
    score_percentile,
    score_persistent_heavy_rain,
    score_pos,
    score_precip_short_duration_heavy_rain,
    score_rotating_storm_supercell,
    score_triangular,
    weighted_mean,
)
from weather_diag.pipeline import diagnose_file, load_analysis, load_diagnostics, load_features


def _risk_grid():
    lat = np.linspace(20.0, 35.0, 16)
    lon = np.linspace(105.0, 123.0, 19)
    lon2d, lat2d = np.meshgrid(lon, lat)
    return lat, lon, lon2d, lat2d


def test_risk_scoring_utils_use_operational_0_100_thresholds():
    values = np.array([-1.0, 0.0, 5.0, 10.0, 12.0])

    np.testing.assert_allclose(score_pos(values, 0.0, 10.0), [0.0, 0.0, 50.0, 100.0, 100.0])
    np.testing.assert_allclose(score_neg(values, high=10.0, low=0.0), [100.0, 100.0, 50.0, 0.0, 0.0])
    np.testing.assert_allclose(
        score_triangular(np.array([1800.0, 2500.0, 4200.0, 5600.0]), 1800.0, 2500.0, 4200.0, 5600.0),
        [0.0, 100.0, 100.0, 0.0],
    )
    np.testing.assert_allclose(score_percentile(np.array([1.0, 3.0, 5.0]), p70=1.0, p95=5.0), [0.0, 50.0, 100.0])

    assert risk_level(81.0) == "very_high"
    assert risk_level(61.0) == "high"
    assert risk_level(41.0) == "medium"
    assert risk_level(21.0) == "low"
    assert risk_level(19.0) == "very_low"


def test_weighted_mean_skips_missing_factors_and_reports_confidence():
    score = np.array([[20.0, 80.0]])
    result = weighted_mean(
        {
            "available": (score, 0.7),
            "missing": (None, 0.3),
        },
        sample=score,
    )

    np.testing.assert_allclose(result["score"], score)
    np.testing.assert_allclose(result["confidence"], np.full_like(score, 0.7))
    assert result["available_weight"] == 0.7
    assert result["configured_weight"] == 1.0
    assert set(result["factors"]) == {"available"}


def test_pipeline_risk_features_include_dominant_factor_evidence(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "risk_demo.nc")
    diagnose_file(source, run_id="risk_feature_details_demo")
    features = load_features("risk_feature_details_demo", 24)["features"]
    risk_features = [
        feature
        for feature in features
        if str(feature["properties"].get("feature_type", "")).endswith("_risk")
    ]

    feature_types = {feature["properties"]["feature_type"] for feature in risk_features}
    assert "heavy_rain_risk" not in feature_types
    assert "convection_risk" not in feature_types
    assert {
        "persistent_heavy_rain_risk",
        "short_duration_heavy_rain_risk",
        "severe_convection_composite_risk",
    } <= feature_types
    for feature in risk_features:
        props = feature["properties"]
        assert props["risk_level"] in {"moderate", "high"}
        assert props["source_grid"].startswith("risk_")
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
    assert "heavy_rain_risk" not in {item["target_type"] for item in analysis["conclusions"]}
    assert "convection_risk" not in {item["target_type"] for item in analysis["conclusions"]}
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
    ]:
        assert name in ds
        assert ds[name].attrs["units"] == "0-1"
        assert float(ds[name].max()) <= 1.0
    assert "heavy_rain_score" not in ds
    assert "convection_score" not in ds
    assert "risk_precipitation_composite_score" not in ds


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
    }
    assert set(details["scores"]) == expected
    assert details["scores"]["risk_short_duration_heavy_rain_score"].shape == lon2d.shape
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


def test_persistent_heavy_rain_score_applies_moisture_and_lift_caps():
    grid = np.ones((2, 2), dtype=float)
    rich_environment = {
        "q850": grid * 0.016,
        "td2m": grid * 24.0,
        "pw": grid * 55.0,
        "rh850": grid * 90.0,
        "rh700": grid * 90.0,
        "rh500": grid * 80.0,
        "moisture_flux": grid * 220.0,
        "moisture_convergence": grid * 5.0,
        "div850": grid * -4.0e-5,
        "omega700": grid * -0.35,
        "precipitation": grid * 90.0,
    }
    dry_no_lift = {
        **rich_environment,
        "q850": grid * 0.003,
        "td2m": grid * 8.0,
        "pw": grid * 15.0,
        "rh850": grid * 35.0,
        "rh700": grid * 25.0,
        "rh500": grid * 20.0,
        "moisture_flux": grid * 20.0,
        "moisture_convergence": grid * 0.0,
        "div850": grid * 1.0e-5,
        "omega700": grid * 0.05,
    }

    rich = score_persistent_heavy_rain(rich_environment, {})
    capped = score_persistent_heavy_rain(dry_no_lift, {})

    assert rich["risk_type"] == "persistent_heavy_rain"
    assert float(np.nanmin(rich["score_grid"])) >= 80.0
    assert float(np.nanmax(capped["score_grid"])) <= 35.0
    assert "moisture_transport" in capped["factor_scores"]
    assert np.nanmin(capped["confidence_grid"]) > 0.0


def test_short_duration_heavy_rain_has_precipitation_and_convective_views():
    grid = np.ones((2, 2), dtype=float)
    precip_fields = {
        "q850": grid * 0.016,
        "td2m": grid * 24.0,
        "pw": grid * 55.0,
        "rh850": grid * 90.0,
        "moisture_flux": grid * 220.0,
        "moisture_convergence": grid * 5.0,
        "div850": grid * -4.0e-5,
        "omega700": grid * -0.35,
        "k_index": grid * 38.0,
        "cape": grid * 120.0,
        "cin": grid * -25.0,
        "shear_0_6km": grid * 5.0,
        "precipitation": grid * 90.0,
    }
    conv_fields = {
        **precip_fields,
        "cape": grid * 2500.0,
        "shear_0_6km": grid * 25.0,
        "moisture_convergence": grid * 5.0,
    }

    precip_view = score_precip_short_duration_heavy_rain(precip_fields, {})
    conv_view = score_conv_short_duration_heavy_rain(precip_fields, {})
    conv_rich_view = score_conv_short_duration_heavy_rain(conv_fields, {})

    assert precip_view["risk_type"] == "precip_short_duration_heavy_rain"
    assert float(np.nanmin(precip_view["score_grid"])) >= 65.0
    assert float(np.nanmax(conv_view["score_grid"])) <= 50.0
    assert float(np.nanmin(conv_rich_view["score_grid"])) > float(np.nanmax(conv_view["score_grid"]))
    assert "convective_character" in conv_rich_view["factor_scores"]


def test_rotating_storm_score_caps_when_srh_and_low_level_shear_are_missing():
    grid = np.ones((2, 2), dtype=float)
    missing_rotation = {
        "cape": grid * 2500.0,
        "shear_0_6km": grid * 25.0,
        "div850": grid * -4.0e-5,
        "cin": grid * -25.0,
        "lcl": grid * 600.0,
    }
    rich_rotation = {
        **missing_rotation,
        "shear_0_1km": grid * 15.0,
        "srh": grid * 300.0,
    }

    missing = score_rotating_storm_supercell(missing_rotation, {})
    rich = score_rotating_storm_supercell(rich_rotation, {})

    assert missing["risk_type"] == "rotating_storm_or_supercell"
    assert float(np.nanmax(missing["score_grid"])) <= 55.0
    assert float(np.nanmax(missing["confidence_grid"])) < float(np.nanmax(rich["confidence_grid"]))
    assert float(np.nanmin(rich["score_grid"])) >= 80.0


def test_multi_hazard_composite_uses_max_and_mean_top2_formula():
    grid = np.ones((2, 2), dtype=float)
    fields = {
        "q850": grid * 0.016,
        "td2m": grid * 24.0,
        "pw": grid * 55.0,
        "rh850": grid * 90.0,
        "rh700": grid * 90.0,
        "rh500": grid * 80.0,
        "moisture_flux": grid * 220.0,
        "moisture_convergence": grid * 5.0,
        "div850": grid * -4.0e-5,
        "omega700": grid * -0.35,
        "k_index": grid * 38.0,
        "cape": grid * 2500.0,
        "cin": grid * -25.0,
        "shear_0_6km": grid * 25.0,
        "shear_0_1km": grid * 15.0,
        "srh": grid * 300.0,
        "dcape": grid * 1500.0,
        "t500": grid * -18.0,
        "precipitation": grid * 90.0,
    }

    details = multi_hazard_score_details(fields, {})
    scores = details["scores"]
    severe_members = np.stack(
        [
            scores["risk_short_duration_heavy_rain_score"],
            scores["risk_thunderstorm_gale_score"],
            scores["risk_hail_score"],
            scores["risk_rotating_storm_score"],
        ]
    )
    sorted_members = np.sort(severe_members, axis=0)
    expected = sorted_members[-1] * 0.65 + np.nanmean(sorted_members[-2:], axis=0) * 0.35

    np.testing.assert_allclose(scores["risk_severe_convection_composite_score"], expected)
    assert set(details["scores"]) == {
        "risk_persistent_heavy_rain_score",
        "risk_short_duration_heavy_rain_score",
        "risk_thunderstorm_gale_score",
        "risk_hail_score",
        "risk_rotating_storm_score",
        "risk_severe_convection_composite_score",
    }
    assert "risk_precipitation_composite_score" not in details["scores"]
