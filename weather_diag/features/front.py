from __future__ import annotations

import numpy as np

from weather_diag.diagnostics.grid import component_axis_line, derivatives_lonlat, mask_to_bbox_features, normalize01
from weather_diag.io.geojson import line_feature

from .areas import mask_area_features


FRONT_TYPE_LABELS = {
    "cold_front": "冷锋候选",
    "warm_front": "暖锋候选",
    "stationary_front": "静止锋候选",
    "mixed_front": "混合锋面候选",
    "front_candidate": "锋面候选",
}

FRONT_MOTION_LABELS = {
    "cold_air_advancing": "冷空气向暖侧推进",
    "warm_air_overrunning": "暖空气向冷侧爬升/推进",
    "quasi_stationary": "准静止或移速较弱",
    "mixed_or_uncertain": "冷暖平流混合或不确定",
    "undetermined": "缺少风场，无法判别移向",
}

FRONT_AXIS_DEFAULT_MAX_POINTS = 28
FRONT_AXIS_DEFAULT_SMOOTH_ITERATIONS = 3


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


def _thermal_front_diagnostics(
    dtdx: np.ndarray,
    dtdy: np.ndarray,
    u850: np.ndarray | None,
    v850: np.ndarray | None,
    temp_adv850: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Return cross-front wind and signed temperature advection diagnostics.

    The thermal normal points from the cold side toward the warm side because it
    follows +grad(T). A positive cross-front wind therefore means the low-level
    flow has a component from cold air toward warm air, which is the objective
    signal used here for a cold-front candidate. A negative value means warm-air
    flow toward the cold side and supports a warm-front candidate.

    `temperature_advection = -V·grad(T)`: positive means warm advection and
    negative means cold advection. If a model ttadv product is supplied, it is
    kept as the primary advection field; otherwise the value is computed from
    the 850hPa wind and temperature gradient.
    """
    gradient = np.sqrt(dtdx**2 + dtdy**2)
    cross_front_wind = np.full_like(gradient, np.nan, dtype=float)
    computed_advection = np.zeros_like(gradient, dtype=float)

    if u850 is not None and v850 is not None:
        nx = np.divide(dtdx, gradient, out=np.zeros_like(gradient), where=gradient > 1e-12)
        ny = np.divide(dtdy, gradient, out=np.zeros_like(gradient), where=gradient > 1e-12)
        cross_front_wind = u850 * nx + v850 * ny
        computed_advection = -(u850 * dtdx + v850 * dtdy)

    if temp_adv850 is not None:
        thermal_advection = np.asarray(temp_adv850, dtype=float)
        source = "model_ttadv850"
    elif u850 is not None and v850 is not None:
        thermal_advection = computed_advection
        source = "computed_from_uv850_t850"
    else:
        thermal_advection = np.zeros_like(gradient, dtype=float)
        source = "unavailable"

    return cross_front_wind, computed_advection, thermal_advection, source


def _support_mask(values: np.ndarray, percentile: float) -> tuple[np.ndarray, float]:
    threshold = _finite_percentile(values, percentile)
    if not np.isfinite(threshold) or threshold <= 0:
        return np.zeros_like(values, dtype=bool), threshold
    return values > threshold, threshold


def _finite_fraction(values: np.ndarray, predicate) -> float:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(np.mean(predicate(finite)))


def _finite_mean(values: np.ndarray, default: float = 0.0) -> float:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return default
    return float(np.nanmean(finite))


def _classify_front_component(ys: np.ndarray, xs: np.ndarray, derived: dict, cfg: dict) -> dict:
    cross = np.asarray(derived.get("cross_front_wind"), dtype=float)
    advection = np.asarray(derived.get("temperature_advection"), dtype=float)
    gradient = np.asarray(derived.get("gradient"), dtype=float)

    cross_threshold = float(cfg.get("cross_front_wind_min_ms", 1.0))
    stationary_threshold = float(cfg.get("stationary_cross_front_max_ms", 0.8))
    consistency_min = float(cfg.get("front_type_consistency_min", 0.55))
    mixed_gap = float(cfg.get("front_type_mixed_gap", 0.15))

    if cross.size == 0 or not np.isfinite(cross[ys, xs]).any():
        return {
            "front_type": "front_candidate",
            "front_type_label": FRONT_TYPE_LABELS["front_candidate"],
            "front_motion": "undetermined",
            "front_motion_label": FRONT_MOTION_LABELS["undetermined"],
            "front_type_confidence": 0.45,
            "cross_front_wind_mean_ms": None,
            "cross_front_wind_abs_mean_ms": None,
            "cold_front_ratio": None,
            "warm_front_ratio": None,
            "stationary_front_ratio": None,
            "temperature_advection_mean": _finite_mean(advection[ys, xs], 0.0) if advection.size else None,
            "temperature_advection_source": derived.get("temperature_advection_source", "unavailable"),
            "classification_reason": "缺少 850hPa 风场，保留为未分类锋面候选。",
        }

    cross_values = cross[ys, xs]
    advection_values = advection[ys, xs] if advection.size else np.array([], dtype=float)
    gradient_values = gradient[ys, xs] if gradient.size else np.array([], dtype=float)
    mean_cross = _finite_mean(cross_values)
    abs_mean_cross = _finite_mean(np.abs(cross_values))
    cold_ratio = _finite_fraction(cross_values, lambda value: value >= cross_threshold)
    warm_ratio = _finite_fraction(cross_values, lambda value: value <= -cross_threshold)
    stationary_ratio = _finite_fraction(cross_values, lambda value: np.abs(value) <= stationary_threshold)
    advection_mean = _finite_mean(advection_values)
    gradient_mean = _finite_mean(gradient_values)

    cold_score = cold_ratio + (0.12 if mean_cross > 0 else 0.0) + (0.10 if advection_mean < 0 else 0.0)
    warm_score = warm_ratio + (0.12 if mean_cross < 0 else 0.0) + (0.10 if advection_mean > 0 else 0.0)

    if (
        stationary_ratio >= consistency_min
        and abs(mean_cross) <= stationary_threshold
        and max(cold_ratio, warm_ratio) < consistency_min
    ):
        front_type = "stationary_front"
        motion = "quasi_stationary"
        reason = "锋面法向风较弱，冷暖侧推进信号均不占优，判为静止锋候选。"
        type_strength = stationary_ratio
    elif cold_score >= warm_score + mixed_gap and (cold_ratio >= consistency_min or mean_cross >= 0.35 * cross_threshold):
        front_type = "cold_front"
        motion = "cold_air_advancing"
        reason = "850hPa 风在温度梯度法向上主要由冷侧指向暖侧，并伴随冷平流或冷侧推进信号。"
        type_strength = min(1.0, cold_score)
    elif warm_score >= cold_score + mixed_gap and (warm_ratio >= consistency_min or mean_cross <= -0.35 * cross_threshold):
        front_type = "warm_front"
        motion = "warm_air_overrunning"
        reason = "850hPa 风在温度梯度法向上主要由暖侧指向冷侧，并伴随暖平流或暖空气爬升推进信号。"
        type_strength = min(1.0, warm_score)
    else:
        front_type = "mixed_front"
        motion = "mixed_or_uncertain"
        reason = "冷锋与暖锋信号接近或空间上混合，暂标记为混合锋面候选。"
        type_strength = max(cold_ratio, warm_ratio, stationary_ratio)

    confidence = 0.48 + 0.34 * float(np.clip(type_strength, 0.0, 1.0))
    if abs(advection_mean) > 0 and front_type in {"cold_front", "warm_front"}:
        sign_ok = (front_type == "cold_front" and advection_mean < 0) or (front_type == "warm_front" and advection_mean > 0)
        confidence += 0.08 if sign_ok else -0.08
    if gradient_mean > 0:
        confidence += 0.04
    confidence = float(np.clip(confidence, 0.35, 0.9))

    return {
        "front_type": front_type,
        "front_type_label": FRONT_TYPE_LABELS[front_type],
        "front_motion": motion,
        "front_motion_label": FRONT_MOTION_LABELS[motion],
        "front_type_confidence": round(confidence, 3),
        "cross_front_wind_mean_ms": round(mean_cross, 3),
        "cross_front_wind_abs_mean_ms": round(abs_mean_cross, 3),
        "cold_front_ratio": round(cold_ratio, 3),
        "warm_front_ratio": round(warm_ratio, 3),
        "stationary_front_ratio": round(stationary_ratio, 3),
        "temperature_advection_mean": float(advection_mean),
        "temperature_advection_source": derived.get("temperature_advection_source", "unavailable"),
        "classification_reason": reason,
    }


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
    cross_front_wind, computed_advection, thermal_advection, thermal_advection_source = _thermal_front_diagnostics(
        dtdx,
        dtdy,
        u850,
        v850,
        temp_adv850,
    )
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

    if temp_adv850 is not None or dynamic_fields_available:
        advection = np.abs(thermal_advection)
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
        "dtdx": dtdx,
        "dtdy": dtdy,
        "gradient": gradient,
        "score": score,
        "mask": mask,
        "support_count": support_count,
        "frontogenesis": frontogenesis,
        "wind_deformation": wind_deformation,
        "cross_front_wind": cross_front_wind,
        "computed_temperature_advection": computed_advection,
        "temperature_advection": thermal_advection,
        "temperature_advection_source": thermal_advection_source,
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


def _front_axis_line(item: dict, lat, lon, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    max_points = int(cfg.get("axis_max_points", FRONT_AXIS_DEFAULT_MAX_POINTS))
    smooth_iterations = int(cfg.get("axis_smooth_iterations", FRONT_AXIS_DEFAULT_SMOOTH_ITERATIONS))
    return component_axis_line(
        item,
        lat,
        lon,
        max_points=max_points,
        smooth=True,
        smooth_iterations=smooth_iterations,
    )


def _front_axis_features(
    derived: dict,
    lat,
    lon,
    *,
    min_points: int,
    max_objects: int,
    evidence: list[str],
    cfg: dict | None = None,
) -> list[dict]:
    cfg = cfg or {}
    score = np.asarray(derived["score"], dtype=float)
    gradient = np.asarray(derived["gradient"], dtype=float)
    components = mask_to_bbox_features(derived["mask"], lat, lon, min_points=min_points)
    ranked = []
    for item in components:
        ys, xs = item["indices"]
        line = _front_axis_line(item, lat, lon, cfg)
        coords = line.get("coordinates", [])
        if len(coords) < 2:
            continue
        values = score[ys, xs]
        grads = gradient[ys, xs]
        classification = _classify_front_component(ys, xs, derived, cfg)
        ranked.append(
            {
                "item": item,
                "line": line,
                "classification": classification,
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
            item["classification"].get("front_type_confidence") or 0,
            item["item"].get("point_count", 0),
        ),
        reverse=True,
    )
    if max_objects > 0:
        ranked = ranked[:max_objects]
    features = []
    for rank, item in enumerate(ranked, start=1):
        source = item["item"]
        cls = item["classification"]
        props = {
            "id": f"front_candidate_{rank:03d}",
            "feature_type": "front_candidate",
            "title": f"850hPa {cls['front_type_label']}轴线",
            "level": "850hPa",
            "rank": rank,
            "geometry_role": "axis",
            "front_type": cls["front_type"],
            "front_type_label": cls["front_type_label"],
            "front_motion": cls["front_motion"],
            "front_motion_label": cls["front_motion_label"],
            "front_type_confidence": cls["front_type_confidence"],
            "cross_front_wind_mean_ms": cls["cross_front_wind_mean_ms"],
            "cross_front_wind_abs_mean_ms": cls["cross_front_wind_abs_mean_ms"],
            "cold_front_ratio": cls["cold_front_ratio"],
            "warm_front_ratio": cls["warm_front_ratio"],
            "stationary_front_ratio": cls["stationary_front_ratio"],
            "temperature_advection_mean": cls["temperature_advection_mean"],
            "temperature_advection_source": cls["temperature_advection_source"],
            "classification_reason": cls["classification_reason"],
            "source_area_point_count": source["point_count"],
            "source_area_bbox": source["bbox"],
            "centroid": source["centroid"],
            "axis_length_km": round(item["axis_length_km"], 1),
            "axis_smoothing": "weather_chart_chaikin",
            "max_value": item["max_score"],
            "mean_value": item["mean_score"],
            "max_gradient": item["max_gradient"],
            "mean_gradient": item["mean_gradient"],
            "score_threshold": derived["score_threshold"],
            "gradient_threshold": derived["gradient_threshold"],
            "frontogenesis_threshold": derived["frontogenesis_threshold"],
            "wind_deformation_threshold": derived["wind_deformation_threshold"],
            "confidence": 0.68,
            "evidence": evidence
            + [
                "候选锋区已抽取为 LineString 轴线，业务图层默认不输出面区域",
                cls["classification_reason"],
            ],
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
    thresholds: dict | None = None,
) -> list[dict]:
    cfg = (thresholds or {}).get("front_candidate", {}) if thresholds else {}
    score = np.asarray(derived["score"], dtype=float)
    gradient = np.asarray(derived["gradient"], dtype=float)
    items = mask_to_bbox_features(derived["mask"], lat, lon, min_points=min_points)
    components = []
    for item in items:
        ys, xs = item["indices"]
        if ys.size == 0:
            continue
        line = _front_axis_line(item, lat, lon, cfg)
        coords = line.get("coordinates") or []
        if len(coords) < 2:
            continue
        values = score[ys, xs]
        gradient_values = gradient[ys, xs]
        classification = _classify_front_component(ys, xs, derived, cfg)
        components.append(
            {
                "item": item,
                "line": line,
                "classification": classification,
                "front_type": classification["front_type"],
                "front_type_label": classification["front_type_label"],
                "front_motion": classification["front_motion"],
                "point_count": int(item["point_count"]),
                "mean_score": float(np.nanmean(values)),
                "max_score": float(np.nanmax(values)),
                "mean_gradient": float(np.nanmean(gradient_values)),
                "max_gradient": float(np.nanmax(gradient_values)),
                "axis_smoothing": "weather_chart_chaikin",
            }
        )
    components.sort(
        key=lambda item: (
            item["max_score"],
            item["mean_score"],
            item["classification"].get("front_type_confidence") or 0,
            item["point_count"],
        ),
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
        evidence.append("850hPa 风场形变、锋生函数和锋面法向风提供动力支撑")
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
        cfg=cfg,
    )
    for feature in features:
        type_conf = feature["properties"].get("front_type_confidence") or 0.0
        base = 0.66 if u850 is not None and v850 is not None else 0.58
        feature["properties"]["confidence"] = round(float(np.clip(base + 0.12 * (type_conf - 0.5), 0.45, 0.85)), 2)
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
        evidence.append("850hPa 风场形变、锋生函数和锋面法向风提供动力支撑")
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
            cfg=cfg,
        )
        for f in features:
            type_conf = f["properties"].get("front_type_confidence") or 0.0
            base = 0.66 if u850 is not None and v850 is not None else 0.58
            f["properties"]["confidence"] = round(float(np.clip(base + 0.12 * (type_conf - 0.5), 0.45, 0.85)), 2)

    if max_objects > 0:
        features = features[:max_objects]
    for rank, feature in enumerate(features, start=1):
        feature["properties"]["rank"] = rank
    return features
