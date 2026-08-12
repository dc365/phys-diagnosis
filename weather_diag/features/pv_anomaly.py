from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.io.geojson import polygon_feature


def _nan_smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    if sigma <= 0:
        return arr.copy()
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weight = finite.astype(float)
    smooth = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weight, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smooth, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def _finite_percentile(values: np.ndarray, percentile: float, default: float = 0.0) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return default
    return float(np.nanpercentile(valid, percentile))


def detect_pv_anomaly(
    pv_upper: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    level: int = 300,
    pv_advection: np.ndarray | None = None,
    rh_mid: np.ndarray | None = None,
) -> list[dict]:
    """Detect upper-level PV anomaly / dry-intrusion support areas.

    This is intentionally a supporting diagnosis rather than a default primary
    weather system. It is useful for hail, thunderstorm-gale and baroclinic
    development risk because upper-level PV maxima often mark dry intrusion and
    dynamic lifting around troughs.
    """
    cfg = thresholds.get("pv_anomaly", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    p = float(cfg.get("pv_percentile", 90.0))
    min_pv = float(cfg.get("pv_min", 1.5))
    min_pts = int(cfg.get("min_area_grid_points", 8))
    max_objects = int(cfg.get("max_objects", 8))
    pv = _nan_smooth(pv_upper, sigma)
    threshold = max(min_pv, _finite_percentile(pv, p, min_pv))
    mask = pv >= threshold
    if pv_advection is not None and bool(cfg.get("require_positive_pv_advection", False)):
        mask &= np.asarray(pv_advection, dtype=float) > 0
    dry_score = None
    if rh_mid is not None:
        dry_score = np.maximum(100.0 - np.asarray(rh_mid, dtype=float), 0.0)
        if "mid_dry_rh_max" in cfg:
            mask &= np.asarray(rh_mid, dtype=float) <= float(cfg["mid_dry_rh_max"])
    items = mask_to_bbox_features(mask, lat, lon, min_points=min_pts)
    ranked = []
    for item in items:
        ys, xs = item["indices"]
        pv_values = pv[ys, xs]
        ranked.append(
            {
                "item": item,
                "mean_pv": float(np.nanmean(pv_values)),
                "max_pv": float(np.nanmax(pv_values)),
                "mean_dry_score": None if dry_score is None else float(np.nanmean(dry_score[ys, xs])),
            }
        )
    ranked.sort(key=lambda item: (item["max_pv"], item["mean_pv"], item["item"].get("point_count", 0)), reverse=True)
    if max_objects > 0:
        ranked = ranked[:max_objects]
    features = []
    for rank, item in enumerate(ranked, start=1):
        source = item["item"]
        features.append(
            polygon_feature(
                source["geometry"],
                {
                    "id": f"pv_anomaly_{level}_{rank:03d}",
                    "feature_type": "pv_anomaly",
                    "title": f"{level}hPa 高空 PV 异常区",
                    "level": f"{level}hPa",
                    "rank": rank,
                    "point_count": source["point_count"],
                    "bbox": source["bbox"],
                    "centroid": source["centroid"],
                    "pv_threshold": threshold,
                    "mean_pv": item["mean_pv"],
                    "max_pv": item["max_pv"],
                    "mean_dry_score": item["mean_dry_score"],
                    "confidence": round(min(0.88, 0.55 + item["max_pv"] / max(threshold, 1.0e-6) * 0.12), 2),
                    "evidence": [
                        "高空 PV 达到区域高值阈值",
                        "可作为槽前动力抬升、干侵入和强对流组织化的支撑诊断",
                        "中层相对湿度偏低，支持干侵入" if item["mean_dry_score"] is not None and item["mean_dry_score"] > 30 else "未提供或未确认中层干侵入",
                    ],
                },
            )
        )
    return features
