from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.diagnostics.grid import component_axis_line, derivatives_lonlat, mask_to_bbox_features, normalize01
from weather_diag.io.geojson import line_feature


def _finite_percentile(values: np.ndarray, percentile: float, default: float = 0.0) -> float:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return default
    return float(np.nanpercentile(valid, percentile))


def _line_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        mean_lat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * 111.32 * max(np.cos(np.deg2rad(mean_lat)), 0.2)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _nan_smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    arr = np.asarray(field, dtype=float)
    if sigma <= 0:
        return arr.copy()
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)
    weights = finite.astype(float)
    smooth = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    weight_sum = ndimage.gaussian_filter(weights, sigma=sigma, mode="nearest")
    out = np.full_like(arr, np.nan, dtype=float)
    np.divide(smooth, weight_sum, out=out, where=weight_sum > 1.0e-6)
    return out


def detect_surface_boundaries(
    t2m: np.ndarray,
    td2m: np.ndarray | None,
    u10: np.ndarray | None,
    v10: np.ndarray | None,
    lat,
    lon,
    thresholds: dict,
) -> list[dict]:
    """Detect surface thermal/moisture boundary candidates.

    This is a lightweight supporting algorithm for drylines, dewpoint fronts and
    surface frontal zones. It is intentionally conservative because 2m fields are
    sensitive to terrain and land-surface biases.
    """
    cfg = thresholds.get("surface_boundary", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    temp = _nan_smooth(t2m, sigma)
    dtdx, dtdy = derivatives_lonlat(temp, lat, lon)
    temp_grad = np.sqrt(dtdx**2 + dtdy**2)
    score_terms = [(0.45, normalize01(temp_grad, 50, 98))]

    td_grad = np.zeros_like(temp_grad)
    if td2m is not None:
        dewpoint = _nan_smooth(td2m, sigma)
        dddx, dddy = derivatives_lonlat(dewpoint, lat, lon)
        td_grad = np.sqrt(dddx**2 + dddy**2)
        score_terms.append((0.35, normalize01(td_grad, 50, 98)))

    convergence = np.zeros_like(temp_grad)
    if u10 is not None and v10 is not None:
        dudx, _dudy = derivatives_lonlat(u10, lat, lon)
        _dvdx, dvdy = derivatives_lonlat(v10, lat, lon)
        convergence = np.maximum(-(dudx + dvdy), 0.0)
        score_terms.append((0.20, normalize01(convergence, 50, 98)))

    weight_sum = sum(weight for weight, _ in score_terms)
    score = sum(weight * term for weight, term in score_terms) / max(weight_sum, 1.0e-6)
    score_threshold = _finite_percentile(score, float(cfg.get("score_percentile", 86.0)))
    temp_threshold = _finite_percentile(temp_grad, float(cfg.get("temp_gradient_percentile", 80.0)))
    mask = (score >= score_threshold) & (temp_grad >= temp_threshold)
    min_points = int(cfg.get("min_area_grid_points", 8))
    max_objects = int(cfg.get("max_objects", 8))
    min_length_km = float(cfg.get("min_length_km", 120.0))
    items = mask_to_bbox_features(mask, lat, lon, min_points=min_points)
    ranked = []
    for item in items:
        ys, xs = item["indices"]
        line = component_axis_line(item, lat, lon, max_points=64)
        coords = line.get("coordinates") or []
        length_km = _line_length_km(coords)
        if len(coords) < 2 or length_km < min_length_km:
            continue
        dewpoint_dominant = td2m is not None and float(np.nanmean(td_grad[ys, xs])) > float(np.nanmean(temp_grad[ys, xs]))
        feature_type = "dryline_candidate" if dewpoint_dominant else "surface_front_candidate"
        ranked.append(
            {
                "item": item,
                "line": line,
                "length_km": length_km,
                "feature_type": feature_type,
                "mean_score": float(np.nanmean(score[ys, xs])),
                "max_score": float(np.nanmax(score[ys, xs])),
                "mean_temp_gradient": float(np.nanmean(temp_grad[ys, xs])),
                "mean_dewpoint_gradient": float(np.nanmean(td_grad[ys, xs])) if td2m is not None else None,
                "mean_convergence": float(np.nanmean(convergence[ys, xs])) if u10 is not None and v10 is not None else None,
            }
        )
    ranked.sort(key=lambda item: (item["max_score"], item["mean_score"], item["length_km"]), reverse=True)
    if max_objects > 0:
        ranked = ranked[:max_objects]
    features = []
    for rank, item in enumerate(ranked, start=1):
        title = "地面干线/露点锋候选" if item["feature_type"] == "dryline_candidate" else "地面锋区候选"
        features.append(
            line_feature(
                item["line"]["coordinates"],
                {
                    "id": f"{item['feature_type']}_{rank:03d}",
                    "feature_type": item["feature_type"],
                    "title": title,
                    "level": "surface",
                    "rank": rank,
                    "axis_length_km": round(item["length_km"], 1),
                    "mean_score": item["mean_score"],
                    "max_score": item["max_score"],
                    "mean_temp_gradient": item["mean_temp_gradient"],
                    "mean_dewpoint_gradient": item["mean_dewpoint_gradient"],
                    "mean_convergence": item["mean_convergence"],
                    "confidence": 0.58,
                    "evidence": [
                        "2m 温度或露点梯度显著",
                        "10m 风辐合支持边界触发" if u10 is not None and v10 is not None else "未提供 10m 风，暂不做地面辐合支撑",
                        "该算法为辅助候选，需结合实况和地形订正",
                    ],
                },
            )
        )
    return features
