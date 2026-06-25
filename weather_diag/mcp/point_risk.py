from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from weather_diag.config import load_thresholds
from weather_diag.diagnosis.algorithm_rules import load_threshold_matrix, score_level
from weather_diag.diagnosis.nafp_layers import _risk_input_bundle
from weather_diag.diagnosis.point import nearest_grid_point
from weather_diag.diagnosis.risk_taxonomy import risk_metadata_catalog
from weather_diag.features.risk import multi_hazard_score_details
from weather_diag.mcp.area_risk_dsl import (
    DEFAULT_WINDOW_HOURS,
    PHYSICAL_EVIDENCE_SPECS,
    normalize_models,
    parse_optional_time,
    resolve_forecast_context,
    resolve_model_source,
)


POINT_RISK_RESPONSE_GUIDE = """点风险 MCP 返回非 DSL JSON。

核心结构：
- points 为请求点位标准化结果，items 为逐模式、逐时效、逐点的风险诊断结果。
- 每个 item 的 risks 包含六类风险评分，score 为 0-1，risk_level 由阈值矩阵划分。
- 每个风险的 evidence_chain 来自同一风险 source_grid 的主导因子格点采样，不使用旧证据链总分替代风险分。
- physical_evidence 为该点最近格点的原始物理量证据，单位、方向和阈值在每个字段内给出，不做 0-1 归一化。
- 该工具适合回答“某点是否会出现强对流、短时强降水、冰雹、雷暴大风”等点位问答。
"""


def parse_point_inputs(points: str | dict[str, Any] | list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    if isinstance(points, str):
        raw = points.strip()
        if not raw:
            raise ValueError("points must not be empty")
        if raw[0] in "[{":
            parsed = json.loads(raw)
            return parse_point_inputs(parsed)
        parsed_points = []
        for idx, chunk in enumerate(raw.split(";"), start=1):
            text = chunk.strip()
            if not text:
                continue
            parts = [item.strip() for item in text.split(",")]
            if len(parts) < 2:
                raise ValueError(f"invalid point text: {text}")
            parsed_points.append(_normalize_point({"lat": parts[0], "lon": parts[1], "name": parts[2] if len(parts) > 2 else None}, idx))
        if not parsed_points:
            raise ValueError("points must not be empty")
        return parsed_points

    if isinstance(points, dict):
        return [_normalize_point(points, 1)]

    out = []
    for idx, item in enumerate(points, start=1):
        out.append(_normalize_point(item, idx))
    if not out:
        raise ValueError("points must not be empty")
    return out


def get_point_risk_payload(
    *,
    points: str | dict[str, Any] | list[Any] | tuple[Any, ...],
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    models: str | list[str] | None = None,
    data_code: str | None = None,
    run_time: str | datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_points = parse_point_inputs(points)
    start = parse_optional_time(start_time, default=(now or datetime.now()).replace(tzinfo=None))
    end = parse_optional_time(end_time, default=start + timedelta(hours=DEFAULT_WINDOW_HOURS))
    if end < start:
        raise ValueError("end_time must be >= start_time")

    threshold_matrix = load_threshold_matrix()
    risk_metadata = risk_metadata_catalog()
    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    model_metadata: list[dict[str, Any]] = []

    for model in normalize_models(models):
        source = resolve_model_source(model, data_code=data_code)
        context = resolve_forecast_context(
            data_code=source["data_code"],
            root=source["root"],
            run_time=run_time,
            start_time=start,
            end_time=end,
        )
        model_metadata.append(
            {
                "model": source["model"],
                "data_code": source["data_code"],
                "run_time": context["run_time"].isoformat(),
                "forecast_hours": [int(hour) for hour in context["forecast_hours"]],
            }
        )
        for forecast_hour in context["forecast_hours"]:
            try:
                fields, lat, lon, _source_paths = _risk_input_bundle(
                    Path(source["root"]),
                    context["run_time"].isoformat(),
                    int(forecast_hour),
                )
                details = multi_hazard_score_details(fields, load_thresholds())
            except Exception as exc:
                failures.append(
                    {
                        "model": source["model"],
                        "data_code": source["data_code"],
                        "run_time": context["run_time"].isoformat(),
                        "forecast_hour": int(forecast_hour),
                        "error": str(exc),
                    }
                )
                continue

            valid_time = context["run_time"] + timedelta(hours=int(forecast_hour))
            for point in normalized_points:
                sample_point = nearest_grid_point(lat, lon, point["lat"], point["lon"])
                items.append(
                    {
                        "model": source["model"],
                        "data_code": source["data_code"],
                        "run_time": context["run_time"].isoformat(),
                        "forecast_hour": int(forecast_hour),
                        "valid_time": valid_time.isoformat(),
                        "point": dict(point),
                        "sample_method": "nearest_grid_point",
                        "nearest_grid_point": sample_point,
                        "risks": _point_risks(details, risk_metadata, threshold_matrix, lat, lon, sample_point),
                        "physical_evidence": _point_physical_evidence(fields, lat, lon, sample_point),
                    }
                )

    return {
        "request": {
            "points": normalized_points,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "models": normalize_models(models),
        },
        "points": normalized_points,
        "model_metadata": model_metadata,
        "risk_metadata": risk_metadata,
        "items": items,
        "failures": failures,
        "response_guide": POINT_RISK_RESPONSE_GUIDE,
    }


def _normalize_point(item: Any, idx: int) -> dict[str, Any]:
    if isinstance(item, dict):
        lat = _float_required(item.get("lat", item.get("latitude")), "lat")
        lon = _float_required(item.get("lon", item.get("lng", item.get("longitude"))), "lon")
        point_id = str(item.get("id") or f"P{idx}")
        name = str(item.get("name") or point_id)
        return {"id": point_id, "name": name, "lat": round(lat, 6), "lon": round(lon, 6)}
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        lat = _float_required(item[0], "lat")
        lon = _float_required(item[1], "lon")
        point_id = str(item[2]) if len(item) >= 3 and item[2] else f"P{idx}"
        name = str(item[3]) if len(item) >= 4 and item[3] else point_id
        return {"id": point_id, "name": name, "lat": round(lat, 6), "lon": round(lon, 6)}
    raise ValueError(f"invalid point item at index {idx}: {item!r}")


def _point_risks(
    details: dict[str, Any],
    risk_metadata: dict[str, dict[str, Any]],
    threshold_matrix: dict[str, Any],
    lat: np.ndarray,
    lon: np.ndarray,
    sample_point: dict[str, Any],
) -> list[dict[str, Any]]:
    risks = []
    scores = details.get("scores") or {}
    factors = details.get("factors") or {}
    for hazard_type, meta in risk_metadata.items():
        source_grid = str(meta["source_grid"])
        score = _sample_grid_number(scores.get(source_grid), lat, lon, sample_point)
        if score is None:
            score = 0.0
        rounded_score = _round_score(score)
        level = score_level(float(score), threshold_matrix)
        risks.append(
            {
                "hazard_type": hazard_type,
                "label": meta["label"],
                "risk_domain": list(meta["risk_domain"]),
                "mechanism_tags": list(meta["mechanism_tags"]),
                "source_grid": source_grid,
                "score": rounded_score,
                "risk_level": level,
                "level": level,
                "score_source": "source_grid",
                "score_range": [0, 1],
                "score_unit": "risk_score",
                "evidence_chain": {
                    "hazard_type": hazard_type,
                    "source_grid": source_grid,
                    "sampling_method": "nearest_grid_point",
                    "sample_point": dict(sample_point),
                    "dominant_factors": _dominant_factor_samples(factors.get(source_grid) or {}, lat, lon, sample_point),
                },
            }
        )
    return risks


def _dominant_factor_samples(
    factor_details: dict[str, Any],
    lat: np.ndarray,
    lon: np.ndarray,
    sample_point: dict[str, Any],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    out = []
    for factor, detail in factor_details.items():
        score = _sample_grid_number(detail.get("score"), lat, lon, sample_point)
        contribution = _sample_grid_number(detail.get("contribution"), lat, lon, sample_point)
        if contribution is None or contribution <= 0:
            continue
        out.append(
            {
                "factor": str(factor),
                "field": str(detail.get("field") or factor),
                "label": str(detail.get("label") or factor),
                "weight": _round_score(float(detail.get("weight") or 0.0)),
                "score": _round_score(score if score is not None else contribution),
                "contribution": _round_score(contribution),
            }
        )
    out.sort(key=lambda item: item["contribution"], reverse=True)
    return out[:limit]


def _point_physical_evidence(
    fields: dict[str, np.ndarray],
    lat: np.ndarray,
    lon: np.ndarray,
    sample_point: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field, spec in PHYSICAL_EVIDENCE_SPECS.items():
        values = fields.get(str(spec.get("source_field") or ""))
        if values is None:
            continue
        arr = _transform_physical_grid(values, str(spec.get("transform") or ""))
        value = _sample_grid_number(arr, lat, lon, sample_point)
        if value is None:
            continue
        out[field] = {
            "value": _round_physical_value(value),
            "label": spec["label"],
            "api": spec["api"],
            "unit": spec["unit"],
            "direction": spec["direction"],
            "watch": spec["watch"],
            "high": spec["high"],
            "sample_method": "nearest_grid_point",
        }
    return out


def _sample_grid_number(
    values: Any,
    lat: np.ndarray,
    lon: np.ndarray,
    sample_point: dict[str, Any],
) -> float | None:
    arr = _prepare_grid(values, lat, lon)
    if arr is None:
        return None
    raw = float(arr[int(sample_point["lat_index"]), int(sample_point["lon_index"])])
    if not math.isfinite(raw):
        return None
    return raw


def _prepare_grid(values: Any, lat: np.ndarray, lon: np.ndarray) -> np.ndarray | None:
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


def _transform_physical_grid(values: np.ndarray, transform: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if transform == "_to_gkg":
        valid = np.abs(arr[np.isfinite(arr)])
        if valid.size and float(np.nanmax(valid)) < 1.0:
            return arr * 1000.0
    return arr


def _float_required(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _round_score(value: float) -> float:
    return round(float(value), 3)


def _round_physical_value(value: float) -> float:
    return round(float(value), 2)
