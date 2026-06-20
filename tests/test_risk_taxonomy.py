from __future__ import annotations

from weather_diag.diagnosis.risk_taxonomy import (
    HAZARD_TYPES,
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
