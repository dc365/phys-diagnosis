from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.features.risk_scoring import (
    score_hail,
    score_persistent_heavy_rain,
    score_severe_convection_composite,
    score_short_duration_heavy_rain,
    score_thunderstorm_gale,
    score_rotating_storm_supercell,
)
from weather_diag.io.geojson import polygon_feature


def multi_hazard_score_details(fields: dict, thresholds: dict) -> dict:
    hazard_outputs = {
        "risk_persistent_heavy_rain_score": score_persistent_heavy_rain(fields, thresholds),
        "risk_short_duration_heavy_rain_score": score_short_duration_heavy_rain(fields, thresholds),
        "risk_thunderstorm_gale_score": score_thunderstorm_gale(fields, thresholds),
        "risk_hail_score": score_hail(fields, thresholds),
        "risk_rotating_storm_score": score_rotating_storm_supercell(fields, thresholds),
    }
    scores = {}
    factors = {}
    available_weights = {}
    metadata = {}
    for grid_name, output in hazard_outputs.items():
        scores[grid_name] = np.clip(np.asarray(output["score_grid"], dtype=float) / 100.0, 0.0, 1.0)
        factors[grid_name] = _factor_details_01(output["factor_scores"])
        available_weights[grid_name] = round(float(np.nanmax(output["confidence_grid"])), 6)
        metadata[grid_name] = _hazard_output_metadata_01(output)

    composite_100 = score_severe_convection_composite(
        hazard_outputs["risk_short_duration_heavy_rain_score"]["score_grid"],
        hazard_outputs["risk_thunderstorm_gale_score"]["score_grid"],
        hazard_outputs["risk_hail_score"]["score_grid"],
        hazard_outputs["risk_rotating_storm_score"]["score_grid"],
    )
    scores["risk_severe_convection_composite_score"] = np.clip(composite_100 / 100.0, 0.0, 1.0)
    factors["risk_severe_convection_composite_score"] = {
        "short_duration_heavy_rain": {
            "field": "risk_short_duration_heavy_rain_score",
            "label": "短时强降水",
            "weight": 0.25,
            "score": scores["risk_short_duration_heavy_rain_score"],
            "contribution": scores["risk_short_duration_heavy_rain_score"] * 0.25,
        },
        "thunderstorm_gale": {
            "field": "risk_thunderstorm_gale_score",
            "label": "雷暴大风/下击暴流",
            "weight": 0.25,
            "score": scores["risk_thunderstorm_gale_score"],
            "contribution": scores["risk_thunderstorm_gale_score"] * 0.25,
        },
        "hail": {
            "field": "risk_hail_score",
            "label": "冰雹",
            "weight": 0.25,
            "score": scores["risk_hail_score"],
            "contribution": scores["risk_hail_score"] * 0.25,
        },
        "rotating_storm": {
            "field": "risk_rotating_storm_score",
            "label": "旋转风暴/超级单体潜势",
            "weight": 0.25,
            "score": scores["risk_rotating_storm_score"],
            "contribution": scores["risk_rotating_storm_score"] * 0.25,
        },
    }
    available_weights["risk_severe_convection_composite_score"] = float(
        np.nanmax(
            np.stack(
                [
                    np.asarray(hazard_outputs["risk_short_duration_heavy_rain_score"]["confidence_grid"], dtype=float),
                    np.asarray(hazard_outputs["risk_thunderstorm_gale_score"]["confidence_grid"], dtype=float),
                    np.asarray(hazard_outputs["risk_hail_score"]["confidence_grid"], dtype=float),
                    np.asarray(hazard_outputs["risk_rotating_storm_score"]["confidence_grid"], dtype=float),
                ]
            )
        )
    )
    metadata["risk_severe_convection_composite_score"] = _composite_metadata(
        [
            metadata["risk_short_duration_heavy_rain_score"],
            metadata["risk_thunderstorm_gale_score"],
            metadata["risk_hail_score"],
            metadata["risk_rotating_storm_score"],
        ]
    )
    quality = {
        key: {
            "input_completeness": value.get("input_completeness"),
            "missing_critical_factors": value.get("missing_critical_factors", []),
            "available_critical_factors": value.get("available_critical_factors", []),
            "score_cap_applied": value.get("score_cap_applied", False),
            "score_cap_value": float(np.nanmean(value.get("score_cap_grid", 1.0))) if np.asarray(value.get("score_cap_grid", 1.0)).size else 1.0,
        }
        for key, value in metadata.items()
    }
    return {"scores": scores, "factors": factors, "available_weights": available_weights, "metadata": metadata, "quality": quality}



def _hazard_output_metadata_01(output: dict) -> dict:
    completeness = np.asarray(output.get("input_completeness_grid", 1.0), dtype=float)
    cap_grid = np.asarray(output.get("score_cap_grid", 100.0), dtype=float) / 100.0
    cap_applied = np.asarray(output.get("score_cap_applied_grid", False), dtype=bool)
    return {
        "input_completeness_grid": completeness,
        "input_completeness": float(np.nanmean(completeness)) if completeness.size else 1.0,
        "missing_critical_factors": list(output.get("missing_critical_factors", [])),
        "available_critical_factors": list(output.get("available_critical_factors", [])),
        "score_cap_grid": cap_grid,
        "score_cap_applied_grid": cap_applied,
        "score_cap_applied": bool(output.get("score_cap_applied", False)),
    }


def _composite_metadata(items: list[dict]) -> dict:
    completeness_arrays = [np.asarray(item.get("input_completeness_grid", 1.0), dtype=float) for item in items]
    cap_arrays = [np.asarray(item.get("score_cap_grid", 1.0), dtype=float) for item in items]
    applied_arrays = [np.asarray(item.get("score_cap_applied_grid", False), dtype=bool) for item in items]
    completeness = np.nanmax(np.stack(completeness_arrays), axis=0) if completeness_arrays else np.array(1.0)
    cap_grid = np.nanmax(np.stack(cap_arrays), axis=0) if cap_arrays else np.array(1.0)
    applied = np.any(np.stack(applied_arrays), axis=0) if applied_arrays else np.array(False)
    missing: list[str] = []
    available: list[str] = []
    for item in items:
        for name in item.get("missing_critical_factors", []):
            if name not in missing:
                missing.append(name)
        for name in item.get("available_critical_factors", []):
            if name not in available:
                available.append(name)
    return {
        "input_completeness_grid": completeness,
        "input_completeness": float(np.nanmean(completeness)) if completeness.size else 1.0,
        "missing_critical_factors": missing,
        "available_critical_factors": available,
        "score_cap_grid": cap_grid,
        "score_cap_applied_grid": applied,
        "score_cap_applied": bool(np.any(applied)),
    }


def _factor_details_01(factor_scores: dict | None) -> dict:
    if not factor_scores:
        return {}
    out = {}
    for factor, detail in factor_scores.items():
        score = np.asarray(detail.get("score", 0.0), dtype=float) / 100.0
        contribution = np.asarray(detail.get("contribution", 0.0), dtype=float) / 100.0
        out[factor] = {
            "field": detail.get("field", factor),
            "label": detail.get("label", factor),
            "weight": float(detail.get("weight", 0.0)),
            "score": score,
            "contribution": contribution,
        }
    return out


def _quality_detail_01(output: dict) -> dict:
    quality = dict(output.get("quality") or {})
    if "input_completeness" not in quality and "input_completeness" in output:
        quality["input_completeness"] = float(output.get("input_completeness") or 0.0)
    if "missing_critical_factors" not in quality:
        quality["missing_critical_factors"] = list(output.get("missing_critical_factors") or [])
    if "available_critical_factors" not in quality:
        quality["available_critical_factors"] = list(output.get("available_critical_factors") or [])
    if "score_cap_applied" not in quality:
        quality["score_cap_applied"] = bool(output.get("score_cap_applied"))
    if "score_cap_value" not in quality:
        quality["score_cap_value"] = output.get("score_cap_value")
    grid = output.get("input_completeness_grid")
    if grid is not None:
        quality["input_completeness_grid"] = np.clip(np.asarray(grid, dtype=float), 0.0, 1.0)
    return quality


def _combine_quality_details(*items: dict | None) -> dict:
    valid = [item for item in items if item]
    if not valid:
        return {}
    completeness = min(float(item.get("input_completeness", 1.0)) for item in valid)
    missing = sorted({factor for item in valid for factor in item.get("missing_critical_factors", [])})
    available = sorted({factor for item in valid for factor in item.get("available_critical_factors", [])})
    caps = [float(item["score_cap_value"]) for item in valid if item.get("score_cap_value") is not None]
    return {
        "input_completeness": completeness,
        "missing_critical_factors": missing,
        "available_critical_factors": available,
        "score_cap_applied": any(bool(item.get("score_cap_applied")) for item in valid),
        "score_cap_value": min(caps) if caps else None,
    }


def _factor_dominance(
    factor_details: dict | None,
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    limit: int = 3,
) -> list[dict]:
    if not factor_details:
        return []
    out = []
    for factor, detail in factor_details.items():
        contribution = np.asarray(detail["contribution"], dtype=float)[ys, xs]
        score = np.asarray(detail.get("score", detail["contribution"]), dtype=float)[ys, xs]
        mean_contribution = float(np.nanmean(contribution)) if contribution.size else 0.0
        if mean_contribution <= 0:
            continue
        out.append(
            {
                "factor": factor,
                "label": detail.get("label", factor),
                "weight": float(detail.get("weight", 0.0)),
                "mean_score": round(float(np.nanmean(score)), 3),
                "mean_contribution": round(mean_contribution, 3),
            }
        )
    out.sort(key=lambda item: item["mean_contribution"], reverse=True)
    return out[:limit]



def _risk_metadata_for_component(metadata: dict | None, ys: np.ndarray, xs: np.ndarray) -> dict:
    if not metadata:
        return {
            "input_completeness": 1.0,
            "missing_critical_factors": [],
            "score_cap_applied": False,
            "score_cap": 1.0,
        }
    completeness_grid = np.asarray(metadata.get("input_completeness_grid", metadata.get("input_completeness", 1.0)), dtype=float)
    score_cap_grid = np.asarray(metadata.get("score_cap_grid", 1.0), dtype=float)
    cap_applied_grid = np.asarray(metadata.get("score_cap_applied_grid", False), dtype=bool)
    def _take_mean(arr, default):
        if arr.shape == ():
            return float(arr)
        return float(np.nanmean(arr[ys, xs])) if arr.size else float(default)
    def _take_any(arr):
        if arr.shape == ():
            return bool(arr)
        return bool(np.any(arr[ys, xs])) if arr.size else False
    return {
        "input_completeness": round(_take_mean(completeness_grid, metadata.get("input_completeness", 1.0)), 3),
        "missing_critical_factors": list(metadata.get("missing_critical_factors", [])),
        "score_cap_applied": _take_any(cap_applied_grid) or bool(metadata.get("score_cap_applied", False)),
        "score_cap": round(_take_mean(score_cap_grid, 1.0), 3),
    }


def _ranked_risk_features(
    score: np.ndarray,
    lat,
    lon,
    *,
    feature_type: str,
    title: str,
    cfg: dict,
    factor_details: dict | None,
    base_evidence: str,
    risk_metadata: dict | None = None,
) -> list[dict]:
    threshold = float(cfg.get("score_threshold", 0.6))
    high_threshold = float(cfg.get("high_score_threshold", max(0.72, threshold + 0.1)))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 8))
    components = mask_to_bbox_features(np.asarray(score) >= threshold, lat, lon, min_points=min_pts)
    components.sort(
        key=lambda item: (
            float(np.nanmax(score[item["indices"]])),
            float(np.nanmean(score[item["indices"]])),
            item["point_count"],
        ),
        reverse=True,
    )
    if max_objects > 0:
        components = components[:max_objects]

    features = []
    for rank, item in enumerate(components, start=1):
        ys, xs = item["indices"]
        values = np.asarray(score, dtype=float)[ys, xs]
        max_value = float(np.nanmax(values)) if values.size else 0.0
        mean_value = float(np.nanmean(values)) if values.size else 0.0
        core_points = int(np.count_nonzero(values >= high_threshold))
        risk_level = "high" if core_points > 0 else "moderate"
        dominant = _factor_dominance(factor_details, ys, xs)
        metadata_summary = _risk_metadata_for_component(risk_metadata, ys, xs)
        evidence = [
            base_evidence,
            f"综合评分最大值 {max_value:.2f}，平均值 {mean_value:.2f}",
        ]
        if core_points:
            evidence.append(f"核心区格点 {core_points} 个达到 {high_threshold:.2f} 高潜势阈值")
        else:
            evidence.append(f"外围区达到 {threshold:.2f} 中等潜势阈值，未形成高潜势核心")
        if dominant:
            evidence.append("主导因子：" + "、".join(f"{item['label']} {item['mean_contribution']:.2f}" for item in dominant))
        if metadata_summary["missing_critical_factors"]:
            evidence.append("缺失关键因子：" + "、".join(metadata_summary["missing_critical_factors"]))
        if metadata_summary["score_cap_applied"]:
            evidence.append("因关键因子不完整，已对风险评分进行上限约束")

        props = {
            "id": f"{feature_type}_{rank:03d}",
            "feature_type": feature_type,
            "title": title,
            "rank": rank,
            "risk_level": risk_level,
            "zone": "core" if core_points else "outer",
            "confidence": round(min(0.9, 0.55 + max_value * 0.35), 2),
            "point_count": item["point_count"],
            "core_point_count": core_points,
            "centroid": item["centroid"],
            "bbox": item["bbox"],
            "max_value": max_value,
            "mean_value": mean_value,
            "score_threshold": threshold,
            "high_score_threshold": high_threshold,
            "dominant_factors": dominant,
            "input_completeness": metadata_summary["input_completeness"],
            "missing_critical_factors": metadata_summary["missing_critical_factors"],
            "score_cap_applied": metadata_summary["score_cap_applied"],
            "score_cap": metadata_summary["score_cap"],
            "evidence": evidence,
        }
        features.append(polygon_feature(item["geometry"], props))
    return features


def detect_hazard_risk_features(
    hazard_type: str,
    score: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    factor_details: dict | None = None,
    risk_metadata: dict | None = None,
) -> list[dict]:
    from weather_diag.diagnosis.risk_taxonomy import hazard_metadata

    meta = hazard_metadata(hazard_type)
    cfg = thresholds.get(meta["feature_type"], {})
    features = _ranked_risk_features(
        score,
        lat,
        lon,
        feature_type=meta["feature_type"],
        title=meta["label"] + "风险区",
        cfg=cfg,
        factor_details=factor_details,
        base_evidence=meta["label"] + "综合评分较高",
        risk_metadata=risk_metadata,
    )
    for feature in features:
        props = feature.setdefault("properties", {})
        props["hazard_type"] = hazard_type
        props["risk_domain"] = list(meta["risk_domain"])
        props["mechanism_tags"] = list(meta["mechanism_tags"])
        props["source_grid"] = meta["score_grid"]
    return features
