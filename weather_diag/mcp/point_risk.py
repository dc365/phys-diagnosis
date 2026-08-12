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
    _physical_summary_extreme_rank,
    _physical_summary_level,
    _physical_summary_met,
    normalize_models,
    normalize_time_match_policy,
    parse_optional_time,
    parse_time_windows,
    resolve_forecast_context,
    resolve_forecast_contexts,
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


WATCH_RISK_LEVELS = {"moderate", "high"}
HIGH_RISK_LEVEL = "high"


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
        return _ensure_unique_point_ids(parsed_points)

    if isinstance(points, dict):
        return [_normalize_point(points, 1)]

    out = []
    for idx, item in enumerate(points, start=1):
        out.append(_normalize_point(item, idx))
    if not out:
        raise ValueError("points must not be empty")
    return _ensure_unique_point_ids(out)


def _ensure_unique_point_ids(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for point in points:
        point_id = str(point.get("id") or "")
        if point_id in seen:
            raise ValueError(f"duplicate point id: {point_id}")
        seen.add(point_id)
    return points


def get_point_risk_payload(
    *,
    points: str | dict[str, Any] | list[Any] | tuple[Any, ...],
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    models: str | list[str] | None = None,
    data_code: str | None = None,
    run_time: str | datetime | None = None,
    now: datetime | None = None,
    windows: str | dict[str, Any] | list[Any] | tuple[Any, ...] | None = None,
    time_match_policy: str | None = None,
    include_window_summary: bool = True,
) -> dict[str, Any]:
    if windows is not None:
        return get_point_risk_multi_window_payload(
            points=points,
            models=models,
            data_code=data_code,
            run_time=run_time,
            windows=windows,
            time_match_policy=time_match_policy,
            include_window_summary=include_window_summary,
        )

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


def get_point_risk_multi_window_payload(
    *,
    points: str | dict[str, Any] | list[Any] | tuple[Any, ...],
    models: str | list[str] | None,
    data_code: str | None,
    run_time: str | datetime | None,
    windows: str | dict[str, Any] | list[Any] | tuple[Any, ...],
    time_match_policy: str | None,
    include_window_summary: bool,
) -> dict[str, Any]:
    normalized_points = parse_point_inputs(points)
    parsed_windows = parse_time_windows(windows)
    policy = normalize_time_match_policy(time_match_policy, windows_provided=True)
    if policy == "fixed_run" and run_time is None:
        raise ValueError("run_time is required when time_match_policy=fixed_run")
    model_names = normalize_models(models)
    threshold_matrix = load_threshold_matrix()
    score_thresholds = load_thresholds()
    risk_metadata = risk_metadata_catalog()
    point_order = {str(point["id"]): idx for idx, point in enumerate(normalized_points)}
    risk_input_cache: dict[
        tuple[str, str, str, int],
        tuple[dict[str, np.ndarray], np.ndarray, np.ndarray],
    ] = {}
    score_details_cache: dict[
        tuple[str, str, str, int],
        tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, dict[str, Any]],
    ] = {}
    window_outputs: list[dict[str, Any]] = []

    for window in parsed_windows:
        failures: list[dict[str, Any]] = []
        model_metadata: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []

        for model in model_names:
            try:
                source = resolve_model_source(model, data_code=data_code)
                contexts = resolve_forecast_contexts(
                    data_code=source["data_code"],
                    root=source["root"],
                    run_time=run_time,
                    start_time=window["start_time"],
                    end_time=window["end_time"],
                    policy=policy,
                )
            except Exception as exc:
                failures.append({"model": str(model), "data_code": data_code, "error": str(exc)})
                continue

            for context in contexts:
                context_run_time = parse_optional_time(context["run_time"])
                forecast_hours = [int(hour) for hour in context["forecast_hours"]]
                model_metadata.append(
                    {
                        "model": source["model"],
                        "data_code": source["data_code"],
                        "run_time": context_run_time.isoformat(),
                        "forecast_hours": forecast_hours,
                        "valid_times": list(context.get("valid_times") or _valid_times(context_run_time, forecast_hours)),
                    }
                )
                for forecast_hour in forecast_hours:
                    try:
                        fields, lat, lon, details = _cached_point_risk_product(
                            root=Path(source["root"]),
                            data_code=source["data_code"],
                            run_time=context_run_time,
                            forecast_hour=int(forecast_hour),
                            risk_input_cache=risk_input_cache,
                            score_details_cache=score_details_cache,
                            score_thresholds=score_thresholds,
                        )
                    except Exception as exc:
                        failures.append(
                            {
                                "model": source["model"],
                                "data_code": source["data_code"],
                                "run_time": context_run_time.isoformat(),
                                "forecast_hour": int(forecast_hour),
                                "error": str(exc),
                            }
                        )
                        continue

                    valid_time = context_run_time + timedelta(hours=int(forecast_hour))
                    for point in normalized_points:
                        sample_point = nearest_grid_point(lat, lon, point["lat"], point["lon"])
                        items.append(
                            {
                                "model": source["model"],
                                "data_code": source["data_code"],
                                "run_time": context_run_time.isoformat(),
                                "forecast_hour": int(forecast_hour),
                                "valid_time": valid_time.isoformat(),
                                "point": dict(point),
                                "sample_method": "nearest_grid_point",
                                "nearest_grid_point": sample_point,
                                "risks": _point_risks(details, risk_metadata, threshold_matrix, lat, lon, sample_point),
                                "physical_evidence": _point_physical_evidence(fields, lat, lon, sample_point),
                            }
                        )

        window_output = {
            "label": window["label"],
            "start_time": window["start_time"].isoformat(),
            "end_time": window["end_time"].isoformat(),
            "time_match_policy": policy,
            "model_metadata": model_metadata,
            "items": items,
            "risk_summary": [],
            "point_summary": [],
            "physical_summary": [],
            "point_physical_summary": [],
            "failures": failures,
        }
        if include_window_summary:
            window_output["risk_summary"] = build_point_window_risk_summary(items, point_order)
            window_output["point_summary"] = build_point_window_point_summary(items, point_order)
            window_output["physical_summary"] = build_point_window_physical_summary(items, point_order)
            window_output["point_physical_summary"] = build_point_window_point_physical_summary(items, point_order)
        window_outputs.append(window_output)

    return {
        "mode": "multi_window_point_risk",
        "request": {
            "points": normalized_points,
            "models": model_names,
            "data_code": data_code,
            "time_match_policy": policy,
            "include_window_summary": bool(include_window_summary),
        },
        "points": normalized_points,
        "risk_metadata": risk_metadata,
        "windows": window_outputs,
        "response_guide": POINT_RISK_RESPONSE_GUIDE,
    }


def _valid_times(run_time: datetime, forecast_hours: list[int]) -> list[str]:
    return [(run_time + timedelta(hours=int(hour))).isoformat() for hour in forecast_hours]


def _cached_point_risk_product(
    *,
    root: Path,
    data_code: str,
    run_time: datetime,
    forecast_hour: int,
    risk_input_cache: dict[
        tuple[str, str, str, int],
        tuple[dict[str, np.ndarray], np.ndarray, np.ndarray],
    ],
    score_details_cache: dict[
        tuple[str, str, str, int],
        tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, dict[str, Any]],
    ],
    score_thresholds: dict[str, Any],
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, dict[str, Any]]:
    key = (str(root), str(data_code), run_time.isoformat(), int(forecast_hour))
    if key in score_details_cache:
        return score_details_cache[key]

    if key in risk_input_cache:
        fields, lat, lon = risk_input_cache[key]
    else:
        fields, lat, lon, _source_paths = _risk_input_bundle(root, run_time.isoformat(), int(forecast_hour))
        risk_input_cache[key] = (fields, lat, lon)

    details = multi_hazard_score_details(fields, score_thresholds)
    score_details_cache[key] = (fields, lat, lon, details)
    return score_details_cache[key]


def build_point_window_risk_summary(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows = _point_risk_summary_rows(items, point_order)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["data_code"], row["hazard_type"]), []).append(row)

    summaries: list[dict[str, Any]] = []
    for (model, data_code, hazard_type), group_rows in sorted(groups.items()):
        winner = min(group_rows, key=_summary_winner_key)
        high_by_valid: dict[str, set[str]] = {}
        watch_by_valid: dict[str, set[str]] = {}
        watch_points: set[str] = set()
        active_valid_times: set[str] = set()
        for row in group_rows:
            valid_key = row["valid_time"]
            if not valid_key:
                continue
            if row["risk_level"] == HIGH_RISK_LEVEL:
                high_by_valid.setdefault(valid_key, set()).add(row["point_id"])
            if row["risk_level"] in WATCH_RISK_LEVELS:
                watch_by_valid.setdefault(valid_key, set()).add(row["point_id"])
                watch_points.add(row["point_id"])
                active_valid_times.add(valid_key)

        summaries.append(
            {
                "model": model,
                "data_code": data_code,
                "hazard_type": hazard_type,
                "max": _round_score(winner["score"]),
                "max_level": winner["risk_level"],
                "max_valid_time": winner["valid_time"],
                "max_point_id": winner["point_id"],
                "max_point_name": winner["point_name"],
                "max_run_time": winner["run_time"],
                "max_forecast_hour": winner["forecast_hour"],
                "high_point_peak": max((len(values) for values in high_by_valid.values()), default=0),
                "watch_point_peak": max((len(values) for values in watch_by_valid.values()), default=0),
                "watch_point_any": len(watch_points),
                "active_valid_time_count": len(active_valid_times),
                "item_count": len(group_rows),
            }
        )
    return summaries


def build_point_window_point_summary(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows = _point_risk_summary_rows(items, point_order)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["data_code"], row["point_id"], row["hazard_type"]), []).append(row)

    def group_sort_key(item: tuple[tuple[str, str, str, str], list[dict[str, Any]]]) -> tuple[Any, ...]:
        key, group_rows = item
        return key[0], key[1], min(row["point_order"] for row in group_rows), key[3]

    summaries: list[dict[str, Any]] = []
    for (model, data_code, point_id, hazard_type), group_rows in sorted(groups.items(), key=group_sort_key):
        winner = min(group_rows, key=_summary_winner_key)
        watch_valid_times = {
            row["valid_time"]
            for row in group_rows
            if row["valid_time"] and row["risk_level"] in WATCH_RISK_LEVELS
        }
        high_valid_times = {
            row["valid_time"]
            for row in group_rows
            if row["valid_time"] and row["risk_level"] == HIGH_RISK_LEVEL
        }
        summaries.append(
            {
                "model": model,
                "data_code": data_code,
                "point_id": point_id,
                "point_name": winner["point_name"],
                "hazard_type": hazard_type,
                "max": _round_score(winner["score"]),
                "max_level": winner["risk_level"],
                "max_valid_time": winner["valid_time"],
                "max_run_time": winner["run_time"],
                "max_forecast_hour": winner["forecast_hour"],
                "watch_valid_time_count": len(watch_valid_times),
                "high_valid_time_count": len(high_valid_times),
                "item_count": len(group_rows),
            }
        )
    return summaries


def build_point_window_physical_summary(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows = _point_physical_summary_rows(items, point_order)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["data_code"], row["field"]), []).append(row)

    summaries: list[dict[str, Any]] = []
    for (model, data_code, field), group_rows in sorted(groups.items()):
        winner = min(group_rows, key=_physical_summary_winner_key)
        high_by_valid: dict[str, set[str]] = {}
        watch_by_valid: dict[str, set[str]] = {}
        watch_points: set[str] = set()
        active_valid_times: set[str] = set()
        for row in group_rows:
            valid_key = row["valid_time"]
            if not valid_key:
                continue
            if _physical_summary_met(row["value"], row, "high"):
                high_by_valid.setdefault(valid_key, set()).add(row["point_id"])
            if _physical_summary_met(row["value"], row, "watch"):
                watch_by_valid.setdefault(valid_key, set()).add(row["point_id"])
                watch_points.add(row["point_id"])
                active_valid_times.add(valid_key)

        summaries.append(
            {
                "model": model,
                "data_code": data_code,
                "field": field,
                "api": winner["api"],
                "label": winner["label"],
                "unit": winner["unit"],
                "direction": winner["direction"],
                "watch": winner["watch"],
                "high": winner["high"],
                "extreme": _round_physical_value(winner["value"]),
                "extreme_level": winner["level"],
                "extreme_valid_time": winner["valid_time"],
                "extreme_point_id": winner["point_id"],
                "extreme_point_name": winner["point_name"],
                "extreme_run_time": winner["run_time"],
                "extreme_forecast_hour": winner["forecast_hour"],
                "high_point_peak": max((len(values) for values in high_by_valid.values()), default=0),
                "watch_point_peak": max((len(values) for values in watch_by_valid.values()), default=0),
                "watch_point_any": len(watch_points),
                "active_valid_time_count": len(active_valid_times),
                "item_count": len(group_rows),
            }
        )
    return summaries


def build_point_window_point_physical_summary(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows = _point_physical_summary_rows(items, point_order)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["data_code"], row["point_id"], row["field"]), []).append(row)

    def group_sort_key(item: tuple[tuple[str, str, str, str], list[dict[str, Any]]]) -> tuple[Any, ...]:
        key, group_rows = item
        return key[0], key[1], min(row["point_order"] for row in group_rows), key[3]

    summaries: list[dict[str, Any]] = []
    for (model, data_code, point_id, field), group_rows in sorted(groups.items(), key=group_sort_key):
        winner = min(group_rows, key=_physical_summary_winner_key)
        watch_valid_times = {
            row["valid_time"]
            for row in group_rows
            if row["valid_time"] and _physical_summary_met(row["value"], row, "watch")
        }
        high_valid_times = {
            row["valid_time"]
            for row in group_rows
            if row["valid_time"] and _physical_summary_met(row["value"], row, "high")
        }
        summaries.append(
            {
                "model": model,
                "data_code": data_code,
                "point_id": point_id,
                "point_name": winner["point_name"],
                "field": field,
                "api": winner["api"],
                "label": winner["label"],
                "unit": winner["unit"],
                "direction": winner["direction"],
                "watch": winner["watch"],
                "high": winner["high"],
                "extreme": _round_physical_value(winner["value"]),
                "extreme_level": winner["level"],
                "extreme_valid_time": winner["valid_time"],
                "extreme_run_time": winner["run_time"],
                "extreme_forecast_hour": winner["forecast_hour"],
                "watch_valid_time_count": len(watch_valid_times),
                "high_valid_time_count": len(high_valid_times),
                "item_count": len(group_rows),
            }
        )
    return summaries


def _point_risk_summary_rows(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        point = item.get("point") or {}
        point_id = str(point.get("id") or "")
        point_name = str(point.get("name") or point_id)
        valid_time = str(item.get("valid_time") or "")
        run_time = str(item.get("run_time") or "")
        for risk in item.get("risks") or []:
            score = _as_summary_float(risk.get("score"))
            hazard_type = str(risk.get("hazard_type") or "")
            if score is None or not hazard_type:
                continue
            rows.append(
                {
                    "model": str(item.get("model") or ""),
                    "data_code": str(item.get("data_code") or ""),
                    "run_time": run_time,
                    "run_datetime": _summary_datetime(run_time),
                    "forecast_hour": int(item.get("forecast_hour") or 0),
                    "valid_time": valid_time,
                    "valid_datetime": _summary_datetime(valid_time),
                    "point_id": point_id,
                    "point_name": point_name,
                    "point_order": point_order.get(point_id, len(point_order)),
                    "hazard_type": hazard_type,
                    "score": score,
                    "risk_level": str(risk.get("risk_level") or risk.get("level") or ""),
                }
            )
    return rows


def _point_physical_summary_rows(
    items: list[dict[str, Any]],
    point_order: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        point = item.get("point") or {}
        point_id = str(point.get("id") or "")
        point_name = str(point.get("name") or point_id)
        valid_time = str(item.get("valid_time") or "")
        run_time = str(item.get("run_time") or "")
        for field, evidence in (item.get("physical_evidence") or {}).items():
            if not isinstance(evidence, dict):
                continue
            value = _as_summary_float(evidence.get("value"))
            field_key = str(field or "")
            if value is None or not field_key:
                continue
            row = {
                "model": str(item.get("model") or ""),
                "data_code": str(item.get("data_code") or ""),
                "run_time": run_time,
                "run_datetime": _summary_datetime(run_time),
                "forecast_hour": int(item.get("forecast_hour") or 0),
                "valid_time": valid_time,
                "valid_datetime": _summary_datetime(valid_time),
                "point_id": point_id,
                "point_name": point_name,
                "point_order": point_order.get(point_id, len(point_order)),
                "field": field_key,
                "value": value,
                "api": str(evidence.get("api") or field_key.lower()),
                "label": str(evidence.get("label") or field_key),
                "unit": str(evidence.get("unit") or ""),
                "direction": str(evidence.get("direction") or "gte"),
                "watch": evidence.get("watch"),
                "high": evidence.get("high"),
            }
            row["level"] = _physical_summary_level(value, row)
            rows.append(row)
    return rows


def _summary_winner_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -float(row["score"]),
        row["valid_datetime"] or datetime.max,
        int(row["point_order"]),
        row["run_datetime"] or datetime.max,
        int(row["forecast_hour"]),
    )


def _physical_summary_winner_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _physical_summary_extreme_rank(row["value"], row),
        row["valid_datetime"] or datetime.max,
        int(row["point_order"]),
        row["run_datetime"] or datetime.max,
        int(row["forecast_hour"]),
    )


def _summary_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return parse_optional_time(value)
    except (TypeError, ValueError):
        return None


def _as_summary_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


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
