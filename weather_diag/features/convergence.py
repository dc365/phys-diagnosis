from __future__ import annotations

import numpy as np
from .areas import mask_area_features


def detect_low_level_convergence(div850: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("convergence", {})
    max_div = float(cfg.get("divergence_max", -1.0e-5))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    mask = np.asarray(div850) <= max_div
    return mask_area_features(
        mask, lat, lon,
        feature_type="low_level_convergence",
        title="850hPa 低层辐合区",
        value_field=-div850,
        min_points=min_pts,
        threshold_desc=f"850hPa 散度 <= {max_div:.1e}",
        evidence=["850hPa 散度为负值，表示低层辐合", "低层辐合有利于空气上升和降水触发"],
        extra_props={"level": "850hPa"},
    )


def detect_upper_divergence(div_upper: np.ndarray, lat, lon, thresholds: dict, level: int) -> list[dict]:
    cfg = thresholds.get("upper_divergence", {})
    min_div = float(cfg.get("divergence_min", 1.0e-5))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    mask = np.asarray(div_upper) >= min_div
    return mask_area_features(
        mask, lat, lon,
        feature_type="upper_divergence",
        title=f"{level}hPa 高空辐散区",
        value_field=div_upper,
        min_points=min_pts,
        threshold_desc=f"{level}hPa 散度 >= {min_div:.1e}",
        evidence=["高空散度为正值，表示高空辐散", "高空辐散有利于下方空气上升"],
        extra_props={"level": f"{level}hPa"},
    )
