from __future__ import annotations

from copy import deepcopy
from typing import Any


RISK_DOMAINS = {
    "precipitation": "强降水风险",
    "severe_convection": "强对流风险",
}


HAZARD_TYPES: dict[str, dict[str, Any]] = {
    "persistent_heavy_rain": {
        "label": "持续性强降水",
        "risk_domain": ["precipitation"],
        "score_grid": "risk_persistent_heavy_rain_score",
        "feature_type": "persistent_heavy_rain_risk",
        "mechanism_tags": ["persistent_moisture_transport", "large_scale_lift"],
    },
    "short_duration_heavy_rain": {
        "label": "短时强降水",
        "risk_domain": ["precipitation", "severe_convection"],
        "score_grid": "risk_short_duration_heavy_rain_score",
        "feature_type": "short_duration_heavy_rain_risk",
        "mechanism_tags": ["convective", "low_level_convergence", "moisture_convergence"],
    },
    "thunderstorm_gale": {
        "label": "雷暴大风",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_thunderstorm_gale_score",
        "feature_type": "thunderstorm_gale_risk",
        "mechanism_tags": ["downdraft_potential", "deep_layer_shear"],
    },
    "hail": {
        "label": "冰雹",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_hail_score",
        "feature_type": "hail_risk",
        "mechanism_tags": ["strong_updraft", "deep_layer_shear", "cold_mid_level"],
    },
    "rotating_storm_or_supercell": {
        "label": "旋转风暴/超级单体潜势",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_rotating_storm_score",
        "feature_type": "rotating_storm_risk",
        "mechanism_tags": ["deep_layer_shear", "low_level_rotation"],
    },
    "severe_convection_composite": {
        "label": "强对流综合风险",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_severe_convection_composite_score",
        "feature_type": "severe_convection_composite_risk",
        "mechanism_tags": ["composite"],
    },
}


DOMAIN_COMPOSITE_GRIDS = {
    "precipitation": "risk_precipitation_composite_score",
    "severe_convection": "risk_severe_convection_composite_score",
}


LEGACY_TARGET_HAZARDS = {
    "heavy_rain_potential": ["persistent_heavy_rain", "short_duration_heavy_rain"],
    "convection_potential": [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ],
    "heavy_rain_risk": ["persistent_heavy_rain", "short_duration_heavy_rain"],
    "convection_risk": [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ],
}


def hazard_metadata(hazard_type: str) -> dict[str, Any]:
    return deepcopy(HAZARD_TYPES[hazard_type])


def risk_grid_for_hazard(hazard_type: str) -> str:
    return str(HAZARD_TYPES[hazard_type]["score_grid"])


def feature_type_for_hazard(hazard_type: str) -> str:
    return str(HAZARD_TYPES[hazard_type]["feature_type"])


def hazard_from_feature_type(feature_type: str) -> str | None:
    for hazard_type, meta in HAZARD_TYPES.items():
        if meta["feature_type"] == feature_type:
            return hazard_type
    return None


def legacy_target_hazards(target_type: str) -> list[str]:
    return list(LEGACY_TARGET_HAZARDS.get(target_type, []))
