from __future__ import annotations

from typing import Any

import numpy as np


DEFAULT_RISK_SCORING: dict[str, Any] = {
    "common": {
        "q850_gkg": {"low": 6.0, "high": 14.0},
        "td2m_c": {"low": 16.0, "high": 24.0},
        "pw_mm": {"low": 30.0, "high": 55.0},
        "rh850": {"low": 60.0, "high": 90.0},
        "rh700": {"low": 60.0, "high": 90.0},
        "rh500": {"low": 50.0, "high": 80.0},
        "moisture_flux850": {"low": 80.0, "high": 200.0},
        "omega700_pa_s": {"low": 0.05, "high": 0.35},
        "cape": {"low": 500.0, "high": 2500.0},
        "k_index": {"low": 25.0, "high": 38.0},
        "li": {"high": 2.0, "low": -6.0},
        "deep_shear_ms": {"low": 10.0, "high": 25.0},
        "low_level_shear_ms": {"low": 5.0, "high": 15.0},
        "dcape": {"low": 500.0, "high": 1500.0},
        "wind500_ms": {"low": 15.0, "high": 30.0},
        "t500_c": {"high": -8.0, "low": -18.0},
        "lapse_rate_700_500": {"low": 6.0, "high": 8.0},
        "freezing_level_m": {"min": 1800.0, "opt_low": 2500.0, "opt_high": 4200.0, "max": 5600.0},
        "lcl_m": {"high": 1600.0, "low": 600.0},
        "srh": {"low": 100.0, "high": 300.0},
        "precip_6h_mm": {"low": 20.0, "high": 80.0},
        "precip_24h_mm": {"low": 50.0, "high": 150.0},
        "precip_1h_mm": {"low": 10.0, "high": 50.0},
        "precip_3h_mm": {"low": 20.0, "high": 80.0},
        "mean_wind_850_500_ms": {"high": 18.0, "low": 5.0},
        "mid_dry_rh700": {"high": 80.0, "low": 35.0},
        "mid_dry_rh500": {"high": 75.0, "low": 30.0},
    },
    "persistent_heavy_rain": {
        "weights": {
            "moisture_transport": 0.18,
            "moisture_convergence": 0.20,
            "ascent": 0.18,
            "deep_moisture": 0.14,
            "low_level_convergence": 0.10,
            "model_precip": 0.10,
            "persistence": 0.07,
            "system_support": 0.03,
        }
    },
    "precip_short_duration_heavy_rain": {
        "weights": {
            "moisture": 0.18,
            "pw": 0.12,
            "moisture_convergence": 0.18,
            "low_level_convergence": 0.12,
            "ascent": 0.12,
            "instability": 0.10,
            "k_index": 0.08,
            "training": 0.06,
            "rainrate": 0.04,
        }
    },
    "conv_short_duration_heavy_rain": {
        "weights": {
            "precip_short_heavy_rain_base": 0.45,
            "convective_character": 0.35,
            "moisture_convergence": 0.10,
            "low_level_convergence": 0.10,
        }
    },
    "convective_character": {
        "weights": {
            "instability": 0.35,
            "cin_breakable": 0.15,
            "trigger": 0.20,
            "low_level_moisture": 0.15,
            "deep_shear": 0.10,
            "k_index": 0.05,
        }
    },
    "thunderstorm_gale": {
        "weights": {
            "storm_initiation": 0.18,
            "dcape": 0.25,
            "mid_dry": 0.17,
            "deep_shear": 0.18,
            "upper_wind": 0.10,
            "linear_mode": 0.12,
        }
    },
    "storm_initiation": {
        "weights": {
            "instability": 0.35,
            "moisture": 0.20,
            "cin_breakable": 0.15,
            "trigger": 0.20,
            "deep_shear": 0.10,
        }
    },
    "linear_mode": {
        "weights": {
            "deep_shear": 0.45,
            "trigger_line": 0.25,
            "low_level_convergence": 0.20,
            "dcape": 0.10,
        }
    },
    "hail": {
        "weights": {
            "cape": 0.22,
            "deep_shear": 0.22,
            "mid_cold": 0.14,
            "lapse_rate": 0.12,
            "freezing_level": 0.10,
            "supercell_env": 0.12,
            "trigger": 0.08,
        }
    },
    "supercell_env": {
        "weights": {
            "cape": 0.30,
            "deep_shear": 0.40,
            "low_level_shear": 0.15,
            "trigger": 0.15,
        }
    },
    "rotating_storm_supercell": {
        "weights": {
            "cape": 0.18,
            "deep_shear": 0.28,
            "low_level_shear": 0.18,
            "srh": 0.16,
            "lcl": 0.08,
            "cin_breakable": 0.05,
            "trigger": 0.05,
            "discrete_storm": 0.02,
        },
        "fallback_without_srh_weights": {
            "cape": 0.22,
            "deep_shear": 0.34,
            "low_level_shear": 0.22,
            "lcl": 0.08,
            "cin_breakable": 0.06,
            "trigger": 0.08,
        },
    },
}


FACTOR_LABELS = {
    "ascent": "700hPa 上升运动",
    "cape": "CAPE",
    "cin_breakable": "CIN 可突破",
    "convective_character": "对流性",
    "dcape": "DCAPE/下沉大风潜势",
    "deep_moisture": "深厚湿层",
    "deep_shear": "0-6km 风切变",
    "discrete_storm": "离散单体环境",
    "freezing_level": "0℃ 层高度",
    "instability": "对流能量",
    "k_index": "K 指数",
    "lapse_rate": "700-500hPa 递减率",
    "lcl": "LCL 云底高度",
    "linear_mode": "线状组织潜势",
    "low_level_convergence": "低层辐合",
    "low_level_moisture": "低层水汽",
    "low_level_shear": "0-1km 风切变",
    "mid_cold": "中层冷空气",
    "mid_dry": "中层干空气",
    "model_precip": "模式累计降水",
    "moisture": "低层水汽",
    "moisture_convergence": "水汽辐合",
    "moisture_transport": "低层水汽输送",
    "persistence": "持续性",
    "precip_short_heavy_rain_base": "降水视角短时强降水",
    "pw": "整层可降水量",
    "rainrate": "模式短时雨强",
    "srh": "风暴相对螺旋度",
    "storm_initiation": "雷暴发生潜势",
    "supercell_env": "超级单体环境",
    "system_support": "系统支持",
    "training": "列车效应潜势",
    "trigger": "触发条件",
    "upper_wind": "高空强风",
}


CRITICAL_FACTOR_ALIASES = {
    "conv_short_duration_heavy_rain": {
        "CAPE/K指数不稳定": ("cape", "k_index", "k"),
        "低层水汽": ("q850", "q850_gkg", "td2m", "pw", "tcwv"),
        "低层辐合/水汽辐合触发": ("div850", "moisture_convergence", "moisture_conv850"),
    },
    "short_duration_heavy_rain": {
        "短时降水或雨强": ("precip_1h", "precip_3h", "precip_6h", "precipitation"),
        "低层水汽": ("q850", "q850_gkg", "td2m", "pw", "tcwv"),
        "低层辐合/水汽辐合触发": ("div850", "moisture_convergence", "moisture_conv850"),
    },
    "thunderstorm_gale": {
        "CAPE/K指数不稳定": ("cape", "k_index", "k"),
        "DCAPE下沉潜势": ("dcape",),
        "0-6km深层风切变": ("shear_0_6km", "deep_shear"),
        "中层干空气": ("rh700", "rh500"),
        "低层触发": ("div850", "moisture_convergence", "front_or_shearline_score"),
    },
    "hail": {
        "CAPE不稳定": ("cape",),
        "0-6km深层风切变": ("shear_0_6km", "deep_shear"),
        "中层冷空气": ("t500", "temperature500"),
        "700-500hPa递减率或温度层结": ("lapse_rate_700_500", "t700", "t500"),
        "0℃层高度": ("z0_c_m", "freezing_level_m", "deg0l"),
    },
    "rotating_storm_or_supercell": {
        "CAPE不稳定": ("cape",),
        "0-6km深层风切变": ("shear_0_6km", "deep_shear"),
        "0-1km低层风切变": ("shear_0_1km", "low_level_shear"),
        "SRH风暴相对螺旋度": ("srh", "srh_0_3km"),
        "LCL云底高度": ("lcl", "lcl_m", "t2m", "td2m"),
    },
}


def _has_usable_field(fields: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    for name in aliases:
        value = fields.get(name)
        if value is None or isinstance(value, dict):
            continue
        try:
            arr = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            continue
        if arr.size and np.isfinite(arr).any():
            return True
    return False


def _quality_gate(
    risk_type: str,
    fields: dict[str, Any],
    score,
    confidence,
    *,
    sample,
    extra_caps: list[tuple[float, Any, str]] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    score_grid = np.asarray(score, dtype=float)
    confidence_grid = _broadcast_to_sample(confidence, sample)
    requirements = CRITICAL_FACTOR_ALIASES.get(risk_type, {})
    missing = [label for label, aliases in requirements.items() if not _has_usable_field(fields, aliases)]
    total = max(1, len(requirements))
    completeness = (total - len(missing)) / total
    cap_value = 100.0
    cap_reasons: list[str] = []
    if completeness < 0.50:
        cap_value = 45.0
        cap_reasons.append("critical_factor_completeness_lt_50pct")
    elif completeness < 0.70:
        cap_value = 60.0
        cap_reasons.append("critical_factor_completeness_lt_70pct")
    elif completeness < 0.85:
        cap_value = 75.0
        cap_reasons.append("critical_factor_completeness_lt_85pct")
    if extra_caps:
        for value, condition, reason in extra_caps:
            condition_arr = np.asarray(condition, dtype=bool)
            if condition_arr.shape == ():
                condition_arr = np.full_like(score_grid, bool(condition_arr), dtype=bool)
            if bool(np.any(condition_arr)):
                score_grid = _cap(score_grid, float(value), condition_arr)
                cap_reasons.append(reason)
                cap_value = min(cap_value, float(value))
    capped_score = np.minimum(score_grid, cap_value)
    confidence_factor = 0.55 + 0.45 * completeness
    confidence_grid = confidence_grid * confidence_factor
    quality = {
        "input_completeness": round(float(completeness), 3),
        "missing_critical_factors": missing,
        "required_critical_factors": list(requirements.keys()),
        "score_cap_applied": bool(np.nanmax(capped_score) < np.nanmax(score_grid) or cap_reasons),
        "score_cap_value": None if cap_value >= 100.0 else float(cap_value),
        "score_cap_reasons": cap_reasons,
    }
    return capped_score, confidence_grid, quality


def _combine_quality(*items: dict[str, Any] | None) -> dict[str, Any]:
    valid = [item for item in items if item]
    if not valid:
        return {}
    missing: list[str] = []
    required: list[str] = []
    reasons: list[str] = []
    completeness_values = []
    cap_values = []
    cap_applied = False
    for item in valid:
        completeness_values.append(float(item.get("input_completeness", 1.0)))
        missing.extend(str(v) for v in item.get("missing_critical_factors", []))
        required.extend(str(v) for v in item.get("required_critical_factors", []))
        reasons.extend(str(v) for v in item.get("score_cap_reasons", []))
        cap_applied = cap_applied or bool(item.get("score_cap_applied"))
        if item.get("score_cap_value") is not None:
            cap_values.append(float(item["score_cap_value"]))
    return {
        "input_completeness": round(float(np.nanmin(completeness_values)), 3),
        "missing_critical_factors": sorted(set(missing)),
        "required_critical_factors": sorted(set(required)),
        "score_cap_applied": cap_applied,
        "score_cap_value": min(cap_values) if cap_values else None,
        "score_cap_reasons": sorted(set(reasons)),
    }


def clamp(x, low: float = 0.0, high: float = 100.0):
    return np.clip(np.asarray(x, dtype=float), low, high)


def score_pos(x, low: float, high: float):
    arr = np.asarray(x, dtype=float)
    if high <= low:
        return np.zeros_like(arr, dtype=float)
    out = (arr - low) / (high - low) * 100.0
    return np.where(np.isfinite(out), clamp(out), 0.0)


def score_neg(x, high: float, low: float):
    arr = np.asarray(x, dtype=float)
    if high <= low:
        return np.zeros_like(arr, dtype=float)
    out = (high - arr) / (high - low) * 100.0
    return np.where(np.isfinite(out), clamp(out), 0.0)


def score_triangular(x, min_v: float, opt_low: float, opt_high: float, max_v: float):
    arr = np.asarray(x, dtype=float)
    out = np.zeros_like(arr, dtype=float)
    rising = (arr > min_v) & (arr < opt_low)
    optimal = (arr >= opt_low) & (arr <= opt_high)
    falling = (arr > opt_high) & (arr < max_v)
    if opt_low > min_v:
        out[rising] = (arr[rising] - min_v) / (opt_low - min_v) * 100.0
    out[optimal] = 100.0
    if max_v > opt_high:
        out[falling] = (max_v - arr[falling]) / (max_v - opt_high) * 100.0
    return np.where(np.isfinite(out), clamp(out), 0.0)


def score_percentile(x, p70: float, p95: float):
    arr = np.asarray(x, dtype=float)
    if p95 <= p70:
        return np.zeros_like(arr, dtype=float)
    out = (arr - p70) / (p95 - p70) * 100.0
    return np.where(np.isfinite(out), clamp(out), 0.0)


def risk_level(score: float) -> str:
    if score >= 80.0:
        return "very_high"
    if score >= 60.0:
        return "high"
    if score >= 40.0:
        return "medium"
    if score >= 20.0:
        return "low"
    return "very_low"


def weighted_mean(factors: dict[str, tuple[Any, float] | tuple[Any, float, str]], *, sample=None) -> dict[str, Any]:
    sample_arr = _as_array(sample) if sample is not None else _sample_from_factor_values(factors)
    if sample_arr is None:
        sample_arr = np.zeros((1, 1), dtype=float)

    configured_weight = float(sum(float(item[1]) for item in factors.values() if float(item[1]) > 0))
    numerator = np.zeros_like(sample_arr, dtype=float)
    denominator = np.zeros_like(sample_arr, dtype=float)
    factor_details: dict[str, dict[str, Any]] = {}

    for factor, item in factors.items():
        value = item[0]
        weight = float(item[1])
        label = str(item[2]) if len(item) > 2 else FACTOR_LABELS.get(factor, factor)
        if value is None or weight <= 0:
            continue
        score = _broadcast_to_sample(value, sample_arr)
        finite = np.isfinite(score)
        numerator += np.where(finite, score * weight, 0.0)
        denominator += np.where(finite, weight, 0.0)
        factor_details[factor] = {
            "field": factor,
            "label": label,
            "weight": weight,
            "score": np.where(finite, score, np.nan),
        }

    score = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(sample_arr, dtype=float),
        where=denominator > 0,
    )
    confidence = (
        np.divide(
            denominator,
            configured_weight,
            out=np.zeros_like(sample_arr, dtype=float),
            where=configured_weight > 0,
        )
        if configured_weight > 0
        else np.zeros_like(sample_arr, dtype=float)
    )

    for detail in factor_details.values():
        contribution = np.divide(
            np.where(np.isfinite(detail["score"]), detail["score"] * detail["weight"], 0.0),
            denominator,
            out=np.zeros_like(sample_arr, dtype=float),
            where=denominator > 0,
        )
        detail["contribution"] = contribution

    available_weight = float(np.nanmax(denominator)) if denominator.size else 0.0
    return {
        "score": clamp(score),
        "confidence": np.clip(confidence, 0.0, 1.0),
        "configured_weight": round(configured_weight, 6),
        "available_weight": round(available_weight, 6),
        "factors": factor_details,
    }


def compute_common_factors(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _risk_config(config)
    common = cfg.get("common", {})
    sample = _sample_from_fields(fields)
    if sample is None:
        sample = np.zeros((1, 1), dtype=float)

    q850_gkg = _to_gkg(_field(fields, "q850", "q850_gkg", "specific_humidity850"))
    td2m = _field(fields, "td2m", "d2m", "dewpoint2m")
    pw = _field(fields, "pw", "pw_mm", "precipitable_water")
    rh850 = _field(fields, "rh850", "relative_humidity850")
    rh700 = _field(fields, "rh700", "relative_humidity700")
    rh500 = _field(fields, "rh500", "relative_humidity500")

    moisture = weighted_mean(
        {
            "q850": (_threshold_score_pos(q850_gkg, common, "q850_gkg"), 0.35, "850hPa 比湿"),
            "td2m": (_threshold_score_pos(td2m, common, "td2m_c"), 0.25, "2m 露点"),
            "pw": (_threshold_score_pos(pw, common, "pw_mm"), 0.25, "可降水量"),
            "rh850": (_threshold_score_pos(rh850, common, "rh850"), 0.15, "850hPa 相对湿度"),
        },
        sample=sample,
    )
    deep_moisture = weighted_mean(
        {
            "rh850": (_threshold_score_pos(rh850, common, "rh850"), 0.36, "850hPa 相对湿度"),
            "rh700": (_threshold_score_pos(rh700, common, "rh700"), 0.36, "700hPa 相对湿度"),
            "rh500": (_threshold_score_pos(rh500, common, "rh500"), 0.28, "500hPa 相对湿度"),
        },
        sample=sample,
    )

    moisture_flux = _scale_moisture_flux(_field(fields, "moisture_flux", "moisture_flux850"))
    moisture_transport_score = _threshold_score_pos(moisture_flux, common, "moisture_flux850")
    moisture_convergence_score = _positive_percentile_score(_field(fields, "moisture_convergence", "moisture_conv850"))
    low_level_convergence_score = _positive_percentile_score(_negative(_field(fields, "div850", "divergence850")))
    ascent_score = _threshold_score_pos(_negative(_field(fields, "omega700", "w700")), common, "omega700_pa_s")

    cape_score = _threshold_score_pos(_field(fields, "cape"), common, "cape")
    k_score = _threshold_score_pos(_field(fields, "k_index", "k"), common, "k_index")
    li_score = _threshold_score_neg(_field(fields, "li"), common, "li")
    instability = weighted_mean(
        {
            "cape": (cape_score, 0.45, "CAPE"),
            "k_index": (k_score, 0.35, "K 指数"),
            "li": (li_score, 0.20, "抬升指数"),
        },
        sample=sample,
    )

    cin_score = _cin_breakable_score(_field(fields, "cin"))
    pva_score = _positive_percentile_score(_field(fields, "pva500", "vort_adv500"))
    upper_divergence_score = _positive_percentile_score(_field(fields, "upper_divergence", "div200", "div300"))
    trigger_score = _nanmax_scores(
        [low_level_convergence_score, moisture_convergence_score, pva_score, upper_divergence_score],
        sample,
    )

    deep_shear_score = _threshold_score_pos(_field(fields, "shear_0_6km", "deep_shear"), common, "deep_shear_ms")
    low_level_shear_score = _threshold_score_pos(
        _field(fields, "shear_0_1km", "low_level_shear"),
        common,
        "low_level_shear_ms",
    )
    dcape_score = _threshold_score_pos(_field(fields, "dcape"), common, "dcape")
    mid_dry = weighted_mean(
        {
            "rh700_dry": (_threshold_score_neg(rh700, common, "mid_dry_rh700"), 0.55, "700hPa 中层干空气"),
            "rh500_dry": (_threshold_score_neg(rh500, common, "mid_dry_rh500"), 0.45, "500hPa 中层干空气"),
        },
        sample=sample,
    )
    upper_wind_score = _threshold_score_pos(_field(fields, "wind500", "wind500_speed", "wind700"), common, "wind500_ms")

    mean_wind = _field(fields, "mean_wind_850_500", "storm_motion")
    slow_motion_score = _threshold_score_neg(mean_wind, common, "mean_wind_850_500_ms")
    persistence_score = _field(fields, "persistence_score", "persistence")
    if persistence_score is None:
        persistence_score = np.full_like(sample, 50.0, dtype=float)
    else:
        persistence_score = _broadcast_to_sample(persistence_score, sample)

    training = weighted_mean(
        {
            "persistence": (persistence_score, 0.40),
            "moisture_convergence": (moisture_convergence_score, 0.40),
            "slow_motion": (slow_motion_score, 0.20),
        },
        sample=sample,
    )

    rainrate_score = _rainrate_score(fields, common)
    model_precip_score = _model_precip_score(fields, common)

    mid_cold_score = _threshold_score_neg(_field(fields, "t500", "temperature500"), common, "t500_c")
    lapse_rate_score = _lapse_rate_score(fields, common)
    freezing_score = _freezing_level_score(fields, common)
    lcl_score = _lcl_score(fields, common, sample)
    srh_score = _threshold_score_pos(_field(fields, "srh", "srh_0_3km"), common, "srh")
    discrete_score = _field(fields, "discrete_storm_score")
    if discrete_score is None:
        discrete_score = np.full_like(sample, 50.0, dtype=float)
    else:
        discrete_score = _broadcast_to_sample(discrete_score, sample)

    return {
        "sample": sample,
        "moisture": moisture,
        "moisture_score": moisture["score"],
        "deep_moisture": deep_moisture,
        "deep_moisture_score": deep_moisture["score"],
        "moisture_transport_score": moisture_transport_score,
        "moisture_convergence_score": moisture_convergence_score,
        "low_level_convergence_score": low_level_convergence_score,
        "ascent_score": ascent_score,
        "cape_score": cape_score,
        "k_score": k_score,
        "li_score": li_score,
        "instability": instability,
        "instability_score": instability["score"],
        "cin_breakable_score": cin_score,
        "trigger_score": trigger_score,
        "deep_shear_score": deep_shear_score,
        "low_level_shear_score": low_level_shear_score,
        "dcape_score": dcape_score,
        "mid_dry": mid_dry,
        "mid_dry_score": mid_dry["score"],
        "upper_wind_score": upper_wind_score,
        "slow_motion_score": slow_motion_score,
        "persistence_score": persistence_score,
        "training": training,
        "training_score": training["score"],
        "rainrate_score": rainrate_score,
        "model_precip_score": model_precip_score,
        "mid_cold_score": mid_cold_score,
        "lapse_rate_score": lapse_rate_score,
        "freezing_level_score": freezing_score,
        "lcl_score": lcl_score,
        "srh_score": srh_score,
        "discrete_storm_score": discrete_score,
    }


def score_persistent_heavy_rain(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    result = weighted_mean(
        _weighted_inputs(
            "persistent_heavy_rain",
            config,
            {
                "moisture_transport": common["moisture_transport_score"],
                "moisture_convergence": common["moisture_convergence_score"],
                "ascent": common["ascent_score"],
                "deep_moisture": common["deep_moisture_score"],
                "low_level_convergence": common["low_level_convergence_score"],
                "model_precip": common["model_precip_score"],
                "persistence": common["persistence_score"],
                "system_support": _field(fields, "system_support_score", "system_support"),
            },
        ),
        sample=sample,
    )
    score = result["score"]
    confidence = result["confidence"]
    score = _cap(score, 35.0, _below(common["moisture_score"], 30.0, sample) & _below(common["moisture_transport_score"], 30.0, sample))
    score = _cap(score, 45.0, _below(common["ascent_score"], 25.0, sample) & _below(common["low_level_convergence_score"], 25.0, sample))
    score = _cap(score, 55.0, _below(common["deep_moisture_score"], 35.0, sample))
    confidence = np.where(
        _above(common["model_precip_score"], 70.0, sample)
        & _below(common["moisture_convergence_score"], 30.0, sample)
        & _below(common["ascent_score"], 30.0, sample),
        confidence * 0.6,
        confidence,
    )
    metadata = _critical_factor_metadata("persistent_heavy_rain", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "persistent_heavy_rain",
        ["precipitation"],
        score,
        confidence,
        result["factors"],
        ["低层水汽输送、水汽辐合、上升运动、深厚湿层和模式累计降水综合评分"],
        metadata,
    )


def score_precip_short_duration_heavy_rain(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    result = weighted_mean(
        _weighted_inputs(
            "precip_short_duration_heavy_rain",
            config,
            {
                "moisture": common["moisture_score"],
                "pw": _threshold_score_pos(_field(fields, "pw", "pw_mm", "precipitable_water"), _common_config(config), "pw_mm"),
                "moisture_convergence": common["moisture_convergence_score"],
                "low_level_convergence": common["low_level_convergence_score"],
                "ascent": common["ascent_score"],
                "instability": common["instability_score"],
                "k_index": common["k_score"],
                "training": common["training_score"],
                "rainrate": common["rainrate_score"],
            },
        ),
        sample=sample,
    )
    score = result["score"]
    confidence = result["confidence"]
    score = _cap(score, 35.0, _below(common["moisture_score"], 35.0, sample) & (_score_or_zero(result["factors"].get("pw"), sample) < 35.0))
    score = _cap(
        score,
        50.0,
        _below(common["moisture_convergence_score"], 30.0, sample) & _below(common["low_level_convergence_score"], 30.0, sample),
    )
    score = _cap(score, 55.0, _below(common["trigger_score"], 30.0, sample))
    confidence = np.where(
        _above(common["rainrate_score"], 80.0, sample) & _below(common["moisture_score"], 40.0, sample),
        confidence * 0.6,
        confidence,
    )
    metadata = _critical_factor_metadata("precip_short_duration_heavy_rain", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "precip_short_duration_heavy_rain",
        ["precipitation"],
        score,
        confidence,
        result["factors"],
        ["低层水汽、水汽辐合、触发、雨强和列车效应潜势综合评分"],
        metadata,
    )


def score_conv_short_duration_heavy_rain(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    precip_base = score_precip_short_duration_heavy_rain(fields, config)
    convective_character = weighted_mean(
        _weighted_inputs(
            "convective_character",
            config,
            {
                "instability": common["instability_score"],
                "cin_breakable": common["cin_breakable_score"],
                "trigger": common["trigger_score"],
                "low_level_moisture": common["moisture_score"],
                "deep_shear": common["deep_shear_score"],
                "k_index": common["k_score"],
            },
        ),
        sample=sample,
    )
    result = weighted_mean(
        _weighted_inputs(
            "conv_short_duration_heavy_rain",
            config,
            {
                "precip_short_heavy_rain_base": precip_base["score_grid"],
                "convective_character": convective_character["score"],
                "moisture_convergence": common["moisture_convergence_score"],
                "low_level_convergence": common["low_level_convergence_score"],
            },
        ),
        sample=sample,
    )
    score = result["score"]
    confidence = np.minimum(result["confidence"], precip_base["confidence_grid"])
    score = _cap(score, 50.0, _below(common["instability_score"], 25.0, sample) & _below(common["k_score"], 25.0, sample))
    score = _cap(score, 50.0, _below(common["cape_score"], 25.0, sample))
    score = _cap(score, 45.0, _below(common["cin_breakable_score"], 30.0, sample) & _below(common["trigger_score"], 40.0, sample))
    score = _cap(score, 45.0, _below(common["moisture_score"], 35.0, sample))
    score = _cap(score, 40.0, _below(common["instability_score"], 20.0, sample) & _below(common["deep_shear_score"], 20.0, sample))
    factors = {
        **result["factors"],
        "convective_character": {
            "field": "convective_character",
            "label": FACTOR_LABELS["convective_character"],
            "weight": _weights_for("conv_short_duration_heavy_rain", config).get("convective_character", 0.35),
            "score": convective_character["score"],
            "contribution": result["factors"].get("convective_character", {}).get("contribution", np.zeros_like(sample)),
        },
    }
    metadata = _critical_factor_metadata("conv_short_duration_heavy_rain", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "conv_short_duration_heavy_rain",
        ["severe_convection"],
        score,
        confidence,
        factors,
        ["短强降水基础、CAPE/K 指数、CIN 可突破和低层触发综合评分"],
        metadata,
    )


def score_short_duration_heavy_rain(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    precip = score_precip_short_duration_heavy_rain(fields, config)
    conv = score_conv_short_duration_heavy_rain(fields, config)
    score = np.nanmax(np.stack([precip["score_grid"], conv["score_grid"]]), axis=0)
    confidence = np.maximum(precip["confidence_grid"], conv["confidence_grid"])
    factors = {
        "precip_short_heavy_rain_view": {
            "field": "precip_short_heavy_rain_view",
            "label": "降水视角短时强降水",
            "weight": 0.5,
            "score": precip["score_grid"],
            "contribution": precip["score_grid"] * 0.5,
        },
        "conv_short_heavy_rain_view": {
            "field": "conv_short_heavy_rain_view",
            "label": "强对流视角短时强降水",
            "weight": 0.5,
            "score": conv["score_grid"],
            "contribution": conv["score_grid"] * 0.5,
        },
    }
    metadata = _critical_factor_metadata("short_duration_heavy_rain", fields, score)
    score, metadata = _apply_input_completeness_cap(score, metadata, score)
    return _hazard_output(
        "short_duration_heavy_rain",
        ["precipitation", "severe_convection"],
        score,
        confidence,
        factors,
        ["短时强降水按降水视角与强对流视角分别评分后取主导风险"],
        metadata,
    )


def score_thunderstorm_gale(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    storm_init = weighted_mean(
        _weighted_inputs(
            "storm_initiation",
            config,
            {
                "instability": common["instability_score"],
                "moisture": common["moisture_score"],
                "cin_breakable": common["cin_breakable_score"],
                "trigger": common["trigger_score"],
                "deep_shear": common["deep_shear_score"],
            },
        ),
        sample=sample,
    )
    linear_mode = weighted_mean(
        _weighted_inputs(
            "linear_mode",
            config,
            {
                "deep_shear": common["deep_shear_score"],
                "trigger_line": _field(fields, "trigger_line_score", "front_or_shearline_score"),
                "low_level_convergence": common["low_level_convergence_score"],
                "dcape": common["dcape_score"],
            },
        ),
        sample=sample,
    )
    result = weighted_mean(
        _weighted_inputs(
            "thunderstorm_gale",
            config,
            {
                "storm_initiation": storm_init["score"],
                "dcape": common["dcape_score"],
                "mid_dry": common["mid_dry_score"],
                "deep_shear": common["deep_shear_score"],
                "upper_wind": common["upper_wind_score"],
                "linear_mode": linear_mode["score"],
            },
        ),
        sample=sample,
    )
    score = result["score"]
    score = _cap(score, 35.0, _below(storm_init["score"], 30.0, sample))
    score = _cap(score, 55.0, _below(common["dcape_score"], 30.0, sample) & _below(common["mid_dry_score"], 30.0, sample))
    score = _cap(score, 65.0, _below(common["deep_shear_score"], 25.0, sample))
    score = _cap(score, 55.0, _below(common["instability_score"], 25.0, sample))
    metadata = _critical_factor_metadata("thunderstorm_gale", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "thunderstorm_gale",
        ["severe_convection"],
        score,
        result["confidence"],
        result["factors"],
        ["雷暴发生潜势、DCAPE/中层干空气、风切变和高空强风综合评分"],
        metadata,
    )


def score_hail(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    supercell_env = weighted_mean(
        _weighted_inputs(
            "supercell_env",
            config,
            {
                "cape": common["cape_score"],
                "deep_shear": common["deep_shear_score"],
                "low_level_shear": common["low_level_shear_score"],
                "trigger": common["trigger_score"],
            },
        ),
        sample=sample,
    )
    result = weighted_mean(
        _weighted_inputs(
            "hail",
            config,
            {
                "cape": common["cape_score"],
                "deep_shear": common["deep_shear_score"],
                "mid_cold": common["mid_cold_score"],
                "lapse_rate": common["lapse_rate_score"],
                "freezing_level": common["freezing_level_score"],
                "supercell_env": supercell_env["score"],
                "trigger": common["trigger_score"],
            },
        ),
        sample=sample,
    )
    score = result["score"]
    confidence = result["confidence"]
    score = _cap(score, 45.0, _below(common["cape_score"], 30.0, sample))
    score = _cap(score, 55.0, _below(common["deep_shear_score"], 30.0, sample))
    if common["freezing_level_score"] is not None:
        score = _cap(score, 60.0, _below(common["freezing_level_score"], 25.0, sample))
    score = _cap(score, 50.0, _below(common["trigger_score"], 30.0, sample))
    if _field(fields, "z0_c_m", "freezing_level_m") is None and common["lapse_rate_score"] is None:
        confidence = confidence * 0.75
    metadata = _critical_factor_metadata("hail", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "hail",
        ["severe_convection"],
        score,
        confidence,
        result["factors"],
        ["CAPE、深层风切变、中层冷空气、0℃ 层高度和触发条件综合评分"],
        metadata,
    )


def score_rotating_storm_supercell(fields: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    common = compute_common_factors(fields, config)
    sample = common["sample"]
    has_srh = _field(fields, "srh", "srh_0_3km") is not None
    section = "rotating_storm_supercell"
    weights = _weights_for(section, config)
    if not has_srh:
        weights = _section_config(section, config).get(
            "fallback_without_srh_weights",
            DEFAULT_RISK_SCORING[section]["fallback_without_srh_weights"],
        )
    result = weighted_mean(
        {
            "cape": (common["cape_score"], weights.get("cape", 0.0)),
            "deep_shear": (common["deep_shear_score"], weights.get("deep_shear", 0.0)),
            "low_level_shear": (common["low_level_shear_score"], weights.get("low_level_shear", 0.0)),
            "srh": (common["srh_score"] if has_srh else None, weights.get("srh", 0.0)),
            "lcl": (common["lcl_score"], weights.get("lcl", 0.0)),
            "cin_breakable": (common["cin_breakable_score"], weights.get("cin_breakable", 0.0)),
            "trigger": (common["trigger_score"], weights.get("trigger", 0.0)),
            "discrete_storm": (common["discrete_storm_score"], weights.get("discrete_storm", 0.0)),
        },
        sample=sample,
    )
    score = result["score"]
    confidence = result["confidence"]
    score = _cap(score, 45.0, _below(common["deep_shear_score"], 40.0, sample))
    score = _cap(score, 45.0, _below(common["cape_score"], 30.0, sample))
    score = _cap(score, 55.0, _below(common["low_level_shear_score"], 30.0, sample) & _below(common["srh_score"], 30.0, sample))
    score = _cap(score, 70.0, _below(common["lcl_score"], 25.0, sample))
    score = _cap(score, 55.0, _below(common["trigger_score"], 25.0, sample))
    if not has_srh:
        confidence = confidence * 0.75
    if _field(fields, "shear_0_1km", "low_level_shear") is None and not has_srh:
        confidence = confidence * 0.65
        score = _cap(score, 55.0, np.ones_like(sample, dtype=bool))
    metadata = _critical_factor_metadata("rotating_storm_or_supercell", fields, sample)
    score, metadata = _apply_input_completeness_cap(score, metadata, sample)
    return _hazard_output(
        "rotating_storm_or_supercell",
        ["severe_convection"],
        score,
        confidence,
        result["factors"],
        ["CAPE、深层风切变、低层风切变/SRH、LCL 和触发条件综合评分"],
        metadata,
    )


def score_severe_convection_composite(
    conv_short_duration_heavy_rain_score,
    thunderstorm_gale_score,
    hail_score,
    rotating_storm_supercell_score,
):
    members = np.stack(
        [
            np.asarray(conv_short_duration_heavy_rain_score, dtype=float),
            np.asarray(thunderstorm_gale_score, dtype=float),
            np.asarray(hail_score, dtype=float),
            np.asarray(rotating_storm_supercell_score, dtype=float),
        ]
    )
    sorted_members = np.sort(members, axis=0)
    return clamp(sorted_members[-1] * 0.65 + np.nanmean(sorted_members[-2:], axis=0) * 0.35)



CRITICAL_FACTOR_GROUPS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "persistent_heavy_rain": [
        ("moisture_flux", ("moisture_flux", "moisture_flux850")),
        ("moisture_convergence", ("moisture_convergence", "moisture_conv850")),
        ("ascent", ("omega700", "w700")),
        ("deep_moisture", ("rh850", "rh700", "rh500", "pw", "pw_mm")),
        ("model_precip", ("precip_24h", "precip_6h", "precipitation")),
    ],
    "precip_short_duration_heavy_rain": [
        ("low_level_moisture", ("q850", "q850_gkg", "td2m", "d2m", "pw", "pw_mm", "rh850")),
        ("moisture_convergence", ("moisture_convergence", "moisture_conv850", "div850", "divergence850")),
        ("trigger_or_ascent", ("omega700", "w700", "pva500", "upper_divergence", "div200", "div300")),
        ("instability", ("cape", "k_index", "k", "li")),
        ("rainrate", ("precip_1h", "precip_3h", "precipitation_1h", "precipitation_3h", "rainmax3", "precipitation")),
    ],
    "conv_short_duration_heavy_rain": [
        ("short_rain_base", ("precip_1h", "precip_3h", "precip_6h", "precipitation")),
        ("instability", ("cape", "k_index", "k", "li")),
        ("trigger", ("div850", "moisture_convergence", "pva500", "upper_divergence", "cin")),
        ("low_level_moisture", ("q850", "td2m", "d2m", "pw", "rh850")),
    ],
    "short_duration_heavy_rain": [
        ("low_level_moisture", ("q850", "q850_gkg", "td2m", "d2m", "pw", "pw_mm", "rh850")),
        ("moisture_convergence", ("moisture_convergence", "moisture_conv850", "div850", "divergence850")),
        ("trigger_or_ascent", ("omega700", "w700", "pva500", "upper_divergence", "div200", "div300", "cin")),
        ("instability", ("cape", "k_index", "k", "li")),
        ("short_period_precip", ("precip_1h", "precip_3h", "precipitation_1h", "precipitation_3h", "rainmax3", "precipitation")),
    ],
    "thunderstorm_gale": [
        ("instability", ("cape", "k_index", "k", "li")),
        ("dcape", ("dcape",)),
        ("mid_dry_air", ("rh700", "rh500")),
        ("deep_shear", ("shear_0_6km", "deep_shear", "shr6km", "shr850-200")),
        ("trigger", ("div850", "moisture_convergence", "pva500", "upper_divergence", "cin", "trigger_line_score")),
    ],
    "hail": [
        ("cape", ("cape",)),
        ("deep_shear", ("shear_0_6km", "deep_shear", "shr6km", "shr850-200")),
        ("mid_cold_or_lapse_rate", ("t500", "temperature500", "lapse_rate_700_500", "li")),
        ("freezing_level", ("z0_c_m", "freezing_level_m", "deg0l", "tw0_height")),
        ("trigger", ("div850", "moisture_convergence", "pva500", "upper_divergence", "cin")),
    ],
    "rotating_storm_or_supercell": [
        ("cape", ("cape",)),
        ("deep_shear", ("shear_0_6km", "deep_shear", "shr6km", "shr850-200")),
        ("low_level_shear", ("shear_0_1km", "low_level_shear", "shr1km", "shr0-1km")),
        ("srh", ("srh", "srh_0_3km")),
        ("lcl", ("lcl", "lcl_m", "t2m", "td2m", "d2m")),
        ("trigger", ("div850", "moisture_convergence", "pva500", "upper_divergence", "cin")),
    ],
}


def _field_available(fields: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    value = _field(fields, *aliases)
    if value is None:
        return False
    arr = np.asarray(value, dtype=float)
    return bool(arr.size and np.isfinite(arr).any())


def _critical_factor_metadata(risk_type: str, fields: dict[str, Any], sample) -> dict[str, Any]:
    sample_arr = _as_array(sample)
    groups = CRITICAL_FACTOR_GROUPS.get(risk_type, [])
    if not groups:
        return {
            "input_completeness_grid": np.ones_like(sample_arr, dtype=float),
            "input_completeness": 1.0,
            "missing_critical_factors": [],
            "available_critical_factors": [],
            "score_cap_grid": np.full_like(sample_arr, 100.0, dtype=float),
            "score_cap_applied_grid": np.zeros_like(sample_arr, dtype=bool),
            "score_cap_applied": False,
        }
    available = []
    missing = []
    for name, aliases in groups:
        if _field_available(fields, aliases):
            available.append(name)
        else:
            missing.append(name)
    completeness = len(available) / max(len(groups), 1)
    cap = 100.0
    if risk_type in {"thunderstorm_gale", "hail", "rotating_storm_or_supercell"}:
        if completeness < 0.50:
            cap = min(cap, 55.0)
        elif completeness < 0.70:
            cap = min(cap, 75.0)
    if risk_type == "rotating_storm_or_supercell":
        if "srh" in missing and "low_level_shear" in missing:
            cap = min(cap, 55.0)
        elif "srh" in missing:
            cap = min(cap, 70.0)
    elif risk_type == "hail":
        if "cape" in missing or "deep_shear" in missing:
            cap = min(cap, 60.0)
        if "freezing_level" in missing and "mid_cold_or_lapse_rate" in missing:
            cap = min(cap, 75.0)
    elif risk_type == "thunderstorm_gale":
        if "dcape" in missing and "mid_dry_air" in missing:
            cap = min(cap, 75.0)
    elif risk_type in {"precip_short_duration_heavy_rain", "conv_short_duration_heavy_rain", "short_duration_heavy_rain"}:
        if "low_level_moisture" in missing and "moisture_convergence" in missing:
            cap = min(cap, 55.0)
        elif completeness < 0.50:
            cap = min(cap, 70.0)
    elif risk_type == "persistent_heavy_rain":
        if "deep_moisture" in missing and "moisture_flux" in missing:
            cap = min(cap, 70.0)

    return {
        "input_completeness_grid": np.full_like(sample_arr, float(completeness), dtype=float),
        "input_completeness": round(float(completeness), 6),
        "missing_critical_factors": missing,
        "available_critical_factors": available,
        "score_cap_grid": np.full_like(sample_arr, float(cap), dtype=float),
        "score_cap_applied_grid": np.zeros_like(sample_arr, dtype=bool),
        "score_cap_applied": False,
    }


def _apply_input_completeness_cap(score, metadata: dict[str, Any], sample) -> tuple[np.ndarray, dict[str, Any]]:
    sample_arr = _as_array(sample)
    score_arr = _broadcast_to_sample(score, sample_arr)
    cap_grid = _broadcast_to_sample(metadata.get("score_cap_grid", 100.0), sample_arr)
    capped = np.minimum(score_arr, cap_grid)
    applied = np.isfinite(score_arr) & (capped < score_arr - 1.0e-9)
    metadata = dict(metadata)
    metadata["score_cap_applied_grid"] = applied
    metadata["score_cap_applied"] = bool(np.any(applied))
    return capped, metadata


def _metadata_for_output(metadata: dict[str, Any] | None, score_grid: np.ndarray) -> dict[str, Any]:
    sample = np.asarray(score_grid, dtype=float)
    if metadata is None:
        metadata = _critical_factor_metadata("", {}, sample)
    completeness_grid = _broadcast_to_sample(metadata.get("input_completeness_grid", 1.0), sample)
    cap_grid = _broadcast_to_sample(metadata.get("score_cap_grid", 100.0), sample)
    cap_applied_grid = np.asarray(metadata.get("score_cap_applied_grid", np.zeros_like(sample, dtype=bool)), dtype=bool)
    if cap_applied_grid.shape != sample.shape:
        cap_applied_grid = np.broadcast_to(cap_applied_grid, sample.shape)
    finite_cap = cap_grid[np.isfinite(cap_grid)]
    score_cap_value = float(np.nanmin(finite_cap)) if finite_cap.size and float(np.nanmin(finite_cap)) < 100.0 else None
    return {
        "input_completeness_grid": completeness_grid,
        "input_completeness": float(np.nanmean(completeness_grid)) if completeness_grid.size else 1.0,
        "missing_critical_factors": list(metadata.get("missing_critical_factors", [])),
        "available_critical_factors": list(metadata.get("available_critical_factors", [])),
        "score_cap_grid": cap_grid,
        "score_cap_value": score_cap_value,
        "score_cap_applied_grid": cap_applied_grid,
        "score_cap_applied": bool(np.any(cap_applied_grid)),
    }


def _hazard_output(
    risk_type: str,
    domain: list[str],
    score,
    confidence,
    factor_scores: dict[str, Any],
    evidence: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score_grid = clamp(score)
    confidence_grid = np.clip(np.asarray(confidence, dtype=float), 0.0, 1.0)
    if confidence_grid.shape == ():
        confidence_grid = np.full_like(score_grid, float(confidence_grid), dtype=float)
    meta = _metadata_for_output(metadata, score_grid)
    return {
        "risk_type": risk_type,
        "domain": list(domain),
        "score_grid": score_grid,
        "level_grid": np.vectorize(risk_level, otypes=[object])(score_grid),
        "confidence_grid": confidence_grid,
        "input_completeness_grid": meta["input_completeness_grid"],
        "input_completeness": round(float(meta["input_completeness"]), 6),
        "missing_critical_factors": meta["missing_critical_factors"],
        "available_critical_factors": meta["available_critical_factors"],
        "score_cap_grid": meta["score_cap_grid"],
        "score_cap_value": meta["score_cap_value"],
        "score_cap_applied_grid": meta["score_cap_applied_grid"],
        "score_cap_applied": meta["score_cap_applied"],
        "factor_scores": factor_scores,
        "evidence": evidence,
        "main_reasons": evidence,
        "quality": {
            "input_completeness": round(float(meta["input_completeness"]), 6),
            "missing_critical_factors": meta["missing_critical_factors"],
            "available_critical_factors": meta["available_critical_factors"],
            "score_cap_applied": meta["score_cap_applied"],
            "score_cap_value": meta["score_cap_value"],
        },
    }


def _risk_config(config: dict[str, Any] | None) -> dict[str, Any]:
    user = (config or {}).get("risk_scoring", {})
    return _deep_merge(DEFAULT_RISK_SCORING, user)


def _common_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return _risk_config(config).get("common", {})


def _section_config(section: str, config: dict[str, Any] | None) -> dict[str, Any]:
    return _risk_config(config).get(section, {})


def _weights_for(section: str, config: dict[str, Any] | None) -> dict[str, float]:
    return dict(_section_config(section, config).get("weights", {}))


def _weighted_inputs(section: str, config: dict[str, Any] | None, values: dict[str, Any]) -> dict[str, tuple[Any, float, str]]:
    weights = _weights_for(section, config)
    return {
        factor: (values.get(factor), float(weights.get(factor, 0.0)), FACTOR_LABELS.get(factor, factor))
        for factor in weights
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _deep_merge(value, override.get(key, {}) if isinstance(override.get(key), dict) else {})
        else:
            merged[key] = override.get(key, value)
    for key, value in override.items():
        if key not in merged:
            merged[key] = value
    return merged


def _field(fields: dict[str, Any], *names: str):
    for name in names:
        if name in fields and fields[name] is not None:
            return fields[name]
    return None


def _sample_from_fields(fields: dict[str, Any]):
    for value in fields.values():
        if value is not None:
            return _as_array(value)
    return None


def _sample_from_factor_values(factors: dict[str, tuple[Any, float] | tuple[Any, float, str]]):
    for item in factors.values():
        if item[0] is not None:
            return _as_array(item[0])
    return None


def _as_array(value):
    arr = np.asarray(value, dtype=float)
    if arr.shape == ():
        arr = arr.reshape((1, 1))
    return arr


def _broadcast_to_sample(value, sample):
    arr = _as_array(value)
    if arr.shape == sample.shape:
        return arr.astype(float)
    if arr.size == 1:
        return np.full_like(sample, float(arr.ravel()[0]), dtype=float)
    return np.broadcast_to(arr, sample.shape).astype(float)


def _threshold_score_pos(value, common: dict[str, Any], key: str):
    if value is None:
        return None
    rule = common.get(key, {})
    return score_pos(value, float(rule.get("low", 0.0)), float(rule.get("high", 100.0)))


def _threshold_score_neg(value, common: dict[str, Any], key: str):
    if value is None:
        return None
    rule = common.get(key, {})
    return score_neg(value, high=float(rule.get("high", 100.0)), low=float(rule.get("low", 0.0)))


def _to_gkg(value):
    if value is None:
        return None
    arr = np.asarray(value, dtype=float)
    valid = np.abs(arr[np.isfinite(arr)])
    if valid.size and float(np.nanmax(valid)) < 1.0:
        return arr * 1000.0
    return arr


def _scale_moisture_flux(value):
    if value is None:
        return None
    arr = np.asarray(value, dtype=float)
    valid = np.abs(arr[np.isfinite(arr)])
    if valid.size and float(np.nanmax(valid)) < 5.0:
        return arr * 1000.0
    return arr


def _positive(value):
    if value is None:
        return None
    return np.maximum(np.asarray(value, dtype=float), 0.0)


def _negative(value):
    if value is None:
        return None
    return np.maximum(-np.asarray(value, dtype=float), 0.0)


def _positive_percentile_score(value):
    positive = _positive(value)
    if positive is None:
        return None
    valid = positive[np.isfinite(positive) & (positive > 0)]
    if valid.size == 0:
        return np.zeros_like(positive, dtype=float)
    p70, p95 = np.nanpercentile(valid, [70, 95])
    if p95 > p70:
        return score_percentile(positive, float(p70), float(p95))
    return score_pos(positive, 0.0, max(float(p95), 1.0e-12))


def _cin_breakable_score(value):
    if value is None:
        return None
    cin_abs = np.abs(np.asarray(value, dtype=float))
    return np.select(
        [cin_abs <= 25.0, cin_abs <= 75.0, cin_abs <= 150.0, cin_abs <= 250.0],
        [100.0, 80.0, 50.0, 20.0],
        default=0.0,
    ).astype(float)


def _nanmax_scores(scores: list[Any], sample):
    available = [np.asarray(item, dtype=float) for item in scores if item is not None]
    if not available:
        return None
    return np.nanmax(np.stack([_broadcast_to_sample(item, sample) for item in available]), axis=0)


def _rainrate_score(fields: dict[str, Any], common: dict[str, Any]):
    precip_1h = _field(fields, "precip_1h", "precipitation_1h")
    if precip_1h is not None:
        return _threshold_score_pos(precip_1h, common, "precip_1h_mm")
    precip_3h = _field(fields, "precip_3h", "precipitation_3h")
    if precip_3h is not None:
        return _threshold_score_pos(precip_3h, common, "precip_3h_mm")
    precip = _field(fields, "precipitation", "precip_6h")
    if precip is not None:
        return _threshold_score_pos(precip, common, "precip_3h_mm")
    return None


def _model_precip_score(fields: dict[str, Any], common: dict[str, Any]):
    precip_24h = _field(fields, "precip_24h", "precipitation_24h")
    if precip_24h is not None:
        return _threshold_score_pos(precip_24h, common, "precip_24h_mm")
    precip = _field(fields, "precipitation", "precip_6h")
    if precip is not None:
        return _threshold_score_pos(precip, common, "precip_6h_mm")
    return None


def _lapse_rate_score(fields: dict[str, Any], common: dict[str, Any]):
    lapse_rate = _field(fields, "lapse_rate_700_500")
    if lapse_rate is None:
        t700 = _field(fields, "t700", "temperature700")
        t500 = _field(fields, "t500", "temperature500")
        z700 = _field(fields, "z700", "height700")
        z500 = _field(fields, "z500", "height500")
        if all(item is not None for item in [t700, t500, z700, z500]):
            dz = np.asarray(z500, dtype=float) - np.asarray(z700, dtype=float)
            lapse_rate = np.divide(
                np.asarray(t700, dtype=float) - np.asarray(t500, dtype=float),
                dz,
                out=np.zeros_like(np.asarray(t500, dtype=float)),
                where=np.abs(dz) > 1.0e-6,
            ) * 1000.0
    return _threshold_score_pos(lapse_rate, common, "lapse_rate_700_500")


def _freezing_level_score(fields: dict[str, Any], common: dict[str, Any]):
    z0 = _field(fields, "z0_c_m", "freezing_level_m")
    if z0 is None:
        return None
    rule = common.get("freezing_level_m", {})
    return score_triangular(
        z0,
        float(rule.get("min", 1800.0)),
        float(rule.get("opt_low", 2500.0)),
        float(rule.get("opt_high", 4200.0)),
        float(rule.get("max", 5600.0)),
    )


def _lcl_score(fields: dict[str, Any], common: dict[str, Any], sample):
    lcl = _field(fields, "lcl", "lcl_m")
    if lcl is None:
        t2m = _field(fields, "t2m", "temperature2m")
        td2m = _field(fields, "td2m", "d2m", "dewpoint2m")
        if t2m is not None and td2m is not None:
            lcl = np.maximum((np.asarray(t2m, dtype=float) - np.asarray(td2m, dtype=float)) * 125.0, 0.0)
    if lcl is None:
        return None
    return _threshold_score_neg(_broadcast_to_sample(lcl, sample), common, "lcl_m")


def _cap(score, cap_value: float, condition):
    condition_arr = np.asarray(condition, dtype=bool)
    return np.where(condition_arr, np.minimum(score, cap_value), score)


def _score_or_zero(detail: dict[str, Any] | None, sample):
    if not detail:
        return np.zeros_like(sample, dtype=float)
    return _broadcast_to_sample(detail.get("score", 0.0), sample)


def _below(value, threshold: float, sample):
    if value is None:
        return np.zeros_like(sample, dtype=bool)
    return _broadcast_to_sample(value, sample) < threshold


def _above(value, threshold: float, sample):
    if value is None:
        return np.zeros_like(sample, dtype=bool)
    return _broadcast_to_sample(value, sample) >= threshold
