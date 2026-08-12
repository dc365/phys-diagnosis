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


def _line_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        mean_lat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * 111.32 * max(np.cos(np.deg2rad(mean_lat)), 0.2)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _wind_diagnostics(u: np.ndarray, v: np.ndarray, lat, lon) -> dict[str, np.ndarray]:
    dudx, dudy = derivatives_lonlat(u, lat, lon)
    dvdx, dvdy = derivatives_lonlat(v, lat, lon)
    divergence = dudx + dvdy
    vorticity = dvdx - dudy
    shear_deformation = np.sqrt((dudx - dvdy) ** 2 + (dudy + dvdx) ** 2)
    speed = np.hypot(u, v)
    return {
        "divergence": divergence,
        "convergence": np.maximum(-divergence, 0.0),
        "vorticity": vorticity,
        "positive_vorticity": np.maximum(vorticity, 0.0),
        "shear_deformation": shear_deformation,
        "speed": speed,
    }


def shear_line_fields(
    u: np.ndarray,
    v: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    temperature: np.ndarray | None = None,
    moisture: np.ndarray | None = None,
) -> dict:
    cfg = thresholds.get("shear_line", {})
    sigma = float(cfg.get("smoothing_sigma_grid", 1.0))
    p_score = float(cfg.get("score_percentile", 84.0))
    p_dynamic = float(cfg.get("dynamic_percentile", 75.0))
    min_vorticity = float(cfg.get("vorticity_min", 1.0e-5))
    min_convergence = float(cfg.get("convergence_min", 4.0e-6))

    u_s = _nan_smooth(u, sigma)
    v_s = _nan_smooth(v, sigma)
    diag = _wind_diagnostics(u_s, v_s, lat, lon)

    vort_score = normalize01(diag["positive_vorticity"], 50, 98)
    conv_score = normalize01(diag["convergence"], 50, 98)
    deform_score = normalize01(diag["shear_deformation"], 50, 98)
    speed_score = normalize01(diag["speed"], 20, 95)
    score_terms = [(0.34, vort_score), (0.28, conv_score), (0.24, deform_score), (0.08, speed_score)]

    thermal_gradient = np.zeros_like(u_s, dtype=float)
    thermal_gradient_score = np.zeros_like(u_s, dtype=float)
    if temperature is not None:
        dtdx, dtdy = derivatives_lonlat(np.asarray(temperature, dtype=float), lat, lon)
        thermal_gradient = np.sqrt(dtdx**2 + dtdy**2)
        thermal_gradient_score = normalize01(thermal_gradient, 50, 98)
        # Temperature gradient is a weak negative weight for pure shear lines. If
        # it is very strong, the object should normally be rendered as a front or
        # front_with_shear rather than a pure shear line.
        score_terms.append((0.03, 1.0 - thermal_gradient_score))

    moisture_score = np.zeros_like(u_s, dtype=float)
    if moisture is not None:
        moisture_score = normalize01(np.asarray(moisture, dtype=float), 40, 95)
        score_terms.append((0.03, moisture_score))

    weight_sum = sum(weight for weight, _ in score_terms)
    score = sum(weight * term for weight, term in score_terms) / max(weight_sum, 1.0e-6)
    score_threshold = _finite_percentile(score, p_score)
    vort_threshold = max(min_vorticity, _finite_percentile(diag["positive_vorticity"], p_dynamic))
    conv_threshold = max(min_convergence, _finite_percentile(diag["convergence"], p_dynamic))
    deform_threshold = _finite_percentile(diag["shear_deformation"], p_dynamic)

    dynamic_support = (
        (diag["positive_vorticity"] >= vort_threshold).astype(int)
        + (diag["convergence"] >= conv_threshold).astype(int)
        + (diag["shear_deformation"] >= deform_threshold).astype(int)
    )
    mask = (score >= score_threshold) & (dynamic_support >= int(cfg.get("min_support_components", 2)))

    if temperature is not None and bool(cfg.get("separate_front_with_shear", True)):
        front_like_threshold = _finite_percentile(thermal_gradient, float(cfg.get("front_gradient_percentile", 85.0)))
        front_like = thermal_gradient >= front_like_threshold
    else:
        front_like = np.zeros_like(mask, dtype=bool)

    return {
        **diag,
        "score": score,
        "mask": mask,
        "front_like_mask": front_like,
        "thermal_gradient": thermal_gradient,
        "thermal_gradient_score": thermal_gradient_score,
        "moisture_score": moisture_score,
        "score_threshold": score_threshold,
        "vorticity_threshold": vort_threshold,
        "convergence_threshold": conv_threshold,
        "deformation_threshold": deform_threshold,
        "dynamic_support": dynamic_support,
    }


def detect_shear_lines(
    u: np.ndarray,
    v: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    level: int = 850,
    temperature: np.ndarray | None = None,
    moisture: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("shear_line", {})
    min_points = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 8))
    min_length_km = float(cfg.get("min_length_km", 300.0))
    fields = shear_line_fields(u, v, lat, lon, thresholds, temperature=temperature, moisture=moisture)
    items = mask_to_bbox_features(fields["mask"], lat, lon, min_points=min_points)
    ranked = []
    for item in items:
        ys, xs = item["indices"]
        line = component_axis_line(item, lat, lon, max_points=64)
        coords = line.get("coordinates") or []
        length_km = _line_length_km(coords)
        if len(coords) < 2 or length_km < min_length_km:
            continue
        score_values = fields["score"][ys, xs]
        vort_values = fields["positive_vorticity"][ys, xs]
        conv_values = fields["convergence"][ys, xs]
        front_ratio = float(np.mean(fields["front_like_mask"][ys, xs])) if ys.size else 0.0
        if front_ratio >= float(cfg.get("front_with_shear_ratio_min", 0.45)):
            shear_type = "front_with_shear"
            title = f"{level}hPa 锋区切变线"
        else:
            shear_type = "shear_line"
            title = f"{level}hPa 切变线"
        ranked.append(
            {
                "item": item,
                "line": line,
                "length_km": length_km,
                "mean_score": float(np.nanmean(score_values)),
                "max_score": float(np.nanmax(score_values)),
                "mean_vorticity": float(np.nanmean(vort_values)),
                "max_vorticity": float(np.nanmax(vort_values)),
                "mean_convergence": float(np.nanmean(conv_values)),
                "front_like_ratio": front_ratio,
                "shear_type": shear_type,
                "title": title,
            }
        )
    ranked.sort(key=lambda item: (item["max_score"], item["mean_score"], item["length_km"]), reverse=True)
    if max_objects > 0:
        ranked = ranked[:max_objects]

    features = []
    for rank, item in enumerate(ranked, start=1):
        props = {
            "id": f"{item['shear_type']}_{level}_{rank:03d}",
            "feature_type": item["shear_type"],
            "title": item["title"],
            "level": f"{level}hPa",
            "rank": rank,
            "geometry_role": "axis",
            "point_count": int(item["item"].get("point_count", 0)),
            "source_area_bbox": item["item"].get("bbox"),
            "axis_length_km": round(float(item["length_km"]), 1),
            "mean_score": item["mean_score"],
            "max_score": item["max_score"],
            "mean_positive_vorticity": item["mean_vorticity"],
            "max_positive_vorticity": item["max_vorticity"],
            "mean_convergence": item["mean_convergence"],
            "front_like_ratio": round(float(item["front_like_ratio"]), 3),
            "score_threshold": fields["score_threshold"],
            "vorticity_threshold": fields["vorticity_threshold"],
            "convergence_threshold": fields["convergence_threshold"],
            "deformation_threshold": fields["deformation_threshold"],
            "confidence": round(min(0.88, 0.55 + 0.22 * item["max_score"] + 0.08 * min(item["length_km"], 1200.0) / 1200.0), 2),
            "evidence": [
                "风向或风速水平切变显著",
                "正涡度带、低层辐合和形变共同支撑切变线候选",
                "温度梯度较强时标记为 front_with_shear，以便与锋面候选区分",
            ],
        }
        features.append(line_feature(item["line"]["coordinates"], props))
    return features
