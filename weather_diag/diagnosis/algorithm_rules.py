from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

from weather_diag.config import THRESHOLD_MATRIX_PATH, ensure_dirs
from weather_diag.features.risk_scoring import DEFAULT_RISK_SCORING


ALGORITHM_ID = "nafp-situation"
DEFAULT_MATRIX_ID = "nafp-default"
WEATHER_SYSTEM_DOMAIN = "weather-systems"
RISK_DIAGNOSIS_DOMAIN = "risk-diagnosis"
SUPPORTING_DIAGNOSIS_DOMAIN = "supporting-diagnosis"
RISK_DIAGNOSIS_TARGETS = {
    "persistent_heavy_rain",
    "short_duration_heavy_rain",
    "thunderstorm_gale",
    "hail",
    "rotating_storm_or_supercell",
    "severe_convection_composite",
}
LEGACY_SUPPORT_TARGETS = {
    "heavy_rain_potential",
    "convection_potential",
    "dynamic_lift_potential",
    "precipitation_phase",
    "evidence_chain_region",
}

RISK_RULE_SPECS = {
    "persistent_heavy_rain": {
        "title": "持续性强降水",
        "purpose": "综合水汽输送、水汽辐合、上升运动、深厚湿层和累计降水，输出持续性强降水风险评分。",
        "basis": ["水汽供给、持续抬升和模式累计降水共同增强时，持续性强降水风险升高。"],
        "inputs": ["q850", "tcwv", "uv850", "div850", "w700", "rain6"],
    },
    "short_duration_heavy_rain": {
        "title": "短时强降水",
        "purpose": "综合低层水汽、CAPE/K 指数、低层触发、水汽辐合和短时降水响应，输出短时强降水风险评分。",
        "basis": ["暖湿低层、局地触发和不稳定能量同时存在时，短时强降水风险升高。"],
        "inputs": ["q850", "tcwv", "div850", "w700", "kindex", "cape", "rain6"],
    },
    "thunderstorm_gale": {
        "title": "雷暴大风/下击暴流",
        "purpose": "综合 DCAPE、深层风切变、CAPE、中层干冷和低层触发，输出雷暴大风/下击暴流风险评分。",
        "basis": ["强下沉潜势、足够不稳定和风切变配合时，雷暴大风或下击暴流风险升高。"],
        "inputs": ["cape", "dcape", "shr850-200", "div850", "div200/div300"],
    },
    "hail": {
        "title": "冰雹",
        "purpose": "综合 CAPE、深层风切变、LI 和冷性层结代理指标，输出冰雹风险评分。",
        "basis": ["较强不稳定、组织化风切变和冷性中层环境配合时，冰雹风险升高。"],
        "inputs": ["cape", "shr850-200", "li"],
    },
    "rotating_storm_or_supercell": {
        "title": "旋转风暴/超级单体潜势",
        "purpose": "综合 CAPE、深层风切变、低层切变或 SRH，输出旋转风暴/超级单体组织潜势评分。",
        "basis": ["不稳定能量、深层风切变和低层旋转环境配合时，旋转风暴组织潜势升高。"],
        "inputs": ["cape", "shr850-200", "srh"],
    },
    "severe_convection_composite": {
        "title": "强对流综合风险",
        "purpose": "综合短时强降水、雷暴大风、冰雹和旋转风暴风险，输出强对流综合风险评分。",
        "basis": ["强对流综合风险不替代单灾种风险，主要用于快速定位多灾种叠加或最强风险区。"],
        "inputs": [
            "risk_short_duration_heavy_rain_score",
            "risk_thunderstorm_gale_score",
            "risk_hail_score",
            "risk_rotating_storm_score",
        ],
    },
}

RISK_COMPOSITION_RULES = {
    "short_duration_heavy_rain": {
        "mode": "max",
        "label": "取较高风险通道",
        "formula": "max(降水型短时强降水通道, 对流型短时强降水通道)",
        "description": "短时强降水同时属于强降水风险和强对流风险，先分别计算降水型与对流型通道，再取较高值作为最终 source_grid。",
        "channels": [
            {
                "channel_id": "precip_short_duration_heavy_rain",
                "label": "降水型短时强降水通道",
                "field": "risk_precip_short_duration_heavy_rain_score",
                "basis": "低层水汽、整层可降水量、水汽辐合、低层辐合、上升运动、列车效应和短时雨强。",
                "weight": None,
            },
            {
                "channel_id": "conv_short_duration_heavy_rain",
                "label": "对流型短时强降水通道",
                "field": "risk_conv_short_duration_heavy_rain_score",
                "basis": "降水型基础叠加 CAPE/K 指数、CIN 可突破、触发条件、低层水汽和深层风切变。",
                "weight": None,
            },
        ],
    }
}

RISK_TARGET_ORDER = [
    "persistent_heavy_rain",
    "short_duration_heavy_rain",
    "thunderstorm_gale",
    "hail",
    "rotating_storm_or_supercell",
    "severe_convection_composite",
]

RISK_MATRIX_FEATURE_DEFAULTS = {
    "persistent_heavy_rain": {
        "feature_type": "persistent_heavy_rain_risk",
        "score_grid": "risk_persistent_heavy_rain_score",
        "score_threshold": 0.60,
        "high_score_threshold": 0.75,
        "min_area_grid_points": 12,
        "max_objects": 8,
    },
    "short_duration_heavy_rain": {
        "feature_type": "short_duration_heavy_rain_risk",
        "score_grid": "risk_short_duration_heavy_rain_score",
        "score_threshold": 0.60,
        "high_score_threshold": 0.75,
        "min_area_grid_points": 10,
        "max_objects": 8,
    },
    "thunderstorm_gale": {
        "feature_type": "thunderstorm_gale_risk",
        "score_grid": "risk_thunderstorm_gale_score",
        "score_threshold": 0.58,
        "high_score_threshold": 0.72,
        "min_area_grid_points": 10,
        "max_objects": 8,
    },
    "hail": {
        "feature_type": "hail_risk",
        "score_grid": "risk_hail_score",
        "score_threshold": 0.58,
        "high_score_threshold": 0.72,
        "min_area_grid_points": 8,
        "max_objects": 8,
    },
    "rotating_storm_or_supercell": {
        "feature_type": "rotating_storm_risk",
        "score_grid": "risk_rotating_storm_score",
        "score_threshold": 0.55,
        "high_score_threshold": 0.70,
        "min_area_grid_points": 8,
        "max_objects": 8,
    },
    "severe_convection_composite": {
        "feature_type": "severe_convection_composite_risk",
        "score_grid": "risk_severe_convection_composite_score",
        "score_threshold": 0.60,
        "high_score_threshold": 0.72,
        "min_area_grid_points": 10,
        "max_objects": 8,
    },
}

RISK_MATRIX_FACTOR_DEFAULTS = {
    "persistent_heavy_rain": [
        ("moisture_transport", "低层水汽输送", "moisture_flux850", 0.18),
        ("moisture_convergence", "水汽辐合", "moisture_flux_divergence850", 0.20),
        ("ascent", "700hPa 上升运动", "w700", 0.18),
        ("deep_moisture", "深厚湿层", "deep_moisture_score", 0.14),
        ("low_level_convergence", "低层辐合", "div850", 0.10),
        ("model_precip", "模式累计降水", "model_precip_score", 0.10),
        ("persistence", "持续性", "persistence_score", 0.07),
        ("system_support", "系统支持", "supporting_systems", 0.03),
    ],
    "short_duration_heavy_rain": [
        ("moisture", "低层水汽", "moisture_score", 0.18),
        ("moisture_convergence", "水汽辐合", "moisture_flux_divergence850", 0.18),
        ("low_level_convergence", "低层辐合", "div850", 0.12),
        ("ascent", "700hPa 上升运动", "w700", 0.12),
        ("instability", "对流能量", "instability_score", 0.10),
        ("k_index", "K 指数", "kindex", 0.08),
        ("training", "列车效应潜势", "training_score", 0.06),
        ("rainrate", "模式短时雨强", "rainrate_score", 0.04),
    ],
    "thunderstorm_gale": [
        ("storm_initiation", "雷暴发生潜势", "storm_initiation_score", 0.18),
        ("dcape", "DCAPE/下沉大风潜势", "dcape", 0.25),
        ("mid_dry", "中层干空气", "mid_dry_score", 0.17),
        ("deep_shear", "0-6km 风切变", "shr850-200", 0.18),
        ("upper_wind", "高空强风", "wind500", 0.10),
        ("linear_mode", "线状组织潜势", "front_or_shearline_score", 0.12),
    ],
    "hail": [
        ("cape", "CAPE", "cape", 0.22),
        ("deep_shear", "0-6km 风切变", "shr850-200", 0.22),
        ("mid_cold", "中层冷空气", "t500", 0.14),
        ("lapse_rate", "700-500hPa 递减率", "lapse_rate_700_500", 0.12),
        ("freezing_level", "0℃ 层高度", "freezing_level_m", 0.10),
        ("supercell_env", "超级单体环境", "supercell_env_score", 0.12),
        ("trigger", "触发条件", "trigger_score", 0.08),
    ],
    "rotating_storm_or_supercell": [
        ("cape", "CAPE", "cape", 0.18),
        ("deep_shear", "0-6km 风切变", "shr850-200", 0.28),
        ("low_level_shear", "0-1km 风切变", "shear_0_1km", 0.18),
        ("srh", "风暴相对螺旋度", "srh", 0.16),
        ("lcl", "LCL 云底高度", "lcl_m", 0.08),
        ("cin_breakable", "CIN 可突破", "cin", 0.05),
        ("trigger", "触发条件", "trigger_score", 0.05),
        ("discrete_storm", "离散单体环境", "discrete_storm_score", 0.02),
    ],
    "severe_convection_composite": [
        ("short_duration_heavy_rain", "短时强降水", "risk_short_duration_heavy_rain_score", 0.25),
        ("thunderstorm_gale", "雷暴大风/下击暴流", "risk_thunderstorm_gale_score", 0.25),
        ("hail", "冰雹", "risk_hail_score", 0.25),
        ("rotating_storm", "旋转风暴/超级单体潜势", "risk_rotating_storm_score", 0.25),
    ],
}

RISK_MATRIX_FIELD_COMPONENTS = {
    ("persistent_heavy_rain", "deep_moisture"): [
        ("rh850", "rh850", "850hPa 相对湿度", 0.36),
        ("rh700", "rh700", "700hPa 相对湿度", 0.36),
        ("rh500", "rh500", "500hPa 相对湿度", 0.28),
    ],
    ("persistent_heavy_rain", "model_precip"): [
        ("rain6", "rain6", "6h 累计降水", 0.50),
        ("rain24", "rain24", "24h 累计降水", 0.50),
    ],
    ("short_duration_heavy_rain", "moisture"): [
        ("q850", "q850", "850hPa 比湿", 0.35),
        ("td2m", "td2m", "2m 露点", 0.25),
        ("tcwv", "tcwv", "整层可降水量", 0.25),
        ("rh850", "rh850", "850hPa 相对湿度", 0.15),
    ],
    ("short_duration_heavy_rain", "instability"): [
        ("cape", "cape", "CAPE", 0.45),
        ("kindex", "kindex", "K 指数", 0.35),
        ("li", "li", "抬升指数", 0.20),
    ],
    ("short_duration_heavy_rain", "training"): [
        ("persistence", "persistence_score", "持续性", 0.40),
        ("moisture_convergence", "moisture_flux_divergence850", "水汽辐合", 0.40),
        ("slow_motion", "mean_wind_850_500", "系统慢移", 0.20),
    ],
    ("short_duration_heavy_rain", "rainrate"): [
        ("rain1", "rain1", "1h 雨强", 1.0 / 3.0),
        ("rain3", "rain3", "3h 雨强", 1.0 / 3.0),
        ("rain6", "rain6", "6h 雨强", 1.0 / 3.0),
    ],
    ("thunderstorm_gale", "storm_initiation"): [
        ("instability", "instability_score", "对流能量", 0.35),
        ("moisture", "moisture_score", "低层水汽", 0.20),
        ("cin_breakable", "cin", "CIN 可突破", 0.15),
        ("trigger", "trigger_score", "触发条件", 0.20),
        ("deep_shear", "shr850-200", "深层风切变", 0.10),
    ],
    ("thunderstorm_gale", "mid_dry"): [
        ("rh700", "rh700", "700hPa 中层干空气", 0.55),
        ("rh500", "rh500", "500hPa 中层干空气", 0.45),
    ],
    ("hail", "supercell_env"): [
        ("cape", "cape", "CAPE", 0.30),
        ("deep_shear", "shr850-200", "深层风切变", 0.40),
        ("low_level_shear", "shear_0_1km", "低层风切变", 0.15),
        ("trigger", "trigger_score", "触发条件", 0.15),
    ],
    ("hail", "trigger"): [
        ("div850", "div850", "低层辐合", 0.25),
        ("moisture_convergence", "moisture_flux_divergence850", "水汽辐合", 0.25),
        ("pva", "pva500", "正涡度平流", 0.25),
        ("upper_divergence", "upper_divergence", "高空辐散", 0.25),
    ],
    ("rotating_storm_or_supercell", "trigger"): [
        ("div850", "div850", "低层辐合", 0.25),
        ("moisture_convergence", "moisture_flux_divergence850", "水汽辐合", 0.25),
        ("pva", "pva500", "正涡度平流", 0.25),
        ("upper_divergence", "upper_divergence", "高空辐散", 0.25),
    ],
}

RISK_SCORING_FIELD_RULES = {
    "q850": ("q850_gkg", "ramp", "g/kg"),
    "td2m": ("td2m_c", "ramp", "degC"),
    "tcwv": ("pw_mm", "ramp", "mm"),
    "pw": ("pw_mm", "ramp", "mm"),
    "rh850": ("rh850", "ramp", "%"),
    "rh700": ("rh700", "ramp", "%"),
    "rh500": ("rh500", "ramp", "%"),
    "moisture_flux850": ("moisture_flux850", "ramp", ""),
    "cape": ("cape", "ramp", "J/kg"),
    "kindex": ("k_index", "ramp", "degC"),
    "k_index": ("k_index", "ramp", "degC"),
    "li": ("li", "negative_ratio", "degC"),
    "shr850-200": ("deep_shear_ms", "ramp", "m/s"),
    "deep_shear": ("deep_shear_ms", "ramp", "m/s"),
    "shear_0_1km": ("low_level_shear_ms", "ramp", "m/s"),
    "dcape": ("dcape", "ramp", "J/kg"),
    "wind500": ("wind500_ms", "ramp", "m/s"),
    "t500": ("t500_c", "negative_ratio", "degC"),
    "lapse_rate_700_500": ("lapse_rate_700_500", "ramp", "degC/km"),
    "lcl_m": ("lcl_m", "negative_ratio", "m"),
    "srh": ("srh", "ramp", "m2/s2"),
    "rain1": ("precip_1h_mm", "ramp", "mm"),
    "rain3": ("precip_3h_mm", "ramp", "mm"),
    "rain6": ("precip_6h_mm", "ramp", "mm"),
    "rain24": ("precip_24h_mm", "ramp", "mm"),
    "mean_wind_850_500": ("mean_wind_850_500_ms", "negative_ratio", "m/s"),
}

RISK_FACTOR_FIELD_RULE_OVERRIDES = {
    ("mid_dry", "rh700"): ("mid_dry_rh700", "negative_ratio", "%"),
    ("mid_dry", "rh500"): ("mid_dry_rh500", "negative_ratio", "%"),
}


def _risk_physical_category(factor: str, field: str) -> str:
    text = f"{factor}.{field}".lower()
    if "risk_" in text:
        return "综合风险"
    if any(token in text for token in ["q850", "tcwv", "td2m", "rh", "moisture", "precipitable_water", "mid_dry"]):
        return "水汽条件"
    if any(token in text for token in ["rain", "precip_"]):
        return "降水条件"
    if any(token in text for token in ["cape", "cin", "kindex", "li", "dcape", "lapse_rate", "t500", "freezing", "lcl", "instability", "mid_cold"]):
        return "热力条件"
    if any(token in text for token in ["div", "vort", "w700", "omega", "wind", "shear", "srh", "pvadv", "upper", "convergence"]):
        return "动力条件"
    return "系统支持"


def _risk_threshold_entry(
    target: str,
    suffix: str,
    *,
    signal: str,
    statistic: str,
    operator: str,
    threshold: float,
    unit: str,
    field: str | None = None,
    scale: float | None = None,
    weight: float | None = None,
    physical_category: str | None = None,
) -> dict:
    feature = RISK_MATRIX_FEATURE_DEFAULTS[target]
    entry = {
        "entry_id": f"risk.{target}.{suffix}",
        "group": RISK_RULE_SPECS[target]["title"],
        "target": target,
        "field": field or feature["score_grid"],
        "signal": signal,
        "statistic": statistic,
        "operator": operator,
        "threshold": threshold,
        "scale": scale,
        "weight": weight,
        "unit": unit,
        "enabled": True,
        "source": feature["feature_type"],
    }
    if physical_category:
        entry["physical_category"] = physical_category
    return entry


def _risk_scoring_threshold_meta(factor: str, field: str) -> dict | None:
    key_operator_unit = RISK_FACTOR_FIELD_RULE_OVERRIDES.get((factor, field)) or RISK_SCORING_FIELD_RULES.get(field)
    if not key_operator_unit:
        return None
    key, operator, unit = key_operator_unit
    rule = DEFAULT_RISK_SCORING.get("common", {}).get(key)
    if not rule:
        return None
    if operator == "negative_ratio":
        high = float(rule.get("high", 0.0))
        low = float(rule.get("low", 0.0))
        return {
            "operator": "negative_ratio",
            "threshold": high,
            "scale": abs(high - low),
            "unit": unit,
        }
    if "low" in rule and "high" in rule:
        low = float(rule["low"])
        high = float(rule["high"])
        return {
            "operator": "ramp",
            "threshold": low,
            "scale": abs(high - low),
            "unit": unit,
        }
    if {"min", "max"} <= set(rule):
        min_v = float(rule["min"])
        max_v = float(rule["max"])
        return {
            "operator": "triangular",
            "threshold": min_v,
            "scale": abs(max_v - min_v),
            "unit": unit,
        }
    return None


def _risk_weight_entry(target: str, factor: str, signal: str, field: str, weight: float) -> dict:
    meta = _risk_scoring_threshold_meta(factor, field) or {}
    return _risk_threshold_entry(
        target,
        f"weight.{factor}",
        signal=signal,
        statistic="factor_score" if meta else "factor_weight",
        operator=meta.get("operator", "weight"),
        threshold=meta.get("threshold"),
        scale=meta.get("scale"),
        unit=meta.get("unit", "ratio"),
        field=field,
        weight=weight,
        physical_category=_risk_physical_category(factor, field),
    )


def _fallback_field_components(field: str) -> list[tuple[str, str, str, float]]:
    parts = [part.strip() for part in str(field).split("/") if part.strip()]
    if len(parts) <= 1:
        return []
    ratio = 1.0 / len(parts)
    return [(part.replace("-", "_"), part, part, ratio) for part in parts]


def _risk_weight_entries(target: str, factor: str, signal: str, field: str, weight: float) -> list[dict]:
    components = RISK_MATRIX_FIELD_COMPONENTS.get((target, factor)) or _fallback_field_components(field)
    if not components:
        return [_risk_weight_entry(target, factor, signal, field, weight)]
    entries = []
    for component_key, component_field, component_signal, ratio in components:
        component_weight = round(float(weight) * float(ratio), 6)
        meta = _risk_scoring_threshold_meta(factor, component_field) or {}
        entries.append(
            _risk_threshold_entry(
                target,
                f"weight.{factor}.{component_key}",
                signal=f"{signal}：{component_signal}",
                statistic="factor_component_score" if meta else "factor_component_weight",
                operator=meta.get("operator", "weight"),
                threshold=meta.get("threshold"),
                scale=meta.get("scale"),
                unit=meta.get("unit", "ratio"),
                field=component_field,
                weight=component_weight,
                physical_category=_risk_physical_category(factor, component_field),
            )
        )
    return entries


def _risk_threshold_entries() -> list[dict]:
    entries: list[dict] = []
    for target in RISK_TARGET_ORDER:
        feature = RISK_MATRIX_FEATURE_DEFAULTS[target]
        entries.extend(
            [
                _risk_threshold_entry(
                    target,
                    "score_threshold",
                    signal="风险区起算评分",
                    statistic="score",
                    operator=">=",
                    threshold=feature["score_threshold"],
                    unit="0-1",
                ),
                _risk_threshold_entry(
                    target,
                    "high_score_threshold",
                    signal="高风险核心评分",
                    statistic="score",
                    operator=">=",
                    threshold=feature["high_score_threshold"],
                    unit="0-1",
                ),
                _risk_threshold_entry(
                    target,
                    "min_area_grid_points",
                    signal="风险区最小连续格点数",
                    statistic="count",
                    operator=">=",
                    threshold=float(feature["min_area_grid_points"]),
                    unit="grid",
                ),
                _risk_threshold_entry(
                    target,
                    "max_objects",
                    signal="最大输出风险区数",
                    statistic="rank",
                    operator="<=",
                    threshold=float(feature["max_objects"]),
                    unit="object",
                ),
            ]
        )
        for factor, signal, field, weight in RISK_MATRIX_FACTOR_DEFAULTS[target]:
            entries.extend(_risk_weight_entries(target, factor, signal, field, weight))
    return entries


def _risk_threshold_entry_ids(target: str) -> list[str]:
    return [
        f"risk.{target}.score_threshold",
        f"risk.{target}.high_score_threshold",
        f"risk.{target}.min_area_grid_points",
        f"risk.{target}.max_objects",
        *[
            entry["entry_id"]
            for factor, signal, field, weight in RISK_MATRIX_FACTOR_DEFAULTS[target]
            for entry in _risk_weight_entries(target, factor, signal, field, weight)
        ],
    ]


class ThresholdMatrixError(Exception):
    def __init__(self, msg: str, *, status_code: int = 400, data: dict | None = None):
        super().__init__(msg)
        self.msg = msg
        self.status_code = status_code
        self.data = data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ALGORITHM_CATALOG = [
    {
        "algorithm_id": ALGORITHM_ID,
        "name": "NAFP 天气形势诊断",
        "model": "ECMWF / EC",
        "domain": "synoptic_situation",
        "status": "enabled",
        "inputs": [
            {"field": "gh500", "required": True, "role": "500hPa 位势高度基础场"},
            {"field": "uv500", "required": False, "role": "500hPa 风场，用于相对涡度"},
            {"field": "uv850", "required": False, "role": "低空风和水汽输送"},
            {"field": "q850", "required": False, "role": "低层水汽"},
            {"field": "div850", "required": False, "role": "低层辐合"},
            {"field": "tt850", "required": False, "role": "850hPa 温度、锋面和相态"},
            {"field": "w700", "required": False, "role": "垂直运动"},
            {"field": "kindex", "required": False, "role": "热力不稳定"},
            {"field": "cape", "required": False, "role": "对流有效位能"},
            {"field": "rain6", "required": False, "role": "模式 6 小时降水"},
            {"field": "pv300", "required": False, "role": "高空 PV 支持"},
        ],
        "systems": [
            {
                "system_id": "subtropical_high_500",
                "name": "500hPa 副热带高压",
                "fields": ["gh500"],
                "method": "连续区域阈值识别",
            },
            {
                "system_id": "trough_ridge_500",
                "name": "500hPa 槽脊候选",
                "fields": ["gh500", "uv500"],
                "method": "纬向距平尾部、等高线曲率和 500hPa 涡度支撑轴线识别",
            },
            {
                "system_id": "low_pressure_convergence_500",
                "name": "低压辐合候选",
                "fields": ["gh500", "div850"],
                "method": "500hPa 高度负距平与 850hPa 低层辐合叠加识别",
            },
            {
                "system_id": "high_pressure_divergence_500",
                "name": "高压辐散候选",
                "fields": ["gh500", "div850"],
                "method": "500hPa 高度正距平与 850hPa 低层辐散叠加识别",
            },
            {
                "system_id": "low_level_jet_850",
                "name": "850hPa 低空急流候选",
                "fields": ["uv850", "q850"],
                "method": "850hPa 风速高值与水汽通量高值叠加识别",
            },
            {
                "system_id": "moisture_transport_850",
                "name": "850hPa 水汽输送带候选",
                "fields": ["uv850", "q850"],
                "method": "850hPa 水汽通量高值带识别",
            },
            {
                "system_id": "moisture_convergence_850",
                "name": "850hPa 水汽辐合区候选",
                "fields": ["uv850", "q850"],
                "method": "水汽通量散度低值区识别",
            },
            {
                "system_id": "front_candidate_850",
                "name": "850hPa 锋面候选",
                "fields": ["tt850", "uv850", "div850", "ttadv850", "rh850"],
                "method": "温度梯度、风场形变、锋生函数、低层辐合和温度平流综合识别",
            },
        ],
        "evidence_chains": [
            {
                "chain_id": "heavy_rain_potential",
                "name": "强降水潜势",
                "target": "heavy_rain_potential",
                "method": "水汽、辐合、抬升、降水预报加权评分",
            },
            {
                "chain_id": "convection_potential",
                "name": "强对流潜势",
                "target": "convection_potential",
                "method": "不稳定能量、抬升触发、深层切变和高空支持加权评分",
            },
            {
                "chain_id": "persistent_heavy_rain",
                "name": "持续性强降水",
                "target": "persistent_heavy_rain",
                "method": "水汽输送、水汽辐合、上升运动和累计降水综合评分",
            },
            {
                "chain_id": "short_duration_heavy_rain",
                "name": "短时强降水",
                "target": "short_duration_heavy_rain",
                "method": "低层水汽、CAPE/K指数、低层触发和水汽辐合综合评分",
            },
            {
                "chain_id": "thunderstorm_gale",
                "name": "雷暴大风/下击暴流",
                "target": "thunderstorm_gale",
                "method": "DCAPE、深层风切变、CAPE和低层触发综合评分",
            },
            {
                "chain_id": "hail",
                "name": "冰雹",
                "target": "hail",
                "method": "CAPE、深层风切变和冷性层结代理指标综合评分",
            },
            {
                "chain_id": "rotating_storm_or_supercell",
                "name": "旋转风暴/超级单体潜势",
                "target": "rotating_storm_or_supercell",
                "method": "CAPE、深层风切变、低层切变或SRH综合评分",
            },
            {
                "chain_id": "severe_convection_composite",
                "name": "强对流综合风险",
                "target": "severe_convection_composite",
                "method": "短时强降水、雷暴大风/下击暴流、冰雹和旋转风暴风险综合取大值",
            },
            {
                "chain_id": "dynamic_lift_potential",
                "name": "动力抬升潜势",
                "target": "dynamic_lift_potential",
                "method": "低层辐合、700hPa 上升、500hPa 涡度、高空辐散和 PV 平流加权评分",
            },
            {
                "chain_id": "precipitation_phase",
                "name": "雨雪相态初判",
                "target": "precipitation_phase",
                "method": "地面温度、925/850hPa 温度和湿球 0℃ 层高度综合判断",
            },
        ],
    }
]


DEFAULT_THRESHOLD_MATRIX = {
    "matrix_id": DEFAULT_MATRIX_ID,
    "algorithm_id": ALGORITHM_ID,
    "name": "NAFP 业务默认阈值矩阵",
    "status": "default",
    "updated_at": "2026-06-18T00:00:00+00:00",
    "updated_by": "system",
    "remark": "从当前 NAFP 天气形势诊断算法硬编码阈值抽取，用于后台管理。",
    "level_thresholds": [
        {"level": "high", "score_gte": 0.7, "label": "高"},
        {"level": "moderate", "score_gte": 0.45, "label": "中"},
        {"level": "low", "score_gte": 0.0, "label": "低"},
    ],
    "entries": [
        {
            "entry_id": "system.subtropical_high.gh500_dam",
            "group": "天气系统",
            "target": "subtropical_high_500",
            "field": "gh500",
            "signal": "500hPa 位势高度连续区",
            "statistic": "value",
            "operator": ">=",
            "threshold": 588.0,
            "scale": None,
            "weight": None,
            "unit": "dagpm",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.subtropical_high.gh500_gpm",
            "group": "天气系统",
            "target": "subtropical_high_500",
            "field": "gh500",
            "signal": "500hPa 位势高度连续区",
            "statistic": "value",
            "operator": ">=",
            "threshold": 5880.0,
            "scale": None,
            "weight": None,
            "unit": "gpm",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.subtropical_high.min_points",
            "group": "天气系统",
            "target": "subtropical_high_500",
            "field": "gh500",
            "signal": "连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 20.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.trough_candidate.anomaly_percentile",
            "group": "天气系统",
            "target": "trough_candidate_500",
            "field": "gh500_anomaly",
            "signal": "槽线候选距平低值分位数",
            "statistic": "percentile",
            "operator": "<=",
            "threshold": 8.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.ridge_candidate.anomaly_percentile",
            "group": "天气系统",
            "target": "ridge_candidate_500",
            "field": "gh500_anomaly",
            "signal": "脊线候选距平高值分位数",
            "statistic": "percentile",
            "operator": ">=",
            "threshold": 92.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.trough_ridge.min_points",
            "group": "天气系统",
            "target": "trough_ridge_500",
            "field": "gh500_anomaly",
            "signal": "槽脊候选连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 24.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "diagnose_systems",
        },
        {
            "entry_id": "system.trough_ridge.axis_anomaly_percentile",
            "group": "天气系统",
            "target": "trough_ridge_axis_500",
            "field": "gh500_anomaly",
            "signal": "槽脊轴线距平尾部分位",
            "statistic": "axis_percentile",
            "operator": "tail_percentile",
            "threshold": 20.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_trough_ridge_axis_systems",
        },
        {
            "entry_id": "system.trough_ridge.curvature_percentile",
            "group": "天气系统",
            "target": "trough_ridge_axis_500",
            "field": "gh500_curvature",
            "signal": "槽脊轴线曲率支撑分位",
            "statistic": "curvature_percentile",
            "operator": ">=",
            "threshold": 55.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_trough_ridge_axis_systems",
        },
        {
            "entry_id": "system.trough_ridge.vorticity_support",
            "group": "天气系统",
            "target": "trough_ridge_axis_500",
            "field": "vorticity500",
            "signal": "槽脊轴线涡度符号支撑",
            "statistic": "signed_mean",
            "operator": ">=",
            "threshold": 0.0,
            "scale": None,
            "weight": None,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_trough_ridge_axis_systems",
        },
        {
            "entry_id": "system.trough_ridge.min_points_per_line",
            "group": "天气系统",
            "target": "trough_ridge_axis_500",
            "field": "gh500_anomaly",
            "signal": "槽脊轴线最小连续纬向点数",
            "statistic": "line_point_count",
            "operator": ">=",
            "threshold": 4.0,
            "scale": None,
            "weight": None,
            "unit": "point",
            "enabled": True,
            "source": "_trough_ridge_axis_systems",
        },
        {
            "entry_id": "system.trough_ridge.max_lines",
            "group": "天气系统",
            "target": "trough_ridge_axis_500",
            "field": "gh500_anomaly",
            "signal": "槽脊轴线最大输出条数",
            "statistic": "line_rank",
            "operator": "<=",
            "threshold": 8.0,
            "scale": None,
            "weight": None,
            "unit": "line",
            "enabled": True,
            "source": "_trough_ridge_axis_systems",
        },
        {
            "entry_id": "system.low_pressure.gh500_anomaly_percentile",
            "group": "天气系统",
            "target": "low_pressure_convergence_500",
            "field": "gh500_anomaly",
            "signal": "低压候选高度负距平分位",
            "statistic": "p20",
            "operator": "<=",
            "threshold": 20.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.low_pressure.div850_convergence_percentile",
            "group": "天气系统",
            "target": "low_pressure_convergence_500",
            "field": "div850",
            "signal": "低压候选低层辐合分位",
            "statistic": "p10",
            "operator": "<=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.high_pressure.gh500_anomaly_percentile",
            "group": "天气系统",
            "target": "high_pressure_divergence_500",
            "field": "gh500_anomaly",
            "signal": "高压候选高度正距平分位",
            "statistic": "p80",
            "operator": ">=",
            "threshold": 80.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.high_pressure.div850_divergence_percentile",
            "group": "天气系统",
            "target": "high_pressure_divergence_500",
            "field": "div850",
            "signal": "高压候选低层辐散分位",
            "statistic": "p90",
            "operator": ">=",
            "threshold": 90.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.pressure_center.min_points",
            "group": "天气系统",
            "target": "pressure_center_500_850",
            "field": "pressure_center_mask",
            "signal": "低压/高压候选连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.pressure_center.max_centers",
            "group": "天气系统",
            "target": "pressure_center_500_850",
            "field": "pressure_center_mask",
            "signal": "低压/高压候选最大输出个数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 6.0,
            "scale": None,
            "weight": None,
            "unit": "center",
            "enabled": True,
            "source": "_pressure_center_systems",
        },
        {
            "entry_id": "system.front_candidate.tt850_gradient_percentile",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "tt850",
            "signal": "850hPa 温度梯度高值分位",
            "statistic": "gradient_p80",
            "operator": ">=",
            "threshold": 80.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.front_candidate.score_percentile",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "front_candidate_score",
            "signal": "锋面候选综合评分高值分位",
            "statistic": "p82",
            "operator": ">=",
            "threshold": 82.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.front_candidate.dynamic_support_percentile",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "frontogenesis850/front_deformation850",
            "signal": "锋面动力支撑高值分位",
            "statistic": "p70",
            "operator": ">=",
            "threshold": 70.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.front_candidate.min_support_components",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "front_support_count",
            "signal": "锋面动力支撑最少项数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 1.0,
            "scale": None,
            "weight": None,
            "unit": "component",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.front_candidate.max_objects",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "front_candidate_score",
            "signal": "锋面候选最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.front_candidate.min_points",
            "group": "天气系统",
            "target": "front_candidate_850",
            "field": "front_candidate_score",
            "signal": "锋面候选连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_front_candidate_systems",
        },
        {
            "entry_id": "system.low_level_jet.wind_speed_min",
            "group": "天气系统",
            "target": "low_level_jet_850",
            "field": "uv850_speed",
            "signal": "850hPa 风速下限",
            "statistic": "max",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "m/s",
            "enabled": True,
            "source": "_low_level_jet_systems",
        },
        {
            "entry_id": "system.low_level_jet.moisture_flux_percentile",
            "group": "天气系统",
            "target": "low_level_jet_850",
            "field": "moisture_flux850",
            "signal": "低空急流水汽通量高值分位",
            "statistic": "p70",
            "operator": ">=",
            "threshold": 70.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_low_level_jet_systems",
        },
        {
            "entry_id": "system.low_level_jet.min_points",
            "group": "天气系统",
            "target": "low_level_jet_850",
            "field": "uv850_speed",
            "signal": "低空急流候选连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 8.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_low_level_jet_systems",
        },
        {
            "entry_id": "system.low_level_jet.min_direction_coherence",
            "group": "天气系统",
            "target": "low_level_jet_850",
            "field": "uv850",
            "signal": "低空急流风向一致性下限",
            "statistic": "coherence",
            "operator": ">=",
            "threshold": 0.65,
            "scale": None,
            "weight": None,
            "unit": "ratio",
            "enabled": True,
            "source": "_low_level_jet_systems",
        },
        {
            "entry_id": "system.low_level_jet.max_objects",
            "group": "天气系统",
            "target": "low_level_jet_850",
            "field": "uv850_speed",
            "signal": "低空急流最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_low_level_jet_systems",
        },
        {
            "entry_id": "system.moisture_transport.flux_percentile",
            "group": "天气系统",
            "target": "moisture_transport_850",
            "field": "moisture_flux850",
            "signal": "850hPa 水汽通量高值分位",
            "statistic": "p75",
            "operator": ">=",
            "threshold": 75.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_moisture_transport_systems",
        },
        {
            "entry_id": "system.moisture_transport.min_points",
            "group": "天气系统",
            "target": "moisture_transport_850",
            "field": "moisture_flux850",
            "signal": "水汽输送带连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_moisture_transport_systems",
        },
        {
            "entry_id": "system.moisture_transport.min_direction_coherence",
            "group": "天气系统",
            "target": "moisture_transport_850",
            "field": "uv850",
            "signal": "水汽输送带风向一致性下限",
            "statistic": "coherence",
            "operator": ">=",
            "threshold": 0.65,
            "scale": None,
            "weight": None,
            "unit": "ratio",
            "enabled": True,
            "source": "_moisture_transport_systems",
        },
        {
            "entry_id": "system.moisture_transport.max_objects",
            "group": "天气系统",
            "target": "moisture_transport_850",
            "field": "moisture_flux850",
            "signal": "水汽输送带最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_moisture_transport_systems",
        },
        {
            "entry_id": "system.moisture_convergence.flux_divergence_percentile",
            "group": "天气系统",
            "target": "moisture_convergence_850",
            "field": "moisture_flux_divergence850",
            "signal": "水汽通量散度低值分位",
            "statistic": "p10",
            "operator": "<=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_moisture_convergence_systems",
        },
        {
            "entry_id": "system.moisture_convergence.moisture_flux_percentile",
            "group": "天气系统",
            "target": "moisture_convergence_850",
            "field": "moisture_flux850",
            "signal": "水汽辐合区通量配合分位",
            "statistic": "p55",
            "operator": ">=",
            "threshold": 55.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_moisture_convergence_systems",
        },
        {
            "entry_id": "system.moisture_convergence.min_points",
            "group": "天气系统",
            "target": "moisture_convergence_850",
            "field": "moisture_flux_divergence850",
            "signal": "水汽辐合候选连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_moisture_convergence_systems",
        },
        {
            "entry_id": "system.moisture_convergence.smoothing_sigma_grid",
            "group": "天气系统",
            "target": "moisture_convergence_850",
            "field": "moisture_flux_divergence850",
            "signal": "水汽辐合散度平滑尺度",
            "statistic": "sigma",
            "operator": ">=",
            "threshold": 1.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_moisture_convergence_systems",
        },
        {
            "entry_id": "system.moisture_convergence.max_objects",
            "group": "天气系统",
            "target": "moisture_convergence_850",
            "field": "moisture_flux_divergence850",
            "signal": "水汽辐合区最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_moisture_convergence_systems",
        },
        {
            "entry_id": "system.low_level_convergence.div850_percentile",
            "group": "天气系统",
            "target": "low_level_convergence_850",
            "field": "div850",
            "signal": "850hPa 散度低值分位",
            "statistic": "p10",
            "operator": "<=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_low_level_convergence_systems",
        },
        {
            "entry_id": "system.low_level_convergence.min_points",
            "group": "天气系统",
            "target": "low_level_convergence_850",
            "field": "div850",
            "signal": "低层辐合区连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_low_level_convergence_systems",
        },
        {
            "entry_id": "system.low_level_convergence.smoothing_sigma_grid",
            "group": "天气系统",
            "target": "low_level_convergence_850",
            "field": "div850",
            "signal": "低层辐合散度平滑尺度",
            "statistic": "sigma",
            "operator": ">=",
            "threshold": 1.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_low_level_convergence_systems",
        },
        {
            "entry_id": "system.low_level_convergence.max_objects",
            "group": "天气系统",
            "target": "low_level_convergence_850",
            "field": "div850",
            "signal": "低层辐合区最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_low_level_convergence_systems",
        },
        {
            "entry_id": "system.upper_divergence.divergence_percentile",
            "group": "天气系统",
            "target": "upper_divergence",
            "field": "div200/div300",
            "signal": "高空散度高值分位",
            "statistic": "p90",
            "operator": ">=",
            "threshold": 90.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_upper_divergence_systems",
        },
        {
            "entry_id": "system.upper_divergence.smoothing_sigma_grid",
            "group": "天气系统",
            "target": "upper_divergence",
            "field": "div200/div300",
            "signal": "高空辐散散度平滑尺度",
            "statistic": "sigma",
            "operator": ">=",
            "threshold": 1.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_upper_divergence_systems",
        },
        {
            "entry_id": "system.upper_divergence.max_objects",
            "group": "天气系统",
            "target": "upper_divergence",
            "field": "div200/div300",
            "signal": "高空辐散区最大输出对象数",
            "statistic": "rank",
            "operator": "<=",
            "threshold": 12.0,
            "scale": None,
            "weight": None,
            "unit": "object",
            "enabled": True,
            "source": "_upper_divergence_systems",
        },
        {
            "entry_id": "system.upper_divergence.min_points",
            "group": "天气系统",
            "target": "upper_divergence",
            "field": "div200/div300",
            "signal": "高空辐散区连续区最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 10.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_upper_divergence_systems",
        },
        {
            "entry_id": "region.risk.percentile",
            "group": "风险区域",
            "target": "evidence_chain_region",
            "field": "composite_risk",
            "signal": "证据链风险区域分位阈值",
            "statistic": "percentile",
            "operator": ">=",
            "threshold": 85.0,
            "scale": None,
            "weight": None,
            "unit": "%",
            "enabled": True,
            "source": "_risk_region_from_arrays",
        },
        {
            "entry_id": "region.risk.min_points",
            "group": "风险区域",
            "target": "evidence_chain_region",
            "field": "composite_risk",
            "signal": "风险区域最小格点数",
            "statistic": "count",
            "operator": ">=",
            "threshold": 16.0,
            "scale": None,
            "weight": None,
            "unit": "grid",
            "enabled": True,
            "source": "_risk_region_from_arrays",
        },
        {
            "entry_id": "heavy_rain.q850",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "q850",
            "signal": "低层水汽",
            "statistic": "p75",
            "operator": "ramp",
            "threshold": 8.0,
            "scale": 8.0,
            "weight": 0.18,
            "unit": "g/kg",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.tcwv",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "tcwv",
            "signal": "整层可降水量",
            "statistic": "p75",
            "operator": "ramp",
            "threshold": 30.0,
            "scale": 35.0,
            "weight": 0.12,
            "unit": "mm",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.moisture_flux850",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "moisture_flux850",
            "signal": "低层水汽输送",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 220.0,
            "weight": 0.18,
            "unit": "",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.div850",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "div850",
            "signal": "低层辐合",
            "statistic": "p10",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 25.0,
            "weight": 0.16,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.w700",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "w700",
            "signal": "700hPa 上升运动",
            "statistic": "p10",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 8.0,
            "weight": 0.16,
            "unit": "",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.kindex",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "kindex",
            "signal": "对流不稳定",
            "statistic": "p75",
            "operator": "ramp",
            "threshold": 25.0,
            "scale": 15.0,
            "weight": 0.1,
            "unit": "degC",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.cape",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "cape",
            "signal": "CAPE 支持",
            "statistic": "p75",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 1500.0,
            "weight": 0.08,
            "unit": "J/kg",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "heavy_rain.rain6",
            "group": "强降水潜势",
            "target": "heavy_rain_potential",
            "field": "rain6",
            "signal": "模式 6 小时降水",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 25.0,
            "weight": 0.12,
            "unit": "mm",
            "enabled": True,
            "source": "_heavy_rain_chain",
        },
        {
            "entry_id": "convection.cape",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "cape",
            "signal": "不稳定能量",
            "statistic": "p75",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 1800.0,
            "weight": 0.22,
            "unit": "J/kg",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.cin",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "cin",
            "signal": "抑制能量不强",
            "statistic": "p50",
            "operator": "inverse_abs_ratio",
            "threshold": 200.0,
            "scale": 200.0,
            "weight": 0.08,
            "unit": "J/kg",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.kindex",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "kindex",
            "signal": "热力不稳定",
            "statistic": "p75",
            "operator": "ramp",
            "threshold": 25.0,
            "scale": 15.0,
            "weight": 0.12,
            "unit": "degC",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.shr850_200",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "shr850-200",
            "signal": "深层垂直风切变",
            "statistic": "p75",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 25.0,
            "weight": 0.16,
            "unit": "m/s",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.q850",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "q850",
            "signal": "低层水汽",
            "statistic": "p75",
            "operator": "ramp",
            "threshold": 8.0,
            "scale": 8.0,
            "weight": 0.12,
            "unit": "g/kg",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.div850",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "div850",
            "signal": "低层触发",
            "statistic": "p10",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 25.0,
            "weight": 0.1,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.upper_divergence",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "div200/div300",
            "signal": "高空辐散",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 20.0,
            "weight": 0.1,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.pv300",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "pv300",
            "signal": "高空 PV 支持",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 5.0,
            "weight": 0.05,
            "unit": "PVU",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.pvadv300",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "pvadv300",
            "signal": "PV 平流支持",
            "statistic": "abs_p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 20.0,
            "weight": 0.05,
            "unit": "",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.li",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "li",
            "signal": "抬升指数",
            "statistic": "p25",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 8.0,
            "weight": 0.04,
            "unit": "degC",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.dcape",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "dcape",
            "signal": "下沉气流能量",
            "statistic": "p75",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 1200.0,
            "weight": 0.04,
            "unit": "J/kg",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "convection.srh",
            "group": "强对流潜势",
            "target": "convection_potential",
            "field": "srh",
            "signal": "风暴相对螺旋度",
            "statistic": "p75",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 180.0,
            "weight": 0.04,
            "unit": "m2/s2",
            "enabled": True,
            "source": "_convection_chain",
        },
        {
            "entry_id": "dynamic_lift.w700",
            "group": "动力抬升潜势",
            "target": "dynamic_lift_potential",
            "field": "w700",
            "signal": "700hPa 上升运动",
            "statistic": "p10",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 8.0,
            "weight": 0.24,
            "unit": "",
            "enabled": True,
            "source": "_dynamic_lift_chain",
        },
        {
            "entry_id": "dynamic_lift.vorticity500",
            "group": "动力抬升潜势",
            "target": "dynamic_lift_potential",
            "field": "vorticity500",
            "signal": "500hPa 正涡度",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 12.0,
            "weight": 0.2,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_dynamic_lift_chain",
        },
        {
            "entry_id": "dynamic_lift.div850",
            "group": "动力抬升潜势",
            "target": "dynamic_lift_potential",
            "field": "div850",
            "signal": "低层辐合",
            "statistic": "p10",
            "operator": "negative_ratio",
            "threshold": 0.0,
            "scale": 25.0,
            "weight": 0.2,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_dynamic_lift_chain",
        },
        {
            "entry_id": "dynamic_lift.upper_divergence",
            "group": "动力抬升潜势",
            "target": "dynamic_lift_potential",
            "field": "div200/div300",
            "signal": "高空辐散",
            "statistic": "p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 20.0,
            "weight": 0.2,
            "unit": "10^-5/s",
            "enabled": True,
            "source": "_dynamic_lift_chain",
        },
        {
            "entry_id": "dynamic_lift.pvadv300",
            "group": "动力抬升潜势",
            "target": "dynamic_lift_potential",
            "field": "pvadv300",
            "signal": "高空 PV 平流",
            "statistic": "abs_p90",
            "operator": "ratio",
            "threshold": 0.0,
            "scale": 20.0,
            "weight": 0.16,
            "unit": "",
            "enabled": True,
            "source": "_dynamic_lift_chain",
        },
        {
            "entry_id": "phase.t2m",
            "group": "雨雪相态",
            "target": "precipitation_phase",
            "field": "t2m",
            "signal": "2m 气温",
            "statistic": "p50",
            "operator": "<=",
            "threshold": 2.0,
            "scale": None,
            "weight": 0.25,
            "unit": "degC",
            "enabled": True,
            "source": "_phase_chain",
        },
        {
            "entry_id": "phase.tt850",
            "group": "雨雪相态",
            "target": "precipitation_phase",
            "field": "tt850",
            "signal": "850hPa 温度",
            "statistic": "p50",
            "operator": "<=",
            "threshold": 0.0,
            "scale": None,
            "weight": 0.25,
            "unit": "degC",
            "enabled": True,
            "source": "_phase_chain",
        },
        {
            "entry_id": "phase.tt925",
            "group": "雨雪相态",
            "target": "precipitation_phase",
            "field": "tt925",
            "signal": "925hPa 温度",
            "statistic": "p50",
            "operator": "<=",
            "threshold": 1.0,
            "scale": None,
            "weight": 0.25,
            "unit": "degC",
            "enabled": True,
            "source": "_phase_chain",
        },
        {
            "entry_id": "phase.tw0_height",
            "group": "雨雪相态",
            "target": "precipitation_phase",
            "field": "tw0_height",
            "signal": "湿球 0℃ 层高度",
            "statistic": "p50",
            "operator": "<=",
            "threshold": 600.0,
            "scale": None,
            "weight": 0.25,
            "unit": "m",
            "enabled": True,
            "source": "_phase_chain",
        },
    ],
}

def _is_legacy_support_entry(entry: dict) -> bool:
    entry_id = str(entry.get("entry_id") or "")
    target = str(entry.get("target") or "")
    return target in LEGACY_SUPPORT_TARGETS or entry_id.startswith(
        (
            "region.risk.",
            "heavy_rain.",
            "convection.",
            "dynamic_lift.",
            "phase.",
        )
    )


LEGACY_SUPPORT_THRESHOLD_ENTRIES = [
    deepcopy(entry)
    for entry in DEFAULT_THRESHOLD_MATRIX["entries"]
    if _is_legacy_support_entry(entry)
]
DEFAULT_THRESHOLD_MATRIX["entries"] = [
    entry
    for entry in DEFAULT_THRESHOLD_MATRIX["entries"]
    if not _is_legacy_support_entry(entry)
]
DEFAULT_THRESHOLD_MATRIX["entries"].extend(_risk_threshold_entries())


RULE_EXPLANATION_TEMPLATES = [
    {
        "rule_id": "subtropical_high_500",
        "title": "500hPa 副热带高压",
        "category": "天气系统",
        "purpose": "识别 500hPa 高度场中达到业务高度阈值且空间连续的副热带高压主体。",
        "basis": [
            "500hPa 位势高度使用 dagpm 或 gpm 双单位适配；最大值小于 1000 时按 dagpm 判读，否则按 gpm 判读。",
            "连续区域满足高度阈值后，再要求连通格点数达到最小面积门槛。",
            "输出对象保留主体中心、西伸脊点、南北界、面积格点数、最大/平均高度和主体形态。",
        ],
        "inputs": [
            {"field": "gh500", "required": True, "role": "500hPa 位势高度基础场"},
        ],
        "method": [
            "mask = gh500 >= threshold",
            "largest_component(mask, min_points) 选取满足面积约束的最大连续区",
            "在最西侧阈值区格点中选高度最高点作为西伸脊点",
            "统计 north_boundary_lat / south_boundary_lat / axis_orientation 供地图详情和证据链展示",
            "连通分量按格点 cell union 输出 polygon geometry，bbox 仅作为范围元数据",
        ],
        "threshold_entries": [
            "system.subtropical_high.gh500_dam",
            "system.subtropical_high.gh500_gpm",
            "system.subtropical_high.min_points",
        ],
        "outputs": [
            "systems.type = subtropical_high",
            "systems.feature_type = subtropical_high",
            "systems.geometry.type = polygon",
            "systems.ridge_point / center / north_boundary_lat / area_grid_points",
        ],
        "evidence_contract": [
            "field=gh500",
            "signal=height threshold area",
            "raw_value=max(gh500)",
            "rule_id 指向启用的高度阈值条目",
            "附加 system.subtropical_high.area_extent / ridge_point / north_boundary 证据",
        ],
    },
    {
        "rule_id": "trough_ridge_500",
        "title": "500hPa 槽脊候选",
        "category": "天气系统",
        "purpose": "从 500hPa 位势高度纬向距平中提取槽线、脊线及槽脊候选区。",
        "basis": [
            "先按纬向平均移除背景场，得到 gh500_anomaly。",
            "槽区使用低值分位，脊区使用高值分位，同时要求轴线位于等高线曲率支撑的连续槽脊带内。",
            "当 uv500 可用时，槽线要求正涡度支撑、脊线要求负涡度支撑，作为动力一致性证据。",
            "轴线从连续槽脊带中按局地低值/高值轴、曲率、距平强度、梯度和可选涡度综合评分抽取，再经样条平滑和评分脊线回贴。",
        ],
        "inputs": [
            {"field": "gh500", "required": True, "role": "500hPa 位势高度，用于计算纬向距平"},
            {"field": "uv500", "required": False, "role": "500hPa 风场，用于计算相对涡度支撑"},
        ],
        "method": [
            "gh500_anomaly = gh500 - mean(gh500, axis=longitude)",
            "trough_area = anomaly <= p8，ridge_area = anomaly >= p92",
            "axis_mask = anomaly_tail_mask 且 curvature_support >= curvature_p55",
            "score = local_axis + curvature + anomaly_intensity + gradient + optional_vorticity",
            "对 axis_mask 连通区按主轴投影抽取高评分轴线点，B 样条平滑后回贴评分脊线；按轴线长度、格点数和距平强度排序",
            "uv500 可用时输出 vorticity500 的符号支撑证据",
        ],
        "threshold_entries": [
            "system.trough_candidate.anomaly_percentile",
            "system.ridge_candidate.anomaly_percentile",
            "system.trough_ridge.min_points",
            "system.trough_ridge.axis_anomaly_percentile",
            "system.trough_ridge.curvature_percentile",
            "system.trough_ridge.vorticity_support",
            "system.trough_ridge.min_points_per_line",
            "system.trough_ridge.max_lines",
        ],
        "outputs": [
            "systems.type = trough_candidate / ridge_candidate",
            "systems.geometry.type = line 或 polygon",
            "diagnostics.gh500_anomaly",
        ],
        "evidence_contract": [
            "field=gh500_anomaly",
            "signal=curvature-supported height anomaly axis / height curvature support / relative vorticity sign support",
            "raw_value=分位阈值、曲率均值、涡度支撑均值、连通点数或输出排序",
            "rule_id 指向槽脊分位、曲率、涡度、点数或条数约束",
        ],
    },
    {
        "rule_id": "low_pressure_convergence_500",
        "title": "低压辐合候选",
        "category": "天气系统",
        "purpose": "识别 500hPa 高度负距平中心与 850hPa 低层辐合叠加的低压性影响区。",
        "basis": [
            "低压候选先由 gh500 纬向距平低值区约束，避免把背景高度梯度误判为中心。",
            "低层散度 div850 取低端分位，负散度越明显表示越强的低层辐合。",
            "高度负距平和低层辐合同时满足后，再用连通格点数和最大输出个数控制结果规模。",
        ],
        "inputs": [
            {"field": "gh500", "required": True, "role": "500hPa 位势高度，用于计算高度距平中心"},
            {"field": "div850", "required": False, "role": "850hPa 散度，负值作为低层辐合证据"},
        ],
        "method": [
            "gh500_anomaly = gh500 - mean(gh500, axis=longitude)",
            "low_mask = gh500_anomaly <= p20 且 div850 <= p10",
            "连通区按格点数排序，输出前 max_centers 个低压辐合候选",
        ],
        "threshold_entries": [
            "system.low_pressure.gh500_anomaly_percentile",
            "system.low_pressure.div850_convergence_percentile",
            "system.pressure_center.min_points",
            "system.pressure_center.max_centers",
        ],
        "outputs": [
            "systems.type = low_pressure_convergence",
            "systems.geometry.type = polygon",
            "systems.evidence[] 同时保留高度距平与 div850 辐合证据",
        ],
        "evidence_contract": [
            "field=gh500_anomaly / div850 / pressure_center_mask",
            "signal=height negative anomaly / low-level convergence / connected point count",
            "raw_value=候选区平均距平、平均散度或连通格点数",
            "source_paths 同时指向 gh500 与 div850 来源",
        ],
    },
    {
        "rule_id": "high_pressure_divergence_500",
        "title": "高压辐散候选",
        "category": "天气系统",
        "purpose": "识别 500hPa 高度正距平中心与 850hPa 低层辐散叠加的高压性影响区。",
        "basis": [
            "高压候选由 gh500 纬向距平高值区约束，突出相对周边偏高的高度中心。",
            "低层散度 div850 取高端分位，正散度越明显表示越强的低层辐散。",
            "高度正距平和低层辐散同时满足后，再用连通格点数和最大输出个数控制结果规模。",
        ],
        "inputs": [
            {"field": "gh500", "required": True, "role": "500hPa 位势高度，用于计算高度距平中心"},
            {"field": "div850", "required": False, "role": "850hPa 散度，正值作为低层辐散证据"},
        ],
        "method": [
            "gh500_anomaly = gh500 - mean(gh500, axis=longitude)",
            "high_mask = gh500_anomaly >= p80 且 div850 >= p90",
            "连通区按格点数排序，输出前 max_centers 个高压辐散候选",
        ],
        "threshold_entries": [
            "system.high_pressure.gh500_anomaly_percentile",
            "system.high_pressure.div850_divergence_percentile",
            "system.pressure_center.min_points",
            "system.pressure_center.max_centers",
        ],
        "outputs": [
            "systems.type = high_pressure_divergence",
            "systems.geometry.type = polygon",
            "systems.evidence[] 同时保留高度距平与 div850 辐散证据",
        ],
        "evidence_contract": [
            "field=gh500_anomaly / div850 / pressure_center_mask",
            "signal=height positive anomaly / low-level divergence / connected point count",
            "raw_value=候选区平均距平、平均散度或连通格点数",
            "source_paths 同时指向 gh500 与 div850 来源",
        ],
    },
    {
        "rule_id": "front_candidate_850",
        "title": "850hPa 锋面候选",
        "category": "天气系统",
        "purpose": "用低层温度梯度、风场形变、锋生函数、辐合和温度平流构造锋面候选综合评分。",
        "basis": [
            "850hPa 温度梯度是主判据，风场形变和锋生函数用于判断温度梯度是否被低层动力场维持或增强。",
            "低层辐合和温度平流作为辅助增强项；湿度可用时作为锋区水汽配合证据。",
            "当 uv850 可用时，除综合评分与温度梯度达标外，还要求至少满足一个动力支撑项。",
        ],
        "inputs": [
            {"field": "tt850", "required": True, "role": "850hPa 温度，计算水平梯度"},
            {"field": "uv850", "required": False, "role": "850hPa 风场，计算形变和锋生函数"},
            {"field": "div850", "required": False, "role": "低层辐合，负散度增强锋面评分"},
            {"field": "ttadv850", "required": False, "role": "温度平流绝对值，补充温度梯度变化信号"},
            {"field": "rh850", "required": False, "role": "850hPa 相对湿度，补充锋区水汽配合"},
        ],
        "method": [
            "grad_score = normalize01(|∇T850|, p5, p98)",
            "frontogenesis = max(-[(Tx^2*dudx + Ty^2*dvdy + Tx*Ty*(dudy+dvdx))] / |∇T|, 0)",
            "front_score = weighted(grad_score, frontogenesis_score, deformation_score, convergence_score, temp_advection_score, moisture_score)",
            "support_count 统计锋生、形变、辐合、温度平流和湿度中达到动力支撑分位的项数",
            "mask = front_score >= score_p82 且 |∇T850| >= gradient_p80；uv850 可用时还要求 support_count >= 1",
            "连通锋区按格点数和平均评分排序，只输出前 max_objects 个主要对象",
        ],
        "threshold_entries": [
            "system.front_candidate.tt850_gradient_percentile",
            "system.front_candidate.score_percentile",
            "system.front_candidate.dynamic_support_percentile",
            "system.front_candidate.min_support_components",
            "system.front_candidate.max_objects",
            "system.front_candidate.min_points",
        ],
        "outputs": [
            "systems.type = front_candidate",
            "diagnostics.tt850_gradient",
            "diagnostics.front_candidate_score",
            "diagnostics.frontogenesis850",
            "diagnostics.front_deformation850",
        ],
        "evidence_contract": [
            "field=tt850 / front_candidate_score / frontogenesis850 / front_support_count",
            "signal=temperature gradient / composite score / dynamic frontal support / connected area",
            "raw_value=梯度阈值、评分阈值、动力支撑阈值、支撑项数、连通格点数或输出排序",
            "source_paths 汇总 tt850、uv850、div850、ttadv850、rh850 来源",
        ],
    },
    {
        "rule_id": "low_level_jet_850",
        "title": "850hPa 低空急流候选",
        "category": "天气系统",
        "purpose": "识别低层风速高值带，并用水汽通量约束其是否可作为暖湿输送通道。",
        "basis": [
            "低空急流优先看 850hPa 风速高值，业务上常与暴雨水汽输送和低层辐合配合使用。",
            "当 q850 可用时，要求风速高值与 moisture_flux850 高值重叠，避免把干急流误判为水汽通道。",
            "候选区要求风向一致性达到下限，并按面积、平均风速和最大风速排序输出主要急流轴。",
        ],
        "inputs": [
            {"field": "uv850", "required": True, "role": "850hPa 风速"},
            {"field": "q850", "required": False, "role": "与风速合成 moisture_flux850"},
        ],
        "method": [
            "uv850_speed = sqrt(u850^2 + v850^2)",
            "moisture_flux850 = uv850_speed * q850",
            "mask = uv850_speed >= wind_speed_min 且 moisture_flux850 >= p70",
            "direction_coherence = length(mean(unit_wind_vector))",
            "连通高值带要求 direction_coherence >= min_direction_coherence，并保留前 max_objects 个",
        ],
        "threshold_entries": [
            "system.low_level_jet.wind_speed_min",
            "system.low_level_jet.moisture_flux_percentile",
            "system.low_level_jet.min_points",
            "system.low_level_jet.min_direction_coherence",
            "system.low_level_jet.max_objects",
        ],
        "outputs": [
            "systems.type = low_level_jet",
            "systems.geometry.type = line",
            "diagnostics.uv850_speed / diagnostics.moisture_flux850",
        ],
        "evidence_contract": [
            "field=uv850_speed / moisture_flux850",
            "signal=wind speed maximum / direction coherence / moisture flux percentile / connected area / output rank",
            "raw_value=候选区最大风速、风向一致性、水汽通量阈值、格点数或输出排序",
        ],
    },
    {
        "rule_id": "moisture_transport_850",
        "title": "850hPa 水汽输送带候选",
        "category": "天气系统",
        "purpose": "从 850hPa 风速与比湿合成的水汽通量中识别暖湿输送带。",
        "basis": [
            "水汽输送用 moisture_flux850 表征，近似为低层风速与 q850 的乘积。",
            "高值分位区代表水汽输送主通道，需后续结合辐合、上升运动判断是否转化为降水。",
            "输送带需要风向一致性支撑，避免局地高通量斑块被误判为连续输送通道。",
        ],
        "inputs": [
            {"field": "uv850", "required": True, "role": "850hPa 风速"},
            {"field": "q850", "required": True, "role": "低层比湿"},
        ],
        "method": [
            "moisture_flux850 = uv850_speed * q850",
            "mask = moisture_flux850 >= p75",
            "direction_coherence = length(mean(unit_wind_vector))",
            "连通高值带要求 direction_coherence >= min_direction_coherence，并按面积、平均通量和最大通量排序",
            "保留前 max_objects 个对象，以 line 几何输出",
        ],
        "threshold_entries": [
            "system.moisture_transport.flux_percentile",
            "system.moisture_transport.min_points",
            "system.moisture_transport.min_direction_coherence",
            "system.moisture_transport.max_objects",
        ],
        "outputs": [
            "systems.type = moisture_transport",
            "systems.geometry.type = line",
            "diagnostics.moisture_flux850",
        ],
        "evidence_contract": [
            "field=moisture_flux850 / uv850",
            "signal=moisture transport percentile / direction coherence / connected area / output rank",
            "raw_value=通量阈值、风向一致性、格点数或输出排序",
        ],
    },
    {
        "rule_id": "moisture_convergence_850",
        "title": "850hPa 水汽辐合区候选",
        "category": "天气系统",
        "purpose": "用水汽通量散度低值区识别水汽堆积和暴雨维持区。",
        "basis": [
            "水汽通量散度 ∇·(qV) 为负时表示水汽辐合。",
            "算法同时要求水汽通量本身达到中高分位，避免弱水汽背景下的伪辐合。",
            "散度场先做格点平滑以压制单格点噪声，再按面积和辐合强度排序输出主要对象。",
        ],
        "inputs": [
            {"field": "uv850", "required": True, "role": "850hPa 风矢量"},
            {"field": "q850", "required": True, "role": "低层比湿"},
        ],
        "method": [
            "moisture_flux_divergence850 = d(q*u)/dx + d(q*v)/dy",
            "smoothed = gaussian_smooth(moisture_flux_divergence850, sigma_grid)",
            "mask = smoothed <= p10 且 moisture_flux850 >= p55",
            "连通区以 polygon 几何输出，按面积和 smoothed 辐合强度排序保留前 max_objects 个",
        ],
        "threshold_entries": [
            "system.moisture_convergence.flux_divergence_percentile",
            "system.moisture_convergence.moisture_flux_percentile",
            "system.moisture_convergence.min_points",
            "system.moisture_convergence.smoothing_sigma_grid",
            "system.moisture_convergence.max_objects",
        ],
        "outputs": [
            "systems.type = moisture_convergence",
            "systems.geometry.type = polygon",
            "diagnostics.moisture_flux_divergence850",
        ],
        "evidence_contract": [
            "field=moisture_flux_divergence850 / moisture_flux_divergence850_smoothed / moisture_flux850",
            "signal=smoothed water vapor convergence / moisture supply / connected area / output rank",
            "raw_value=候选区平滑平均散度、原始平均散度、通量阈值、格点数或输出排序",
        ],
    },
    {
        "rule_id": "low_level_convergence_850",
        "title": "850hPa 低层辐合区",
        "category": "天气系统",
        "purpose": "用 850hPa 散度低值区识别有利触发和抬升的低层辐合带。",
        "basis": [
            "散度为负表示空气汇聚；低层辐合常与锋面、切变线、低压和地形抬升共同触发降水。",
            "散度场先做格点平滑，风场可用时要求由 uv850 反算的散度符号也支持辐合。",
            "候选区按面积和辐合强度排序截断，避免噪声碎片刷长系统列表。",
        ],
        "inputs": [
            {"field": "div850", "required": True, "role": "850hPa 散度"},
            {"field": "uv850", "required": False, "role": "850hPa 风场，用于反算散度符号一致性"},
        ],
        "method": [
            "smoothed = gaussian_smooth(div850, sigma_grid)",
            "mask = smoothed <= p10",
            "uv850 可用时 mask 还要求 divergence(u850,v850) <= 0",
            "连通区按最小格点数过滤，再按面积和辐合强度排序保留前 max_objects 个",
        ],
        "threshold_entries": [
            "system.low_level_convergence.div850_percentile",
            "system.low_level_convergence.min_points",
            "system.low_level_convergence.smoothing_sigma_grid",
            "system.low_level_convergence.max_objects",
        ],
        "outputs": [
            "systems.type = low_level_convergence",
            "systems.geometry.type = polygon",
        ],
        "evidence_contract": [
            "field=div850 / div850_smoothed",
            "signal=smoothed low-level convergence percentile / smoothing scale / connected area / output rank",
            "raw_value=候选区平滑平均散度、原始平均散度、格点数或输出排序",
        ],
    },
    {
        "rule_id": "upper_divergence",
        "title": "高空辐散区",
        "category": "天气系统",
        "purpose": "识别 200/300hPa 散度高值区，作为高空抽吸和动力抬升配合证据。",
        "basis": [
            "高空正散度表示空气在高层散开，有利于下方空气补偿上升。",
            "200/300hPa 候选统一进入排序池，按面积和辐散强度输出主要对象。",
            "散度场先做格点平滑，降低单格点高值造成的噪声对象。",
        ],
        "inputs": [
            {"field": "div200/div300", "required": True, "role": "高空散度"},
        ],
        "method": [
            "smoothed = gaussian_smooth(div_upper, sigma_grid)",
            "mask = smoothed >= p90",
            "200/300hPa 连通区合并排序，按最小格点数过滤后保留前 max_objects 个",
        ],
        "threshold_entries": [
            "system.upper_divergence.divergence_percentile",
            "system.upper_divergence.min_points",
            "system.upper_divergence.smoothing_sigma_grid",
            "system.upper_divergence.max_objects",
        ],
        "outputs": [
            "systems.type = upper_divergence",
            "systems.geometry.type = polygon",
        ],
        "evidence_contract": [
            "field=div200/div300 或其 smoothed 诊断",
            "signal=smoothed upper-level divergence percentile / smoothing scale / connected area / output rank",
            "raw_value=候选区平滑平均散度、原始平均散度、格点数或输出排序",
        ],
    },
    {
        "rule_id": "heavy_rain_potential",
        "title": "强降水潜势",
        "category": "证据链",
        "purpose": "汇总水汽、输送、辐合、抬升、不稳定和模式降水信号，给出强降水潜势等级与风险区域。",
        "basis": [
            "每个证据项按阈值矩阵的 operator、threshold、scale 归一化，并乘以 weight 形成贡献值。",
            "水汽和输送刻画供给，div850 与 w700 刻画触发和上升，kindex/CAPE 刻画不稳定，rain6 提供模式降水响应。",
            "风险区域由 q850、moisture_flux850、-div850、rain6 的归一化合成风险场分位提取。",
        ],
        "inputs": [
            {"field": "q850", "required": False, "role": "低层水汽 p75"},
            {"field": "tcwv", "required": False, "role": "整层可降水量 p75"},
            {"field": "uv850", "required": False, "role": "与 q850 组合为 moisture_flux850 p90"},
            {"field": "div850", "required": False, "role": "低层辐合 p10，负值越强越有利"},
            {"field": "w700", "required": False, "role": "700hPa 上升运动 p10"},
            {"field": "kindex", "required": False, "role": "对流不稳定 p75"},
            {"field": "cape", "required": False, "role": "CAPE 支持 p75"},
            {"field": "rain6", "required": False, "role": "模式 6 小时降水 p90"},
        ],
        "method": [
            "score = sum(normalized_score(rule, statistic(field)) * weight)",
            "level = score_level(score, matrix.level_thresholds)",
            "risk_region = largest_component(composite_risk >= p85, min_points=16)",
            "risk_region 连通分量按格点 cell union 输出 polygon，bbox 仅作为范围元数据",
        ],
        "threshold_entries": [
            "heavy_rain.q850",
            "heavy_rain.tcwv",
            "heavy_rain.moisture_flux850",
            "heavy_rain.div850",
            "heavy_rain.w700",
            "heavy_rain.kindex",
            "heavy_rain.cape",
            "heavy_rain.rain6",
            "region.risk.percentile",
            "region.risk.min_points",
        ],
        "outputs": [
            "evidence_chains.target_type = heavy_rain_potential",
            "evidence_chains.score / level / region(type=polygon,bbox,coordinates)",
            "evidence_chains.dominant_evidence[] / linked_systems[] / evidence[] / missing_evidence[]",
            "diagnosis_conclusions.headline / reasoning[] / action_hint",
        ],
        "evidence_contract": [
            "field、signal、value 描述证据项",
            "threshold、scale、operator、weight 来自默认阈值矩阵",
            "normalized_score 与 contribution 可追溯单项贡献",
            "dominant_evidence 按 contribution 降序保留前三个主导证据",
            "linked_systems 按空间关系与天气学相关性排序解释支撑系统",
            "diagnosis_conclusions 将主导证据和支撑系统组织为值班口径结论",
            "missing_evidence 只记录启用但缺测的证据场",
        ],
    },
    {
        "rule_id": "convection_potential",
        "title": "强对流潜势",
        "category": "证据链",
        "purpose": "综合不稳定能量、抑制能量、低层触发、垂直风切变与高空动力支持，输出强对流潜势等级。",
        "basis": [
            "CAPE、K 指数、水汽和风切变提供环境条件，CIN 采用 inverse_abs_ratio 判断抑制不强。",
            "低层辐合、高空辐散、PV 与 PV 平流用于增强触发和动力抬升证据。",
            "风险区域由 cape、shr850-200、q850、-div850 的归一化合成风险场分位提取。",
        ],
        "inputs": [
            {"field": "cape", "required": False, "role": "不稳定能量 p75"},
            {"field": "cin", "required": False, "role": "抑制能量 p50"},
            {"field": "kindex", "required": False, "role": "热力不稳定 p75"},
            {"field": "shr850-200", "required": False, "role": "深层垂直风切变 p75"},
            {"field": "q850", "required": False, "role": "低层水汽 p75"},
            {"field": "div850", "required": False, "role": "低层触发 p10"},
            {"field": "div200/div300", "required": False, "role": "高空辐散 p90，优先使用 div200"},
            {"field": "pv300", "required": False, "role": "高空 PV 支持 p90"},
            {"field": "pvadv300", "required": False, "role": "PV 平流绝对值 p90"},
        ],
        "method": [
            "score = sum(normalized_score(rule, statistic(field)) * weight)",
            "upper_divergence 优先取 div200，缺测时回退 div300",
            "level = score_level(score, matrix.level_thresholds)",
            "risk_region 连通分量按格点 cell union 输出 polygon，bbox 仅作为范围元数据",
        ],
        "threshold_entries": [
            "convection.cape",
            "convection.cin",
            "convection.kindex",
            "convection.shr850_200",
            "convection.q850",
            "convection.div850",
            "convection.upper_divergence",
            "convection.pv300",
            "convection.pvadv300",
            "region.risk.percentile",
            "region.risk.min_points",
        ],
        "outputs": [
            "evidence_chains.target_type = convection_potential",
            "evidence_chains.score / level / region(type=polygon,bbox,coordinates)",
            "evidence_chains.dominant_evidence[] / linked_systems[] / evidence[] / missing_evidence[]",
            "diagnosis_conclusions.headline / reasoning[] / action_hint",
        ],
        "evidence_contract": [
            "field、signal、value 描述证据项",
            "threshold、scale、operator、weight 来自默认阈值矩阵",
            "normalized_score 与 contribution 可追溯单项贡献",
            "dominant_evidence 按 contribution 降序保留前三个主导证据",
            "linked_systems 按空间关系与天气学相关性排序解释支撑系统",
            "diagnosis_conclusions 将主导证据和支撑系统组织为值班口径结论",
            "missing_evidence 只记录启用但缺测的证据场",
        ],
    },
    {
        "rule_id": "dynamic_lift_potential",
        "title": "动力抬升潜势",
        "category": "证据链",
        "purpose": "综合低层辐合、垂直运动、涡度和高空辐散，判断大尺度动力抬升配合程度。",
        "basis": [
            "低层辐合与高空辐散构成上下配合，700hPa 负垂直速度表示上升运动。",
            "500hPa 正涡度和 PV 平流可反映槽前动力抬升或高空扰动支持。",
            "该链更强调动力条件，不替代水汽和热力判断。",
        ],
        "inputs": [
            {"field": "w700", "required": False, "role": "700hPa 垂直速度 p10"},
            {"field": "uv500", "required": False, "role": "计算 500hPa 相对涡度 p90"},
            {"field": "div850", "required": False, "role": "低层辐合 p10"},
            {"field": "div200/div300", "required": False, "role": "高空辐散 p90"},
            {"field": "pvadv300", "required": False, "role": "高空 PV 平流绝对值 p90"},
        ],
        "method": [
            "vorticity500 = dv500/dx - du500/dy",
            "score = sum(normalized_score(rule, statistic(field)) * weight)",
            "level = score_level(score, matrix.level_thresholds)",
            "risk_region 连通分量按格点 cell union 输出 polygon，bbox 仅作为范围元数据",
        ],
        "threshold_entries": [
            "dynamic_lift.w700",
            "dynamic_lift.vorticity500",
            "dynamic_lift.div850",
            "dynamic_lift.upper_divergence",
            "dynamic_lift.pvadv300",
            "region.risk.percentile",
            "region.risk.min_points",
        ],
        "outputs": [
            "evidence_chains.target_type = dynamic_lift_potential",
            "diagnostics.vorticity500",
            "evidence_chains.score / level / region(type=polygon,bbox,coordinates)",
            "evidence_chains.dominant_evidence[]",
            "evidence_chains.linked_systems[]",
        ],
        "evidence_contract": [
            "field、signal、value 描述动力证据项",
            "threshold、scale、operator、weight 来自默认阈值矩阵",
            "dominant_evidence 按 contribution 降序保留前三个主导证据",
            "linked_systems 按空间关系与天气学相关性排序解释支撑系统",
            "missing_evidence 记录缺测动力量",
        ],
    },
    {
        "rule_id": "precipitation_phase",
        "title": "雨雪相态初判",
        "category": "证据链",
        "purpose": "用近地面和低层温度结构给出雨、雪、混合相态或冻雨的初步判断。",
        "basis": [
            "相态首先受近地面温度、925/850hPa 暖层和湿球 0℃ 层控制。",
            "当前为格点模式资料的初判，缺少完整探空廓线时需要预报员结合整层温湿结构订正。",
        ],
        "inputs": [
            {"field": "t2m", "required": False, "role": "2m 温度 p50"},
            {"field": "tt850", "required": False, "role": "850hPa 温度 p50"},
            {"field": "tt925", "required": False, "role": "925hPa 温度 p50"},
            {"field": "tw0_height", "required": False, "role": "湿球 0℃ 层高度 p50"},
        ],
        "method": [
            "温度统一转换为摄氏度后取区域 p50",
            "低层均低于 0℃ 倾向雪；近地面接近 0℃ 且低层有暖层倾向混合或冻雨",
            "phase_type 输出 rain / mixed / snow / freezing_rain / unknown",
        ],
        "threshold_entries": [
            "phase.t2m",
            "phase.tt850",
            "phase.tt925",
            "phase.tw0_height",
        ],
        "outputs": [
            "evidence_chains.target_type = precipitation_phase",
            "evidence_chains.phase_type",
            "evidence_chains.diagnosis",
            "evidence_chains.dominant_evidence[]",
        ],
        "evidence_contract": [
            "field=t2m / tt850 / tt925 / tw0_height",
            "raw_value=摄氏温度或高度统计值",
            "dominant_evidence 按 contribution 降序保留前三个主导证据",
            "missing_evidence 记录缺测层次，避免误报相态确定性",
        ],
    },
]


def default_threshold_matrix() -> dict:
    return deepcopy(DEFAULT_THRESHOLD_MATRIX)


def _same_optional_float(left: object, right: object) -> bool:
    if left is None or right is None or left == "" or right == "":
        return False
    try:
        return abs(float(left) - float(right)) <= 1.0e-9
    except (TypeError, ValueError):
        return False


def _migrate_saved_threshold_entry(default_item: dict, raw_item: dict) -> dict:
    item = dict(raw_item)
    entry_id = str(item.get("entry_id") or "")
    if not entry_id.startswith("risk."):
        return item
    if str(item.get("operator") or "") != "weight":
        return item
    if not _same_optional_float(item.get("threshold"), item.get("weight")):
        return item
    if default_item.get("threshold") is not None and _same_optional_float(item.get("threshold"), default_item.get("threshold")):
        return item
    for field in ["threshold", "scale", "operator", "statistic", "unit"]:
        item.pop(field, None)
    return item


def _merge_default_items(default_items: list[dict], saved_items: list[dict] | None, key: str) -> list[dict]:
    merged = [deepcopy(item) for item in default_items]
    by_key = {str(item.get(key) or ""): item for item in merged}
    for raw in saved_items or []:
        item_key = str(raw.get(key) or "")
        if item_key in by_key:
            if key == "entry_id":
                raw = _migrate_saved_threshold_entry(by_key[item_key], raw)
            by_key[item_key].update(raw)
    return merged


def load_threshold_matrix() -> dict:
    ensure_dirs()
    if not THRESHOLD_MATRIX_PATH.exists():
        return default_threshold_matrix()
    try:
        data = json.loads(THRESHOLD_MATRIX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ThresholdMatrixError("threshold matrix unreadable", status_code=500) from exc
    data = dict(data)
    saved_entries = data.pop("entries", None)
    saved_level_thresholds = data.pop("level_thresholds", None)
    matrix = default_threshold_matrix()
    matrix.update(data)
    matrix["entries"] = _merge_default_items(
        DEFAULT_THRESHOLD_MATRIX["entries"],
        saved_entries,
        "entry_id",
    )
    matrix["level_thresholds"] = _merge_default_items(
        DEFAULT_THRESHOLD_MATRIX["level_thresholds"],
        saved_level_thresholds,
        "level",
    )
    matrix["matrix_id"] = DEFAULT_MATRIX_ID
    matrix["algorithm_id"] = ALGORITHM_ID
    matrix["status"] = "default"
    return matrix


def threshold_entries_by_id(matrix: dict) -> dict[str, dict]:
    internal_defaults = [
        *DEFAULT_THRESHOLD_MATRIX["entries"],
        *LEGACY_SUPPORT_THRESHOLD_ENTRIES,
    ]
    entries = _merge_default_items(internal_defaults, matrix.get("entries") or [], "entry_id")
    return {str(entry["entry_id"]): entry for entry in entries}


def score_level(score: float, matrix: dict) -> str:
    thresholds = sorted(
        matrix.get("level_thresholds", []),
        key=lambda item: float(item.get("score_gte") or 0.0),
        reverse=True,
    )
    for item in thresholds:
        if score >= float(item.get("score_gte") or 0.0):
            return str(item.get("level") or "low")
    return "low"


def catalog_payload() -> dict:
    algorithms = deepcopy(ALGORITHM_CATALOG)
    for algorithm in algorithms:
        for system in algorithm.get("systems") or []:
            system["governance_domain"] = WEATHER_SYSTEM_DOMAIN
        algorithm["evidence_chains"] = [
            chain for chain in algorithm.get("evidence_chains") or []
            if str(chain.get("target") or "") in RISK_DIAGNOSIS_TARGETS
        ]
        for chain in algorithm["evidence_chains"]:
            target = str(chain.get("target") or "")
            if target in RISK_DIAGNOSIS_TARGETS:
                chain["governance_domain"] = RISK_DIAGNOSIS_DOMAIN
    return {
        "algorithms": algorithms,
        "threshold_matrix": load_threshold_matrix(),
    }


def _risk_diagnosis_rule_templates() -> list[dict]:
    chain_lookup = {
        chain["target"]: chain
        for algorithm in ALGORITHM_CATALOG
        for chain in algorithm.get("evidence_chains") or []
        if chain.get("target") in RISK_DIAGNOSIS_TARGETS
    }
    sections = []
    for target in [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ]:
        spec = RISK_RULE_SPECS[target]
        chain = chain_lookup.get(target, {})
        title = spec["title"]
        source_grid = f"risk_{target.replace('rotating_storm_or_supercell', 'rotating_storm')}_score"
        sections.append(
            {
                "rule_id": target,
                "title": title,
                "category": "风险诊断",
                "purpose": spec["purpose"],
                "basis": spec["basis"],
                "inputs": [
                    {"field": field, "required": False, "role": "风险评分因子"}
                    for field in spec["inputs"]
                ],
                "method": [
                    chain.get("method") or spec["purpose"],
                    "各因子统一归一到 0-100，再转换为 0-1 风险格点输出。",
                    "按中等/高风险阈值提取风险区，保留主导因子、支撑天气系统和 source_grid。",
                ],
                "composition": deepcopy(RISK_COMPOSITION_RULES.get(target)),
                "threshold_entries": _risk_threshold_entry_ids(target),
                "outputs": [
                    f"risk_diagnoses.hazard_type = {target}",
                    f"risk_diagnoses.source_grid = {source_grid}",
                    f"diagnostics.{source_grid}",
                ],
                "evidence_contract": [
                    "score 必须来自对应 source_grid 的格点评分。",
                    "dominant_evidence 按主导因子贡献排序。",
                    "supporting_systems 只记录空间邻近或重叠的天气系统支撑。",
                ],
            }
        )
    return sections


def _rule_governance_domain(section: dict) -> str:
    if section.get("rule_id") in RISK_DIAGNOSIS_TARGETS:
        return RISK_DIAGNOSIS_DOMAIN
    if section.get("category") == "天气系统":
        return WEATHER_SYSTEM_DOMAIN
    return SUPPORTING_DIAGNOSIS_DOMAIN


def rule_explanations_payload() -> dict:
    matrix = load_threshold_matrix()
    by_id = threshold_entries_by_id(matrix)
    sections = []
    for template in [*RULE_EXPLANATION_TEMPLATES, *_risk_diagnosis_rule_templates()]:
        if str(template.get("rule_id") or "") in LEGACY_SUPPORT_TARGETS:
            continue
        section = deepcopy(template)
        section["governance_domain"] = _rule_governance_domain(section)
        threshold_ids = list(section["threshold_entries"])
        section["threshold_details"] = [deepcopy(by_id[entry_id]) for entry_id in threshold_ids if entry_id in by_id]
        section["missing_threshold_entries"] = [entry_id for entry_id in threshold_ids if entry_id not in by_id]
        section["enabled_threshold_count"] = sum(
            1 for entry in section["threshold_details"] if bool(entry.get("enabled", True))
        )
        sections.append(section)
    return {
        "algorithm_id": ALGORITHM_ID,
        "name": "NAFP 天气形势诊断规则说明",
        "matrix_id": matrix.get("matrix_id", DEFAULT_MATRIX_ID),
        "matrix_updated_at": matrix.get("updated_at"),
        "sections": sections,
    }


def _as_optional_float(value: object, field_name: str, entry_id: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ThresholdMatrixError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": field_name, "entry_id": entry_id},
        ) from exc


def _validate_entries(entries: list[dict]) -> list[dict]:
    known_ids = {entry["entry_id"] for entry in DEFAULT_THRESHOLD_MATRIX["entries"]}
    seen: set[str] = set()
    normalized = []
    if not entries:
        raise ThresholdMatrixError("invalid threshold matrix", status_code=400, data={"field": "entries"})

    for raw in entries:
        entry = dict(raw)
        entry_id = str(entry.get("entry_id") or "")
        if not entry_id or entry_id in seen or entry_id not in known_ids:
            raise ThresholdMatrixError(
                "invalid threshold matrix",
                status_code=400,
                data={"field": "entry_id", "entry_id": entry_id},
            )
        seen.add(entry_id)

        threshold = _as_optional_float(entry.get("threshold"), "threshold", entry_id)
        scale = _as_optional_float(entry.get("scale"), "scale", entry_id)
        weight = _as_optional_float(entry.get("weight"), "weight", entry_id)
        if weight is not None and not 0 <= weight <= 1:
            raise ThresholdMatrixError(
                "invalid threshold matrix",
                status_code=400,
                data={"field": "weight", "entry_id": entry_id},
            )
        if scale is not None and scale <= 0:
            raise ThresholdMatrixError(
                "invalid threshold matrix",
                status_code=400,
                data={"field": "scale", "entry_id": entry_id},
            )

        entry["threshold"] = threshold
        entry["scale"] = scale
        entry["weight"] = weight
        entry["enabled"] = bool(entry.get("enabled", True))
        normalized.append(entry)

    return normalized


def _validate_level_thresholds(level_thresholds: list[dict]) -> list[dict]:
    required = {"high", "moderate", "low"}
    levels = {str(item.get("level") or "") for item in level_thresholds}
    if levels != required:
        raise ThresholdMatrixError("invalid threshold matrix", status_code=400, data={"field": "level_thresholds"})
    normalized = []
    for item in level_thresholds:
        score = _as_optional_float(item.get("score_gte"), "score_gte", str(item.get("level") or ""))
        if score is None or not 0 <= score <= 1:
            raise ThresholdMatrixError("invalid threshold matrix", status_code=400, data={"field": "score_gte"})
        normalized.append({**item, "score_gte": score})
    return normalized


def save_threshold_matrix(payload: dict) -> dict:
    ensure_dirs()
    if payload.get("algorithm_id") != ALGORITHM_ID:
        raise ThresholdMatrixError("invalid threshold matrix", status_code=400, data={"field": "algorithm_id"})

    entries = _merge_default_items(
        DEFAULT_THRESHOLD_MATRIX["entries"],
        _validate_entries(list(payload.get("entries") or [])),
        "entry_id",
    )
    level_thresholds = _merge_default_items(
        DEFAULT_THRESHOLD_MATRIX["level_thresholds"],
        _validate_level_thresholds(list(payload.get("level_thresholds") or [])),
        "level",
    )
    matrix = {
        "matrix_id": DEFAULT_MATRIX_ID,
        "algorithm_id": ALGORITHM_ID,
        "name": "NAFP 业务默认阈值矩阵",
        "status": "default",
        "updated_at": utc_now(),
        "updated_by": str(payload.get("updated_by") or "admin"),
        "remark": str(payload.get("remark") or ""),
        "level_thresholds": level_thresholds,
        "entries": entries,
    }
    THRESHOLD_MATRIX_PATH.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    return matrix
