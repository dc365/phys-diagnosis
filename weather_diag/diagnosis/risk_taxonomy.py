from __future__ import annotations

from copy import deepcopy
from typing import Any


RISK_DOMAINS = {
    "precipitation": "强降水风险",
    "severe_convection": "强对流风险",
}


RISK_CHANNELS = [
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


HAZARD_TYPES: dict[str, dict[str, Any]] = {
    "persistent_heavy_rain": {
        "label": "持续性强降水",
        "description": "水汽输送、辐合抬升、深厚湿层和累计降水共同支持时，持续性强降水风险升高。",
        "evidence_summary": "重点查看低层水汽输送、水汽辐合、700hPa 上升运动、深厚湿层、低层辐合和模式累计降水。",
        "risk_domain": ["precipitation"],
        "score_grid": "risk_persistent_heavy_rain_score",
        "feature_type": "persistent_heavy_rain_risk",
        "mechanism_tags": ["persistent_moisture_transport", "large_scale_lift"],
    },
    "short_duration_heavy_rain": {
        "label": "短时强降水",
        "description": "暖湿低层、局地触发、不稳定能量和水汽辐合同步增强时，短时强降水风险升高。",
        "evidence_summary": "重点查看低层水汽、可降水量、水汽辐合、低层辐合、上升运动、CAPE/K 指数、列车效应和短时雨强。",
        "risk_domain": ["precipitation", "severe_convection"],
        "score_grid": "risk_short_duration_heavy_rain_score",
        "feature_type": "short_duration_heavy_rain_risk",
        "mechanism_tags": ["convective", "low_level_convergence", "moisture_convergence"],
    },
    "thunderstorm_gale": {
        "label": "雷暴大风/下击暴流",
        "description": "下沉冷池潜势、不稳定能量、深层风切变和触发条件配合时，雷暴大风或下击暴流风险升高。",
        "evidence_summary": "重点查看 DCAPE、中层干空气、0-6km 风切变、高空强风、雷暴发生潜势和线状组织潜势。",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_thunderstorm_gale_score",
        "feature_type": "thunderstorm_gale_risk",
        "mechanism_tags": ["downdraft_potential", "deep_layer_shear"],
    },
    "hail": {
        "label": "冰雹",
        "description": "强不稳定、组织化风切变、中层冷空气和适宜 0℃ 层高度配合时，冰雹风险升高。",
        "evidence_summary": "重点查看 CAPE、0-6km 风切变、中层冷空气、700-500hPa 递减率、0℃ 层高度、超级单体环境和触发条件。",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_hail_score",
        "feature_type": "hail_risk",
        "mechanism_tags": ["strong_updraft", "deep_layer_shear", "cold_mid_level"],
    },
    "rotating_storm_or_supercell": {
        "label": "旋转风暴/超级单体潜势",
        "description": "不稳定能量、深层风切变、低层切变或 SRH 共同支持时，旋转风暴或超级单体组织潜势升高。",
        "evidence_summary": "重点查看 CAPE、0-6km 风切变、0-1km 风切变、SRH、LCL、CIN 可突破和触发条件。",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_rotating_storm_score",
        "feature_type": "rotating_storm_risk",
        "mechanism_tags": ["deep_layer_shear", "low_level_rotation"],
    },
    "severe_convection_composite": {
        "label": "强对流综合风险",
        "description": "综合短时强降水、雷暴大风、冰雹和旋转风暴风险，用于快速识别强对流多灾种叠加区域。",
        "evidence_summary": "重点查看短时强降水、雷暴大风、冰雹和旋转风暴四类风险评分的叠加关系。",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_severe_convection_composite_score",
        "feature_type": "severe_convection_composite_risk",
        "mechanism_tags": ["composite"],
    },
}


DOMAIN_COMPOSITE_GRIDS = {
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
}


def hazard_metadata(hazard_type: str) -> dict[str, Any]:
    return deepcopy(HAZARD_TYPES[hazard_type])


def risk_metadata(hazard_type: str) -> dict[str, Any]:
    meta = HAZARD_TYPES[hazard_type]
    return {
        "hazard_type": hazard_type,
        "label": meta["label"],
        "description": meta["description"],
        "evidence_summary": meta["evidence_summary"],
        "risk_domain": list(meta["risk_domain"]),
        "source_grid": meta["score_grid"],
        "feature_type": meta["feature_type"],
        "mechanism_tags": list(meta["mechanism_tags"]),
        "score_range": [0, 1],
        "score_unit": "risk_score",
        "score_direction": "higher_is_riskier",
    }


def risk_metadata_catalog(hazard_types: list[str] | None = None) -> dict[str, dict[str, Any]]:
    selected = hazard_types or list(HAZARD_TYPES)
    return {hazard_type: risk_metadata(hazard_type) for hazard_type in selected}


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
