from __future__ import annotations

import numpy as np
from .areas import mask_area_features


def detect_subtropical_high(z500: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("subtropical_high", {})
    contour = float(cfg.get("contour_gpm", 5880))
    min_pts = int(cfg.get("min_area_grid_points", 20))
    mask = np.asarray(z500) >= contour
    return mask_area_features(
        mask, lat, lon,
        feature_type="subtropical_high",
        title="副热带高压 5880gpm 区域",
        value_field=z500,
        min_points=min_pts,
        threshold_desc=f"500hPa 位势高度 >= {contour:.0f} gpm",
        evidence=[f"500hPa 位势高度达到或超过 {contour:.0f} gpm", "MVP 以 5880gpm 区域近似表示副高范围"],
        extra_props={"level": "500hPa", "contour_gpm": contour},
    )
