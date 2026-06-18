from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import normalize01
from .areas import mask_area_features


def _w(weights, key, default=0.0):
    return float(weights.get(key, default))


def heavy_rain_score(fields: dict, thresholds: dict) -> np.ndarray:
    weights = thresholds.get("heavy_rain_risk", {}).get("weights", {})
    sample = next(v for v in fields.values() if v is not None)
    score = np.zeros_like(sample, dtype=float)
    if fields.get("moisture_flux") is not None:
        score += _w(weights, "moisture_flux") * normalize01(fields["moisture_flux"], 10, 98)
    if fields.get("moisture_convergence") is not None:
        score += _w(weights, "moisture_convergence") * normalize01(np.maximum(fields["moisture_convergence"], 0), 10, 98)
    if fields.get("div850") is not None:
        score += _w(weights, "low_level_convergence") * normalize01(np.maximum(-fields["div850"], 0), 10, 98)
    if fields.get("omega700") is not None:
        score += _w(weights, "upward_motion") * normalize01(np.maximum(-fields["omega700"], 0), 10, 98)
    if fields.get("k_index") is not None:
        score += _w(weights, "k_index") * normalize01(fields["k_index"], 10, 98)
    if fields.get("cape") is not None:
        score += _w(weights, "cape") * normalize01(fields["cape"], 10, 98)
    if fields.get("precipitation") is not None:
        score += _w(weights, "precipitation") * normalize01(fields["precipitation"], 10, 98)
    return np.clip(score, 0, 1)


def convection_score(fields: dict, thresholds: dict) -> np.ndarray:
    weights = thresholds.get("convection_risk", {}).get("weights", {})
    sample = next(v for v in fields.values() if v is not None)
    score = np.zeros_like(sample, dtype=float)
    if fields.get("cape") is not None:
        score += _w(weights, "cape") * normalize01(fields["cape"], 10, 98)
    if fields.get("cin") is not None:
        # CIN often negative. Smaller absolute inhibition is more favorable.
        cin_abs = np.abs(fields["cin"])
        score += _w(weights, "cin") * (1.0 - normalize01(cin_abs, 5, 95))
    if fields.get("k_index") is not None:
        score += _w(weights, "k_index") * normalize01(fields["k_index"], 10, 98)
    if fields.get("shear_0_6km") is not None:
        score += _w(weights, "shear_0_6km") * normalize01(fields["shear_0_6km"], 10, 98)
    if fields.get("div850") is not None:
        score += _w(weights, "low_level_convergence") * normalize01(np.maximum(-fields["div850"], 0), 10, 98)
    if fields.get("moisture") is not None:
        score += _w(weights, "moisture") * normalize01(fields["moisture"], 10, 98)
    return np.clip(score, 0, 1)


def detect_heavy_rain_risk(score: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("heavy_rain_risk", {})
    thr = float(cfg.get("score_threshold", 0.62))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    return mask_area_features(score >= thr, lat, lon, feature_type="heavy_rain_risk", title="强降水潜势区",
                              value_field=score, min_points=min_pts,
                              evidence=["水汽输送、水汽辐合、上升运动和热力条件综合评分较高"],
                              extra_props={"score_threshold": thr})


def detect_convection_risk(score: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("convection_risk", {})
    thr = float(cfg.get("score_threshold", 0.60))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    return mask_area_features(score >= thr, lat, lon, feature_type="convection_risk", title="强对流潜势区",
                              value_field=score, min_points=min_pts,
                              evidence=["CAPE、CIN、风切变、低层水汽和触发条件综合评分较高"],
                              extra_props={"score_threshold": thr})
