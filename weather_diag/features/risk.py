from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import mask_to_bbox_features, normalize01
from weather_diag.io.geojson import polygon_feature


def _w(weights, key, default=0.0):
    return float(weights.get(key, default))


def _positive(field: np.ndarray) -> np.ndarray:
    return np.maximum(field, 0.0)


def _negative(field: np.ndarray) -> np.ndarray:
    return np.maximum(-field, 0.0)


def _weak_inhibition(field: np.ndarray) -> np.ndarray:
    cin_abs = np.abs(field)
    return 1.0 - normalize01(cin_abs, 5, 95)


def _identity_score(field: np.ndarray) -> np.ndarray:
    return normalize01(field, 10, 98)


def _positive_score(field: np.ndarray) -> np.ndarray:
    return normalize01(_positive(field), 10, 98)


def _negative_score(field: np.ndarray) -> np.ndarray:
    return normalize01(_negative(field), 10, 98)


def _score_details(
    fields: dict,
    weights: dict,
    specs: list[dict],
) -> dict:
    sample = next(v for v in fields.values() if v is not None)
    score = np.zeros_like(sample, dtype=float)
    factors = {}
    available_weight = 0.0
    for spec in specs:
        field = fields.get(spec["field"])
        if field is None:
            continue
        weight = _w(weights, spec["factor"])
        factor_score = spec["score"](np.asarray(field, dtype=float))
        contribution = weight * factor_score
        score += contribution
        available_weight += weight
        factors[spec["factor"]] = {
            "field": spec["field"],
            "label": spec["label"],
            "weight": weight,
            "score": factor_score,
            "contribution": contribution,
        }
    return {
        "score": np.clip(score, 0, 1),
        "factors": factors,
        "available_weight": round(float(available_weight), 6),
    }


HEAVY_RAIN_SPECS = [
    {"factor": "moisture_flux", "field": "moisture_flux", "label": "水汽通量", "score": _identity_score},
    {"factor": "moisture_convergence", "field": "moisture_convergence", "label": "水汽辐合", "score": _positive_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合", "score": _negative_score},
    {"factor": "upward_motion", "field": "omega700", "label": "700hPa 上升运动", "score": _negative_score},
    {"factor": "k_index", "field": "k_index", "label": "K 指数", "score": _identity_score},
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "precipitation", "field": "precipitation", "label": "模式降水", "score": _identity_score},
]


CONVECTION_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "cin", "field": "cin", "label": "CIN 较弱", "score": _weak_inhibition},
    {"factor": "k_index", "field": "k_index", "label": "K 指数", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合触发", "score": _negative_score},
    {"factor": "moisture", "field": "moisture", "label": "低层水汽", "score": _identity_score},
]


PERSISTENT_HEAVY_RAIN_SPECS = [
    {"factor": "moisture_flux", "field": "moisture_flux", "label": "水汽通量", "score": _identity_score},
    {"factor": "moisture_convergence", "field": "moisture_convergence", "label": "水汽辐合", "score": _positive_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合", "score": _negative_score},
    {"factor": "upward_motion", "field": "omega700", "label": "700hPa 上升运动", "score": _negative_score},
    {"factor": "precipitation", "field": "precipitation", "label": "模式降水", "score": _identity_score},
]


SHORT_DURATION_HEAVY_RAIN_SPECS = [
    {"factor": "moisture_flux", "field": "moisture_flux", "label": "水汽通量", "score": _identity_score},
    {"factor": "moisture_convergence", "field": "moisture_convergence", "label": "水汽辐合", "score": _positive_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合触发", "score": _negative_score},
    {"factor": "k_index", "field": "k_index", "label": "K 指数", "score": _identity_score},
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "precipitation", "field": "precipitation", "label": "模式降水", "score": _identity_score},
]


THUNDERSTORM_GALE_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "dcape", "field": "dcape", "label": "DCAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层触发", "score": _negative_score},
]


HAIL_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "li", "field": "li", "label": "抬升指数", "score": _negative_score},
]


ROTATING_STORM_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "srh", "field": "srh", "label": "SRH", "score": _identity_score},
    {"factor": "shear_0_1km", "field": "shear_0_1km", "label": "0-1km 风切变", "score": _identity_score},
]


def heavy_rain_score_details(fields: dict, thresholds: dict) -> dict:
    weights = thresholds.get("heavy_rain_risk", {}).get("weights", {})
    return _score_details(fields, weights, HEAVY_RAIN_SPECS)


def heavy_rain_score(fields: dict, thresholds: dict) -> np.ndarray:
    return heavy_rain_score_details(fields, thresholds)["score"]


def convection_score_details(fields: dict, thresholds: dict) -> dict:
    weights = thresholds.get("convection_risk", {}).get("weights", {})
    return _score_details(fields, weights, CONVECTION_SPECS)


def convection_score(fields: dict, thresholds: dict) -> np.ndarray:
    return convection_score_details(fields, thresholds)["score"]


def multi_hazard_score_details(fields: dict, thresholds: dict) -> dict:
    specs = {
        "risk_persistent_heavy_rain_score": ("persistent_heavy_rain_risk", PERSISTENT_HEAVY_RAIN_SPECS),
        "risk_short_duration_heavy_rain_score": ("short_duration_heavy_rain_risk", SHORT_DURATION_HEAVY_RAIN_SPECS),
        "risk_thunderstorm_gale_score": ("thunderstorm_gale_risk", THUNDERSTORM_GALE_SPECS),
        "risk_hail_score": ("hail_risk", HAIL_SPECS),
        "risk_rotating_storm_score": ("rotating_storm_risk", ROTATING_STORM_SPECS),
    }
    scores = {}
    factors = {}
    available_weights = {}
    for grid_name, (cfg_name, cfg_specs) in specs.items():
        weights = thresholds.get(cfg_name, {}).get("weights", {})
        details = _score_details(fields, weights, cfg_specs)
        configured_weight = sum(_w(weights, spec["factor"]) for spec in cfg_specs)
        if configured_weight > 0:
            contributions = [detail["contribution"] for detail in details["factors"].values()]
            if contributions:
                raw_score = np.sum(np.stack(contributions), axis=0)
            else:
                raw_score = details["score"]
            scores[grid_name] = np.clip(raw_score / configured_weight, 0, 1)
        else:
            scores[grid_name] = details["score"]
        factors[grid_name] = details["factors"]
        available_weights[grid_name] = details["available_weight"]

    scores["risk_precipitation_composite_score"] = np.nanmax(
        np.stack(
            [
                scores["risk_persistent_heavy_rain_score"],
                scores["risk_short_duration_heavy_rain_score"],
            ]
        ),
        axis=0,
    )
    scores["risk_severe_convection_composite_score"] = np.nanmax(
        np.stack(
            [
                scores["risk_short_duration_heavy_rain_score"],
                scores["risk_thunderstorm_gale_score"],
                scores["risk_hail_score"],
                scores["risk_rotating_storm_score"],
            ]
        ),
        axis=0,
    )
    return {"scores": scores, "factors": factors, "available_weights": available_weights}


def _factor_dominance(
    factor_details: dict | None,
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    limit: int = 3,
) -> list[dict]:
    if not factor_details:
        return []
    out = []
    for factor, detail in factor_details.items():
        contribution = np.asarray(detail["contribution"], dtype=float)[ys, xs]
        score = np.asarray(detail.get("score", detail["contribution"]), dtype=float)[ys, xs]
        mean_contribution = float(np.nanmean(contribution)) if contribution.size else 0.0
        if mean_contribution <= 0:
            continue
        out.append(
            {
                "factor": factor,
                "label": detail.get("label", factor),
                "weight": float(detail.get("weight", 0.0)),
                "mean_score": round(float(np.nanmean(score)), 3),
                "mean_contribution": round(mean_contribution, 3),
            }
        )
    out.sort(key=lambda item: item["mean_contribution"], reverse=True)
    return out[:limit]


def _ranked_risk_features(
    score: np.ndarray,
    lat,
    lon,
    *,
    feature_type: str,
    title: str,
    cfg: dict,
    factor_details: dict | None,
    base_evidence: str,
) -> list[dict]:
    threshold = float(cfg.get("score_threshold", 0.6))
    high_threshold = float(cfg.get("high_score_threshold", max(0.72, threshold + 0.1)))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 8))
    components = mask_to_bbox_features(np.asarray(score) >= threshold, lat, lon, min_points=min_pts)
    components.sort(
        key=lambda item: (
            float(np.nanmax(score[item["indices"]])),
            float(np.nanmean(score[item["indices"]])),
            item["point_count"],
        ),
        reverse=True,
    )
    if max_objects > 0:
        components = components[:max_objects]

    features = []
    for rank, item in enumerate(components, start=1):
        ys, xs = item["indices"]
        values = np.asarray(score, dtype=float)[ys, xs]
        max_value = float(np.nanmax(values)) if values.size else 0.0
        mean_value = float(np.nanmean(values)) if values.size else 0.0
        core_points = int(np.count_nonzero(values >= high_threshold))
        risk_level = "high" if core_points > 0 else "moderate"
        dominant = _factor_dominance(factor_details, ys, xs)
        evidence = [
            base_evidence,
            f"综合评分最大值 {max_value:.2f}，平均值 {mean_value:.2f}",
        ]
        if core_points:
            evidence.append(f"核心区格点 {core_points} 个达到 {high_threshold:.2f} 高潜势阈值")
        else:
            evidence.append(f"外围区达到 {threshold:.2f} 中等潜势阈值，未形成高潜势核心")
        if dominant:
            evidence.append("主导因子：" + "、".join(f"{item['label']} {item['mean_contribution']:.2f}" for item in dominant))

        props = {
            "id": f"{feature_type}_{rank:03d}",
            "feature_type": feature_type,
            "title": title,
            "rank": rank,
            "risk_level": risk_level,
            "zone": "core" if core_points else "outer",
            "confidence": round(min(0.9, 0.55 + max_value * 0.35), 2),
            "point_count": item["point_count"],
            "core_point_count": core_points,
            "centroid": item["centroid"],
            "bbox": item["bbox"],
            "max_value": max_value,
            "mean_value": mean_value,
            "score_threshold": threshold,
            "high_score_threshold": high_threshold,
            "dominant_factors": dominant,
            "evidence": evidence,
        }
        features.append(polygon_feature(item["geometry"], props))
    return features


def detect_heavy_rain_risk(
    score: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    factor_details: dict | None = None,
) -> list[dict]:
    cfg = thresholds.get("heavy_rain_risk", {})
    return _ranked_risk_features(
        score,
        lat,
        lon,
        feature_type="heavy_rain_risk",
        title="强降水潜势区",
        cfg=cfg,
        factor_details=factor_details,
        base_evidence="水汽输送、水汽辐合、低层辐合、上升运动和热力条件综合评分较高",
    )


def detect_convection_risk(
    score: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    factor_details: dict | None = None,
) -> list[dict]:
    cfg = thresholds.get("convection_risk", {})
    return _ranked_risk_features(
        score,
        lat,
        lon,
        feature_type="convection_risk",
        title="强对流潜势区",
        cfg=cfg,
        factor_details=factor_details,
        base_evidence="CAPE、CIN、风切变、低层水汽、低层触发条件综合评分较高",
    )
