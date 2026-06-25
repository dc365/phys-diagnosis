from __future__ import annotations

from weather_diag.diagnosis.risk_taxonomy import (
    HAZARD_TYPES,
    RISK_CHANNELS,
    feature_type_for_hazard,
    hazard_from_feature_type,
    legacy_target_hazards,
    risk_grid_for_hazard,
)


def test_short_duration_heavy_rain_is_cross_domain():
    meta = HAZARD_TYPES["short_duration_heavy_rain"]

    assert meta["label"] == "短时强降水"
    assert meta["risk_domain"] == ["precipitation", "severe_convection"]
    assert meta["score_grid"] == "risk_short_duration_heavy_rain_score"
    assert meta["feature_type"] == "short_duration_heavy_rain_risk"


def test_backend_risk_hazards_are_six_operational_categories():
    assert list(HAZARD_TYPES) == [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ]
    assert HAZARD_TYPES["thunderstorm_gale"]["label"] == "雷暴大风/下击暴流"
    assert "risk_precipitation_composite_score" not in {
        meta["score_grid"] for meta in HAZARD_TYPES.values()
    }


def test_frontend_risk_channels_keep_short_duration_in_both_domains():
    assert RISK_CHANNELS == [
        {
            "id": "precipitation",
            "label": "强降水风险",
            "hazard_types": ["persistent_heavy_rain", "short_duration_heavy_rain"],
        },
        {
            "id": "severe_convection",
            "label": "强对流风险",
            "hazard_types": [
                "short_duration_heavy_rain",
                "thunderstorm_gale",
                "hail",
                "rotating_storm_or_supercell",
            ],
        },
    ]


def test_hazard_feature_and_grid_mappings_are_bidirectional():
    assert risk_grid_for_hazard("hail") == "risk_hail_score"
    assert feature_type_for_hazard("thunderstorm_gale") == "thunderstorm_gale_risk"
    assert hazard_from_feature_type("rotating_storm_risk") == "rotating_storm_or_supercell"


def test_legacy_targets_expand_without_mutating_old_contract():
    assert legacy_target_hazards("heavy_rain_potential") == [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
    ]
    assert legacy_target_hazards("convection_potential") == [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ]
    assert legacy_target_hazards("heavy_rain_risk") == []
    assert legacy_target_hazards("convection_risk") == []
