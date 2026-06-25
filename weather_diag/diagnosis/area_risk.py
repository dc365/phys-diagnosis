from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from weather_diag.areas.registry import TownArea
from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, score_level
from weather_diag.diagnosis.nafp_layers import nafp_multi_hazard_score_details
from weather_diag.diagnosis.risk_taxonomy import HAZARD_TYPES, risk_metadata, risk_metadata_catalog


def supported_area_risk_types() -> list[str]:
    return list(HAZARD_TYPES)


def area_risk_metadata(risk_types: list[str] | None = None) -> dict[str, dict[str, Any]]:
    return risk_metadata_catalog(risk_types)


def evaluate_area_risks(
    *,
    root: str | Path,
    run_time: str | datetime,
    forecast_hours: list[int],
    towns: list[TownArea],
    risk_types: list[str] | None = None,
    include_evidence: bool = True,
    include_samples: bool = False,
    threshold_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    selected_risks = risk_types or supported_area_risk_types()
    matrix = threshold_matrix or load_threshold_matrix()
    items: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for hour in forecast_hours:
        try:
            details, lat, lon, source_paths = nafp_multi_hazard_score_details(Path(root), rt.isoformat(), int(hour))
        except Exception as exc:
            failed.append(
                {
                    "forecast_hour": int(hour),
                    "error": str(exc),
                }
            )
            continue

        valid_time = rt + timedelta(hours=int(hour))
        for town in towns:
            risks = [
                _town_hazard_risk(
                    town=town,
                    hazard_type=hazard_type,
                    details=details,
                    lat=lat,
                    lon=lon,
                    source_paths=source_paths,
                    threshold_matrix=matrix,
                    include_evidence=include_evidence,
                    include_samples=include_samples,
                )
                for hazard_type in selected_risks
            ]
            items.append(
                {
                    "area": town.to_dict(include_points=False),
                    "forecast_hour": int(hour),
                    "valid_time": valid_time.isoformat(),
                    "risks": risks,
                }
            )

    return {
        "items": items,
        "failed": failed,
        "summary": _summary(items, towns, selected_risks),
    }


def _town_hazard_risk(
    *,
    town: TownArea,
    hazard_type: str,
    details: dict[str, Any],
    lat: np.ndarray,
    lon: np.ndarray,
    source_paths: list[str],
    threshold_matrix: dict[str, Any],
    include_evidence: bool,
    include_samples: bool,
) -> dict[str, Any]:
    metadata = risk_metadata(hazard_type)
    source_grid = metadata["source_grid"]
    score_grid = _prepare_2d((details.get("scores") or {}).get(source_grid), lat, lon)
    factors = (details.get("factors") or {}).get(source_grid, {})
    quality = (details.get("quality") or {}).get(source_grid, {})
    samples = _sample_town_points(town, score_grid, lat, lon)
    valid_scores = np.asarray([item["score"] for item in samples if item.get("score") is not None], dtype=float)
    valid_scores = valid_scores[np.isfinite(valid_scores)]

    if valid_scores.size:
        max_score = float(np.nanmax(valid_scores))
        mean_score = float(np.nanmean(valid_scores))
        p90_score = float(np.nanpercentile(valid_scores, 90))
        level = score_level(max_score, threshold_matrix)
    else:
        max_score = 0.0
        mean_score = 0.0
        p90_score = 0.0
        level = score_level(0.0, threshold_matrix)

    risk = {
        "hazard_type": hazard_type,
        "label": metadata["label"],
        "metadata": metadata,
        "risk_domain": metadata["risk_domain"],
        "source_grid": source_grid,
        "feature_type": metadata["feature_type"],
        "score": round(max_score, 3),
        "max_score": round(max_score, 3),
        "mean_score": round(mean_score, 3),
        "p90_score": round(p90_score, 3),
        "risk_level": level,
        "level": level,
        "score_source": "source_grid",
        "score_statistic": "station_points_max",
        "sample_count": int(valid_scores.size),
        "station_count": town.station_count,
        "input_completeness": quality.get("input_completeness"),
        "missing_critical_factors": list(quality.get("missing_critical_factors") or []),
        "score_cap_applied": bool(quality.get("score_cap_applied", False)),
        "score_cap_value": quality.get("score_cap_value"),
    }
    if include_evidence:
        risk["evidence_chain"] = _evidence_chain(
            hazard_type=hazard_type,
            source_grid=source_grid,
            samples=samples,
            factors=factors,
            source_paths=source_paths,
        )
    if include_samples:
        risk["samples"] = samples
    return risk


def _prepare_2d(values: Any, lat: np.ndarray, lon: np.ndarray) -> np.ndarray | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=float).squeeze()
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    if arr.ndim != 2:
        return None
    if arr.shape == (lat_values.size, lon_values.size):
        return arr
    if arr.shape == (lon_values.size, lat_values.size):
        return arr.T
    return None


def _normalize_query_lon(lon_values: np.ndarray, lon: float) -> float:
    lon_min = float(np.nanmin(lon_values))
    lon_max = float(np.nanmax(lon_values))
    query = float(lon)
    if lon_min >= 0.0 and lon_max > 180.0 and query < 0.0:
        return query % 360.0
    if lon_min < 0.0 and lon_max <= 180.0 and query > 180.0:
        return ((query + 180.0) % 360.0) - 180.0
    return query


def _nearest_grid_point(lat_values: np.ndarray, lon_values: np.ndarray, lat: float, lon: float) -> dict[str, Any]:
    lats = np.asarray(lat_values, dtype=float)
    lons = np.asarray(lon_values, dtype=float)
    query_lon = _normalize_query_lon(lons, lon)
    lat_idx = int(np.nanargmin(np.abs(lats - float(lat))))
    lon_idx = int(np.nanargmin(np.abs(lons - query_lon)))
    nearest_lat = float(lats[lat_idx])
    nearest_lon = float(lons[lon_idx])
    return {
        "lat": round(nearest_lat, 6),
        "lon": round(nearest_lon, 6),
        "lat_index": lat_idx,
        "lon_index": lon_idx,
        "distance_degrees": round(float(np.hypot(nearest_lat - float(lat), nearest_lon - query_lon)), 6),
        "outside_domain": (
            float(lat) < float(np.nanmin(lats))
            or float(lat) > float(np.nanmax(lats))
            or query_lon < float(np.nanmin(lons))
            or query_lon > float(np.nanmax(lons))
        ),
        "normalized_query_lon": round(query_lon, 6),
    }


def _sample_town_points(
    town: TownArea,
    score_grid: np.ndarray | None,
    lat: np.ndarray,
    lon: np.ndarray,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for station in town.points:
        sample_point = _nearest_grid_point(lat, lon, station.lat, station.lon)
        score = None
        if score_grid is not None:
            raw = float(score_grid[sample_point["lat_index"], sample_point["lon_index"]])
            if np.isfinite(raw):
                score = round(raw, 3)
        samples.append(
            {
                "station_code": station.station_code,
                "station_name": station.station_name,
                "display_name": station.display_name,
                "lon": station.lon,
                "lat": station.lat,
                "score": score,
                "sample_point": sample_point,
            }
        )
    return samples


def _dominant_factors(
    factor_details: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not factor_details:
        return []
    indices = [
        (sample["sample_point"]["lat_index"], sample["sample_point"]["lon_index"])
        for sample in samples
        if sample.get("score") is not None
    ]
    if not indices:
        return []
    out: list[dict[str, Any]] = []
    for factor, detail in factor_details.items():
        contribution_grid = _prepare_factor_grid(detail.get("contribution"))
        if contribution_grid is None:
            continue
        contribution_values = _values_at_indices(contribution_grid, indices)
        if contribution_values.size == 0 or not np.isfinite(contribution_values).any():
            continue
        mean_contribution = float(np.nanmean(contribution_values))
        if mean_contribution <= 0:
            continue
        score_grid = _prepare_factor_grid(detail.get("score"))
        score_values = _values_at_indices(score_grid, indices) if score_grid is not None else contribution_values
        out.append(
            {
                "factor": factor,
                "field": detail.get("field", factor),
                "label": detail.get("label", factor),
                "weight": float(detail.get("weight", 0.0)),
                "mean_score": round(float(np.nanmean(score_values)), 3),
                "mean_contribution": round(mean_contribution, 3),
                "max_contribution": round(float(np.nanmax(contribution_values)), 3),
            }
        )
    out.sort(key=lambda item: (item["mean_contribution"], item["max_contribution"]), reverse=True)
    return out[:limit]


def _prepare_factor_grid(values: Any) -> np.ndarray | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=float).squeeze()
    return arr if arr.ndim == 2 else None


def _values_at_indices(values: np.ndarray, indices: list[tuple[int, int]]) -> np.ndarray:
    out = []
    for y, x in indices:
        if y < values.shape[0] and x < values.shape[1]:
            out.append(values[y, x])
    return np.asarray(out, dtype=float)


def _max_sample(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [sample for sample in samples if sample.get("score") is not None]
    if not valid:
        return None
    return max(valid, key=lambda item: float(item["score"]))


def _evidence_chain(
    *,
    hazard_type: str,
    source_grid: str,
    samples: list[dict[str, Any]],
    factors: dict[str, Any],
    source_paths: list[str],
) -> dict[str, Any]:
    return {
        "hazard_type": hazard_type,
        "source_grid": source_grid,
        "sampling_method": "station_points",
        "score_statistic": "station_points_max",
        "dominant_factors": _dominant_factors(factors, samples),
        "max_sample": _max_sample(samples),
        "sample_count": sum(1 for sample in samples if sample.get("score") is not None),
        "source_paths": list(source_paths),
    }


def _summary(items: list[dict[str, Any]], towns: list[TownArea], risk_types: list[str]) -> dict[str, Any]:
    risks = [risk for item in items for risk in item.get("risks") or []]
    max_score = max((float(risk.get("score") or 0.0) for risk in risks), default=0.0)
    return {
        "town_count": len(towns),
        "risk_type_count": len(risk_types),
        "item_count": len(items),
        "risk_count": len(risks),
        "max_score": round(max_score, 3),
    }
