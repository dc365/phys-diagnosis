from __future__ import annotations

import numpy as np

from weather_diag.diagnostics.grid import component_axis_line, derivatives_lonlat, mask_to_bbox_features, normalize01
from weather_diag.io.geojson import line_feature

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


def _axis_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        dx = (lon1 - lon0) * 111.32 * max(np.cos(np.deg2rad((lat0 + lat1) / 2.0)), 0.2)
        dy = (lat1 - lat0) * 111.32
        total += float(np.hypot(dx, dy))
    return total


def _front_axis_features(
    derived: dict,
    lat,
    lon,
    *,
    min_points: int,
    max_objects: int,
    evidence: list[str],
) -> list[dict]:
    score = np.asarray(derived["score"], dtype=float)
    gradient = np.asarray(derived["gradient"], dtype=float)
    components = mask_to_bbox_features(derived["mask"], lat, lon, min_points=min_points)
    ranked = []
    for item in components:
        ys, xs = item["indices"]
        line = component_axis_line(item, lat, lon)
        coords = line.get("coordinates", [])
        if len(coords) < 2:
            continue
        values = score[ys, xs]
        grads = gradient[ys, xs]
        ranked.append(
            {
                "item": item,
                "line": line,
                "mean_score": float(np.nanmean(values)),
                "max_score": float(np.nanmax(values)),
                "mean_gradient": float(np.nanmean(grads)),
                "max_gradient": float(np.nanmax(grads)),
                "axis_length_km": _axis_length_km(coords),
            }
        )
    ranked.sort(
        key=lambda item: (
            item["axis_length_km"],
            item["max_score"],
            item["mean_score"],
            item["item"].get("point_count", 0),
        ),
        reverse=True,
    )
    if max_objects > 0:
        ranked = ranked[:max_objects]
    features = []
    for rank, item in enumerate(ranked, start=1):
        source = item["item"]
        props = {
            "id": f"front_candidate_{rank:03d}",
            "feature_type": "front_candidate",
            "title": "850hPa 锋面候选轴线",
            "level": "850hPa",
            "rank": rank,
            "geometry_role": "axis",
            "source_area_point_count": source["point_count"],
            "source_area_bbox": source["bbox"],
            "centroid": source["centroid"],
            "axis_length_km": round(item["axis_length_km"], 1),
            "max_value": item["max_score"],
            "mean_value": item["mean_score"],
            "max_gradient": item["max_gradient"],
            "mean_gradient": item["mean_gradient"],
            "score_threshold": derived["score_threshold"],
            "gradient_threshold": derived["gradient_threshold"],
            "frontogenesis_threshold": derived["frontogenesis_threshold"],
            "wind_deformation_threshold": derived["wind_deformation_threshold"],
            "confidence": 0.68,
            "evidence": evidence + ["候选锋区已抽取为 LineString 轴线，业务图层默认不输出面区域"],
        }
        features.append(line_feature(item["line"]["coordinates"], props))
    return features


def front_axis_components(
    derived: dict,
    lat,
    lon,
    *,
    min_points: int,
    max_objects: int,
) -> list[dict]:
    score = np.asarray(derived["score"], dtype=float)
    gradient = np.asarray(derived["gradient"], dtype=float)
    items = mask_to_bbox_features(derived["mask"], lat, lon, min_points=min_points)
    components = []
    for item in items:
        ys, xs = item["indices"]
        if ys.size == 0:
            continue
        line = component_axis_line(item, lat, lon, max_points=64)
        coords = line.get("coordinates") or []
        if len(coords) < 2:
            continue
        values = score[ys, xs]
        gradient_values = gradient[ys, xs]
        components.append(
            {
                "item": item,
                "line": line,
                "point_count": int(item["point_count"]),
                "mean_score": float(np.nanmean(values)),
                "max_score": float(np.nanmax(values)),
                "mean_gradient": float(np.nanmean(gradient_values)),
                "max_gradient": float(np.nanmax(gradient_values)),
            }
        )
    components.sort(
        key=lambda item: (item["max_score"], item["mean_score"], item["point_count"]),
        reverse=True,
    )
    if max_objects > 0:
        components = components[:max_objects]
    for rank, component in enumerate(components, start=1):
        component["rank"] = rank
    return components


def detect_front_candidate_axes(
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
    evidence = ["850hPa 温度梯度较大"]
    if u850 is not None and v850 is not None:
        evidence.append("850hPa 风场形变和锋生函数提供动力支撑")
    if div850 is not None:
        evidence.append("低层存在辐合信号")
    if temp_adv850 is not None:
        evidence.append("温度平流变化明显")
    features = _front_axis_features(
        derived,
        lat,
        lon,
        min_points=min_pts,
        max_objects=max_objects,
        evidence=evidence,
    )
    for feature in features:
        feature["properties"]["confidence"] = 0.66 if u850 is not None and v850 is not None else 0.58
    return features


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
    output_geometry = str(cfg.get("output_geometry", "axis")).lower()
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

    if output_geometry in {"area", "polygon"}:
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
                "geometry_role": "area",
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
    else:
        features = _front_axis_features(
            derived,
            lat,
            lon,
            min_points=min_pts,
            max_objects=max_objects,
            evidence=evidence,
        )
        for f in features:
            f["properties"]["confidence"] = 0.66 if u850 is not None and v850 is not None else 0.58

    if max_objects > 0:
        features = features[:max_objects]
    for rank, feature in enumerate(features, start=1):
        feature["properties"]["rank"] = rank
    return features
