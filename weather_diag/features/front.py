from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import derivatives_lonlat, normalize01
from .areas import mask_area_features


def detect_front_candidates(t850: np.ndarray, div850: np.ndarray | None, temp_adv850: np.ndarray | None, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("front_candidate", {})
    p_grad = float(cfg.get("temp_gradient_percentile", 80))
    p_score = float(cfg.get("score_percentile", 82))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    dtdx, dtdy = derivatives_lonlat(t850, lat, lon)
    grad = np.sqrt(dtdx ** 2 + dtdy ** 2)
    grad_score = normalize01(grad, 5, 98)
    score = 0.60 * grad_score
    evidence = ["850hPa 温度梯度较大"]
    if div850 is not None:
        conv_score = normalize01(np.maximum(-div850, 0), 5, 98)
        score += 0.25 * conv_score
        evidence.append("低层存在辐合信号")
    if temp_adv850 is not None:
        adv_grad = normalize01(np.abs(temp_adv850), 5, 98)
        score += 0.15 * adv_grad
        evidence.append("温度平流变化明显")
    thr = float(np.nanpercentile(score, p_score))
    mask = score >= thr
    features = mask_area_features(
        mask, lat, lon,
        feature_type="front_candidate",
        title="锋面候选区",
        value_field=score,
        min_points=min_pts,
        threshold_desc="温度梯度、低层辐合和温度平流综合评分较高",
        evidence=evidence + ["MVP 阶段仅作为锋面候选，需人工订正"],
        extra_props={"level": "850hPa", "score_threshold": thr},
    )
    for f in features:
        f["properties"]["confidence"] = 0.58
    return features
