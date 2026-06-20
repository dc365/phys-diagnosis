from __future__ import annotations

import numpy as np

from weather_diag.diagnostics.grid import derivatives_lonlat, normalize01

from .areas import mask_area_features


def _finite_percentile(values: np.ndarray, percentile: float) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return float("nan")
    return float(np.nanpercentile(valid, percentile))


def _frontogenesis(
    dtdx: np.ndarray,
    dtdy: np.ndarray,
    u850: np.ndarray,
    v850: np.ndarray,
    lat,
    lon,
) -> tuple[np.ndarray, np.ndarray]:
    dudx, dudy = derivatives_lonlat(u850, lat, lon)
    dvdx, dvdy = derivatives_lonlat(v850, lat, lon)
    deformation = np.sqrt((dudx - dvdy) ** 2 + (dudy + dvdx) ** 2)
    grad_mag = np.sqrt(dtdx**2 + dtdy**2)
    numerator = -(
        dtdx**2 * dudx
        + dtdy**2 * dvdy
        + dtdx * dtdy * (dudy + dvdx)
    )
    frontogen = np.divide(numerator, grad_mag, out=np.zeros_like(grad_mag), where=grad_mag > 1e-12)
    return np.maximum(frontogen, 0.0), deformation


def _support_mask(values: np.ndarray, percentile: float) -> tuple[np.ndarray, float]:
    threshold = _finite_percentile(values, percentile)
    if not np.isfinite(threshold) or threshold <= 0:
        return np.zeros_like(values, dtype=bool), threshold
    return values > threshold, threshold


def front_candidate_fields(
    t850: np.ndarray,
    div850: np.ndarray | None,
    temp_adv850: np.ndarray | None,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
    rh850: np.ndarray | None = None,
) -> dict:
    cfg = thresholds.get("front_candidate", {})
    p_grad = float(cfg.get("temp_gradient_percentile", 80))
    p_score = float(cfg.get("score_percentile", 82))
    p_dynamic = float(cfg.get("dynamic_support_percentile", 70))
    min_support = int(cfg.get("min_support_components", 1))

    dtdx, dtdy = derivatives_lonlat(t850, lat, lon)
    gradient = np.sqrt(dtdx**2 + dtdy**2)
    grad_score = normalize01(gradient, 5, 98)
    score_terms = [(0.45, grad_score)]
    support_count = np.zeros_like(gradient, dtype=int)

    frontogenesis = np.zeros_like(gradient, dtype=float)
    wind_deformation = np.zeros_like(gradient, dtype=float)
    frontogenesis_threshold = float("nan")
    wind_deformation_threshold = float("nan")
    dynamic_fields_available = u850 is not None and v850 is not None
    if dynamic_fields_available:
        frontogenesis, wind_deformation = _frontogenesis(dtdx, dtdy, u850, v850, lat, lon)
        frontogenesis_score = normalize01(frontogenesis, 20, 98)
        deformation_score = normalize01(wind_deformation, 20, 98)
        score_terms.extend([(0.18, frontogenesis_score), (0.17, deformation_score)])
        mask_part, frontogenesis_threshold = _support_mask(frontogenesis, p_dynamic)
        support_count += mask_part
        mask_part, wind_deformation_threshold = _support_mask(wind_deformation, p_dynamic)
        support_count += mask_part

    if div850 is not None:
        convergence = np.maximum(-div850, 0.0)
        conv_score = normalize01(convergence, 5, 98)
        score_terms.append((0.12, conv_score))
        mask_part, _ = _support_mask(convergence, p_dynamic)
        support_count += mask_part

    if temp_adv850 is not None:
        advection = np.abs(temp_adv850)
        adv_score = normalize01(advection, 5, 98)
        score_terms.append((0.06, adv_score))
        mask_part, _ = _support_mask(advection, p_dynamic)
        support_count += mask_part

    if rh850 is not None:
        moisture_score = normalize01(rh850, 40, 95)
        score_terms.append((0.02, moisture_score))
        mask_part, _ = _support_mask(rh850, max(60.0, p_dynamic))
        support_count += mask_part

    weight_sum = sum(weight for weight, _ in score_terms)
    score = sum(weight * term for weight, term in score_terms) / max(weight_sum, 1e-6)

    gradient_threshold = _finite_percentile(gradient, p_grad)
    score_threshold = _finite_percentile(score, p_score)
    mask = (score >= score_threshold) & (gradient >= gradient_threshold)
    if dynamic_fields_available:
        mask &= support_count >= min_support

    return {
        "gradient": gradient,
        "score": score,
        "mask": mask,
        "support_count": support_count,
        "frontogenesis": frontogenesis,
        "wind_deformation": wind_deformation,
        "gradient_percentile": p_grad,
        "score_percentile": p_score,
        "dynamic_support_percentile": p_dynamic,
        "gradient_threshold": gradient_threshold,
        "score_threshold": score_threshold,
        "frontogenesis_threshold": frontogenesis_threshold,
        "wind_deformation_threshold": wind_deformation_threshold,
    }


def detect_front_candidates(
    t850: np.ndarray,
    div850: np.ndarray | None,
    temp_adv850: np.ndarray | None,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
    rh850: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("front_candidate", {})
    min_pts = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 12))
    derived = front_candidate_fields(
        t850,
        div850,
        temp_adv850,
        lat,
        lon,
        thresholds,
        u850=u850,
        v850=v850,
        rh850=rh850,
    )
    score = derived["score"]
    evidence = ["850hPa 温度梯度较大"]
    if u850 is not None and v850 is not None:
        evidence.append("850hPa 风场形变和锋生函数提供动力支撑")
    if div850 is not None:
        evidence.append("低层存在辐合信号")
    if temp_adv850 is not None:
        evidence.append("温度平流变化明显")
    features = mask_area_features(
        derived["mask"],
        lat,
        lon,
        feature_type="front_candidate",
        title="锋面候选区",
        value_field=score,
        min_points=min_pts,
        threshold_desc="温度梯度、风场形变、锋生函数和低层辐合综合评分较高",
        evidence=evidence,
        extra_props={
            "level": "850hPa",
            "score_threshold": derived["score_threshold"],
            "gradient_threshold": derived["gradient_threshold"],
            "frontogenesis_threshold": derived["frontogenesis_threshold"],
            "wind_deformation_threshold": derived["wind_deformation_threshold"],
        },
    )
    for f in features:
        f["properties"]["confidence"] = 0.66 if u850 is not None and v850 is not None else 0.58
    features.sort(
        key=lambda feature: (
            feature["properties"].get("point_count") or 0,
            feature["properties"].get("mean_value") or 0,
        ),
        reverse=True,
    )
    if max_objects > 0:
        features = features[:max_objects]
    for rank, feature in enumerate(features, start=1):
        feature["properties"]["rank"] = rank
    return features
