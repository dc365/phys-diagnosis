from __future__ import annotations

import math
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.services.data_sources import (
    DataSourceError,
    discover_nafp_run_inventory,
    list_data_sources,
    resolve_data_root,
)
from weather_diag.areas.registry import TownArea, load_area_registry
from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.area_risk import area_risk_metadata, evaluate_area_risks
from weather_diag.diagnosis.nafp_layers import _risk_input_bundle


DEFAULT_MODEL = "EC"
DEFAULT_DATA_CODE = "NAFP_ECTHIN_NC"
DEFAULT_WINDOW_HOURS = 6

REGION_ALIASES = {
    "fuzhou": {"region_code": "350100", "region_level": "city", "region_name": "福州市"},
    "福州": {"region_code": "350100", "region_level": "city", "region_name": "福州市"},
    "福州市": {"region_code": "350100", "region_level": "city", "region_name": "福州市"},
    "xiamen": {"region_code": "350200", "region_level": "city", "region_name": "厦门市"},
    "厦门": {"region_code": "350200", "region_level": "city", "region_name": "厦门市"},
    "厦门市": {"region_code": "350200", "region_level": "city", "region_name": "厦门市"},
}

RISK_DSL_FIELDS = [
    ("persistent_heavy_rain", "R_PHR", "持续性强降水", "risk_persistent_heavy_rain_score"),
    ("short_duration_heavy_rain", "R_SHR", "短时强降水", "risk_short_duration_heavy_rain_score"),
    ("thunderstorm_gale", "R_TG", "雷暴大风/下击暴流", "risk_thunderstorm_gale_score"),
    ("hail", "R_HAIL", "冰雹", "risk_hail_score"),
    ("rotating_storm_or_supercell", "R_ROT", "旋转风暴/超级单体潜势", "risk_rotating_storm_score"),
    ("severe_convection_composite", "R_SC", "强对流综合风险", "risk_severe_convection_composite_score"),
]

PHYSICAL_EVIDENCE_SPECS: OrderedDict[str, dict[str, Any]] = OrderedDict(
    [
        (
            "CAPE",
            {
                "source_field": "cape",
                "api": "cape",
                "label": "CAPE",
                "unit": "J/kg",
                "direction": "gte",
                "watch": 1000,
                "high": 2000,
            },
        ),
        (
            "CIN",
            {
                "source_field": "cin",
                "api": "cin",
                "label": "CIN",
                "unit": "J/kg",
                "direction": "lte",
                "watch": 150,
                "high": 50,
            },
        ),
        (
            "Q850",
            {
                "source_field": "q850",
                "api": "q850_g_kg",
                "label": "850hPa 比湿",
                "unit": "g/kg",
                "direction": "gte",
                "watch": 8,
                "high": 12,
                "transform": "_to_gkg",
            },
        ),
        (
            "PW",
            {
                "source_field": "pw",
                "api": "pw",
                "label": "整层可降水量",
                "unit": "mm",
                "direction": "gte",
                "watch": 30,
                "high": 55,
            },
        ),
        (
            "W700",
            {
                "source_field": "omega700",
                "api": "omega700",
                "label": "700hPa 垂直速度",
                "unit": "Pa/s",
                "direction": "lte",
                "watch": -0.05,
                "high": -0.35,
            },
        ),
        (
            "SHR6",
            {
                "source_field": "shear_0_6km",
                "api": "shear_0_6km",
                "label": "0-6km 风切变",
                "unit": "m/s",
                "direction": "gte",
                "watch": 12,
                "high": 20,
            },
        ),
        (
            "SHR1",
            {
                "source_field": "shear_0_1km",
                "api": "shear_0_1km",
                "label": "0-1km 风切变",
                "unit": "m/s",
                "direction": "gte",
                "watch": 5,
                "high": 15,
            },
        ),
        (
            "KI",
            {
                "source_field": "k_index",
                "api": "k_index",
                "label": "K 指数",
                "unit": "degC",
                "direction": "gte",
                "watch": 32,
                "high": 38,
            },
        ),
        (
            "LI",
            {
                "source_field": "li",
                "api": "li",
                "label": "抬升指数",
                "unit": "degC",
                "direction": "lte",
                "watch": 0,
                "high": -3,
            },
        ),
        (
            "DCAPE",
            {
                "source_field": "dcape",
                "api": "dcape",
                "label": "下沉对流有效位能",
                "unit": "J/kg",
                "direction": "gte",
                "watch": 500,
                "high": 1500,
            },
        ),
        (
            "SRH",
            {
                "source_field": "srh",
                "api": "srh",
                "label": "风暴相对螺旋度",
                "unit": "m2/s2",
                "direction": "gte",
                "watch": 100,
                "high": 300,
            },
        ),
        (
            "LCL",
            {
                "source_field": "lcl",
                "api": "lcl",
                "label": "抬升凝结高度",
                "unit": "m",
                "direction": "lte",
                "watch": 1600,
                "high": 600,
            },
        ),
        (
            "RH850",
            {
                "source_field": "rh850",
                "api": "rh850",
                "label": "850hPa 相对湿度",
                "unit": "%",
                "direction": "gte",
                "watch": 60,
                "high": 90,
            },
        ),
        (
            "RH700",
            {
                "source_field": "rh700",
                "api": "rh700",
                "label": "700hPa 相对湿度",
                "unit": "%",
                "direction": "gte",
                "watch": 60,
                "high": 90,
            },
        ),
        (
            "RH500",
            {
                "source_field": "rh500",
                "api": "rh500",
                "label": "500hPa 相对湿度",
                "unit": "%",
                "direction": "gte",
                "watch": 50,
                "high": 80,
            },
        ),
        (
            "RAIN3",
            {
                "source_field": "precip_3h",
                "api": "precip_3h",
                "label": "3小时降水量",
                "unit": "mm",
                "direction": "gte",
                "watch": 20,
                "high": 80,
            },
        ),
        (
            "RAIN6",
            {
                "source_field": "precip_6h",
                "api": "precip_6h",
                "label": "6小时降水量",
                "unit": "mm",
                "direction": "gte",
                "watch": 20,
                "high": 80,
            },
        ),
        (
            "RAIN24",
            {
                "source_field": "precip_24h",
                "api": "precip_24h",
                "label": "24小时降水量",
                "unit": "mm",
                "direction": "gte",
                "watch": 50,
                "high": 150,
            },
        ),
    ]
)

AREA_RISK_DSL_STRUCTURE_GUIDE = """乡镇风险 MCP 返回 FCST_TWN_PHY 格式 DSL。

核心结构：
- @B:FCST_TWN_PHY 表示模式预报、乡镇粒度、物理量/风险字段。
- @A 为区域行政代码，@S 给出县区到乡镇 S5 短码的映射。
- @M 为模式名，@T 为起报时间，@DT 为相对起报时间的分钟数。
- @ORD:DT>S5=... 表示正文 #PHY 每行先按时效分钟 DT，再按乡镇 S5 编码索引。
- 风险值字段使用 0-1，值越高风险越高；物理量证据字段使用 @PHY 中声明的原始业务单位和阈值，不做 0-1 归一化。
- 物理量证据按乡镇站点邻近格点采样后取均值；缺测、资料源未提供或该乡镇无有效采样时填 NA。
- JSON 中的 risk_metadata 保留六类风险元信息；物理量证据字段以 DSL 内的 @PHY_ORD 与 @PHY 为准。
"""


def parse_optional_time(value: str | datetime | None, *, default: datetime | None = None) -> datetime:
    if value is None or value == "":
        if default is None:
            raise ValueError("time value is required")
        return default
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1]
    return datetime.fromisoformat(raw).replace(tzinfo=None)


def normalize_models(models: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if models is None or models == "":
        return [DEFAULT_MODEL]
    if isinstance(models, str):
        values = [item.strip() for item in models.split(",")]
    else:
        values = [str(item).strip() for item in models]
    normalized = [item for item in values if item]
    return normalized or [DEFAULT_MODEL]


def resolve_region_scope(region: str | None = None) -> dict[str, Any]:
    raw = str(region or "fuzhou").strip()
    registry = load_area_registry()
    alias = REGION_ALIASES.get(raw) or REGION_ALIASES.get(raw.lower())
    if alias:
        towns = registry.towns_for_region(alias["region_code"], region_level=alias["region_level"])
        return {**alias, "town_count": len(towns), "towns": towns}

    towns = registry.towns_for_region(raw)
    if towns:
        level = _infer_region_level(raw, towns)
        return {
            "region_code": raw,
            "region_level": level,
            "region_name": _region_name_for_level(raw, level, towns),
            "town_count": len(towns),
            "towns": towns,
        }

    name_matches = _towns_for_region_name(raw, registry.all_towns())
    if name_matches:
        code, level, name, matched_towns = name_matches
        return {
            "region_code": code,
            "region_level": level,
            "region_name": name,
            "town_count": len(matched_towns),
            "towns": matched_towns,
        }

    raise ValueError(f"region not found or has no towns: {raw}")


def town_s5_code(town: TownArea) -> str:
    for point in town.points:
        raw = str(getattr(point, "s5_code", "") or "").strip()
        if raw:
            return raw
    county = str(town.county_code or "")[-3:]
    suffix = str(town.code or "")[-2:]
    return f"{county}{suffix}"


def resolve_forecast_hours_for_window(
    *,
    run_time: str | datetime,
    forecast_hours: list[int],
    start_time: str | datetime,
    end_time: str | datetime,
) -> list[int]:
    rt = parse_run_time(run_time)
    start = parse_optional_time(start_time)
    end = parse_optional_time(end_time)
    if end < start:
        raise ValueError("end_time must be >= start_time")
    out = [int(hour) for hour in forecast_hours if start <= rt + timedelta(hours=int(hour)) <= end]
    return _dedupe_ints(out)


def get_town_risk_dsl_payload(
    *,
    region: str = "fuzhou",
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    models: str | list[str] | None = None,
    data_code: str | None = None,
    #root: str | Path | None = None,
    run_time: str | datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    start = parse_optional_time(start_time, default=(now or datetime.now()).replace(tzinfo=None))
    end = parse_optional_time(end_time, default=start + timedelta(hours=DEFAULT_WINDOW_HOURS))
    if end < start:
        raise ValueError("end_time must be >= start_time")

    scope = resolve_region_scope(region)
    model_metadata: list[dict[str, Any]] = []
    dsl_blocks: list[str] = []
    risk_metadata_out: dict[str, dict[str, Any]] | None = None

    for model in normalize_models(models):
        source = resolve_model_source(model, data_code=data_code)
        context = resolve_forecast_context(
            data_code=source["data_code"],
            root=source["root"],
            run_time=run_time,
            start_time=start,
            end_time=end,
        )
        result = evaluate_area_risks(
            root=source["root"],
            run_time=context["run_time"],
            forecast_hours=context["forecast_hours"],
            towns=scope["towns"],
            risk_types=None,
            include_evidence=True,
            include_samples=False,
        )
        physical_evidence = build_physical_evidence(
            root=source["root"],
            run_time=context["run_time"],
            forecast_hours=context["forecast_hours"],
            towns=scope["towns"],
        )
        response = build_town_risk_dsl_response(
            request={"region": region, "start_time": start.isoformat(), "end_time": end.isoformat(), "models": [model]},
            region_scope=scope,
            model=source["model"],
            data_code=source["data_code"],
            #root=str(source["root"]),
            run_time=context["run_time"],
            forecast_hours=context["forecast_hours"],
            start_time=start,
            end_time=end,
            area_risk_result=result,
            risk_metadata=area_risk_metadata(),
            physical_evidence=physical_evidence,
        )
        dsl_blocks.append(response["dsl"])
        model_metadata.append(
            {
                "model": response["model"],
                "data_code": response["data_code"],
                "run_time": response["run_time"],
                "forecast_hours": response["forecast_hours"],
            }
        )
        if risk_metadata_out is None:
            risk_metadata_out = response["risk_metadata"]

    return {
        "request": {
            "region": region,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "models": normalize_models(models),
        },
        "region": _public_scope(scope),
        "model_metadata": model_metadata,
        "risk_metadata": risk_metadata_out or _risk_metadata_with_dsl_fields(area_risk_metadata()),
        "dsl": "\n\n".join(block for block in dsl_blocks if block),
        "dsl_structure_guide": AREA_RISK_DSL_STRUCTURE_GUIDE,
    }


def resolve_model_source(
    model: str | None,
    *,
    data_code: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    requested = str(model or DEFAULT_MODEL).strip()
    sources = list_data_sources()
    items = [item for item in sources.get("items") or [] if item.get("enabled")]

    selected = None
    if data_code:
        for item in items:
            if str(item.get("code")) == str(data_code):
                selected = item
                break
        if selected is None:
            raise DataSourceError(f"unknown data code: {data_code}")
    else:
        key = requested.upper()
        for item in items:
            candidates = {
                str(item.get("label") or "").upper(),
                str(item.get("model") or "").upper(),
                str(item.get("code") or "").upper(),
                str(item.get("name") or "").upper(),
            }
            if key in candidates:
                selected = item
                break
        if selected is None and key == DEFAULT_MODEL:
            selected = next((item for item in items if item.get("code") == sources.get("default_code")), None)
        if selected is None:
            raise DataSourceError(f"unsupported model: {requested}")

    resolved_root = Path(root) if root is not None else resolve_data_root(str(selected["code"]))
    return {
        "model": str(selected.get("model") or requested),
        "data_code": str(selected["code"]),
        "root": resolved_root,
        "forecast_hours": [int(hour) for hour in selected.get("forecast_hours") or []],
    }


def resolve_forecast_context(
    *,
    data_code: str,
    root: str | Path,
    run_time: str | datetime | None,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, Any]:
    if run_time is not None:
        configured = _configured_forecast_hours(data_code)
        hours = resolve_forecast_hours_for_window(
            run_time=run_time,
            forecast_hours=configured,
            start_time=start_time,
            end_time=end_time,
        )
        if not hours:
            raise ValueError("no forecast hours matched the requested time window")
        return {"run_time": parse_run_time(run_time), "forecast_hours": hours}

    inventory = discover_nafp_run_inventory(data_code=data_code, root=root, max_run_times=50)
    for item in inventory.get("run_times") or []:
        rt = parse_run_time(item["run_time"])
        available = [int(hour) for hour in item.get("forecast_hours") or []]
        hours = resolve_forecast_hours_for_window(
            run_time=rt,
            forecast_hours=available,
            start_time=start_time,
            end_time=end_time,
        )
        if hours:
            return {"run_time": rt, "forecast_hours": hours}

    raise ValueError("no NAFP run time matched the requested time window")


def build_town_risk_dsl_response(
    *,
    request: dict[str, Any],
    region_scope: dict[str, Any],
    model: str,
    data_code: str,
    #root: str,
    run_time: str | datetime,
    forecast_hours: list[int],
    start_time: str | datetime,
    end_time: str | datetime,
    area_risk_result: dict[str, Any],
    risk_metadata: dict[str, dict[str, Any]],
    physical_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    start = parse_optional_time(start_time)
    end = parse_optional_time(end_time)
    evidence_fields = _physical_evidence_fields(physical_evidence)
    physical_values = _physical_evidence_values(physical_evidence)
    ordered_fields = [field for _hazard, field, _label, _source in RISK_DSL_FIELDS] + list(evidence_fields)

    dsl = "\n".join(
        [
            *_metadata_lines(region_scope, model, rt, forecast_hours, ordered_fields, area_risk_result),
            *_phy_dictionary_lines(evidence_fields),
            "#PHY:",
            *_body_lines(area_risk_result, evidence_fields, physical_values),
        ]
    )

    return {
        "request": dict(request),
        "region": _public_scope(region_scope),
        "model": model,
        "data_code": data_code,
        #"root": root,
        "run_time": rt.isoformat(),
        "forecast_hours": [int(hour) for hour in forecast_hours],
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "risk_metadata": _risk_metadata_with_dsl_fields(risk_metadata),
        "evidence_fields": dict(evidence_fields),
        "dsl": dsl,
        "dsl_structure_guide": AREA_RISK_DSL_STRUCTURE_GUIDE,
        "area_risk": _area_risk_result_for_response(area_risk_result),
    }


def build_physical_evidence(
    *,
    root: str | Path,
    run_time: str | datetime,
    forecast_hours: list[int],
    towns: list[TownArea],
) -> dict[str, Any]:
    rt = parse_run_time(run_time)
    values: dict[tuple[int, str], dict[str, float]] = {}
    for hour in forecast_hours:
        try:
            fields, lat, lon, _source_paths = _risk_input_bundle(Path(root), rt.isoformat(), int(hour))
        except Exception:
            continue
        for town in towns:
            town_values = _sample_town_physical_values(town, fields, lat, lon)
            if town_values:
                values[(int(hour), town.code)] = town_values
    return {
        "fields": _public_physical_evidence_fields(PHYSICAL_EVIDENCE_SPECS),
        "values": values,
    }


def _metadata_lines(
    region_scope: dict[str, Any],
    model: str,
    run_time: datetime,
    forecast_hours: list[int],
    ordered_fields: list[str],
    area_risk_result: dict[str, Any],
) -> list[str]:
    towns = _towns_from_result_or_scope(area_risk_result, region_scope)
    return [
        "@B:FCST_TWN_PHY;",
        f"@A:{region_scope.get('region_code', '')};",
        "@CR:S5=县区3位短码+乡镇2位短码;",
        *_town_mapping_lines(towns),
        f"@M:{model};",
        f"@T:{_dsl_time(run_time)};",
        f"@DT:{','.join(str(int(hour) * 60) for hour in forecast_hours)};",
        "@WIN_RULE:VALID=@T+DT;",
        f"@ORD:DT>S5={'|'.join(ordered_fields)};",
        "@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;",
    ]


def _phy_dictionary_lines(evidence_fields: OrderedDict[str, dict[str, Any]]) -> list[str]:
    lines = [
        f"@PHY:{field}={source}|risk_score_0_1|gte|0.6|0.75;"
        for _hazard, field, _label, source in RISK_DSL_FIELDS
    ]
    for field, meta in evidence_fields.items():
        lines.append(
            f"@PHY:{field}={meta['api']}|{meta['unit']}|{meta['direction']}|"
            f"{_format_threshold(meta.get('watch'))}|{_format_threshold(meta.get('high'))};"
        )
    return lines


def _body_lines(
    area_risk_result: dict[str, Any],
    evidence_fields: OrderedDict[str, dict[str, Any]],
    physical_values: dict[tuple[int, str], dict[str, float]],
) -> list[str]:
    rows: list[str] = []
    for item in sorted(area_risk_result.get("items") or [], key=_item_sort_key):
        area = item.get("area") or {}
        town_code = str(area.get("town_code") or "")
        s5 = str(area.get("s5") or "") or _s5_from_codes(area.get("county_code"), town_code)
        forecast_hour = int(item.get("forecast_hour") or 0)
        dt = forecast_hour * 60
        risk_values = _risk_values(item.get("risks") or [])
        evidence_values = physical_values.get((forecast_hour, town_code), {})
        values = [
            _format_value(risk_values.get(hazard))
            for hazard, _field, _label, _source in RISK_DSL_FIELDS
        ]
        values.extend(_format_value(evidence_values.get(field)) for field in evidence_fields)
        rows.append(f"{dt}>{s5}={'|'.join(values)};")
    return rows


def _physical_evidence_fields(physical_evidence: dict[str, Any] | None) -> OrderedDict[str, dict[str, Any]]:
    raw_fields = (physical_evidence or {}).get("fields") or {}
    fields: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for key, meta in raw_fields.items():
        if not isinstance(meta, dict):
            continue
        field = str(meta.get("dsl_field") or key).strip()
        if not field:
            continue
        fields[field] = {
            "dsl_field": field,
            "api": str(meta.get("api") or field.lower()),
            "label": str(meta.get("label") or field),
            "unit": str(meta.get("unit") or ""),
            "direction": str(meta.get("direction") or "gte"),
            "watch": meta.get("watch"),
            "high": meta.get("high"),
            "statistic": str(meta.get("statistic") or "town_station_points_mean"),
        }
    return fields


def _physical_evidence_values(physical_evidence: dict[str, Any] | None) -> dict[tuple[int, str], dict[str, float]]:
    raw_values = (physical_evidence or {}).get("values") or {}
    values: dict[tuple[int, str], dict[str, float]] = {}
    for raw_key, item_values in raw_values.items():
        if not isinstance(item_values, dict):
            continue
        key = _physical_value_key(raw_key)
        if key is None:
            continue
        row: dict[str, float] = {}
        for field, value in item_values.items():
            number = _as_float(value)
            if number is not None:
                row[str(field)] = number
        if row:
            values[key] = row
    return values


def _public_physical_evidence_fields(specs: OrderedDict[str, dict[str, Any]]) -> OrderedDict[str, dict[str, Any]]:
    fields: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for field, meta in specs.items():
        fields[field] = {
            "dsl_field": field,
            "api": meta["api"],
            "label": meta["label"],
            "unit": meta["unit"],
            "direction": meta["direction"],
            "watch": meta["watch"],
            "high": meta["high"],
            "statistic": "town_station_points_mean",
        }
    return fields


def _risk_values(risks: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for risk in risks:
        hazard = str(risk.get("hazard_type") or "")
        value = _as_float(risk.get("score"))
        if hazard and value is not None:
            out[hazard] = value
    return out


def _sample_town_physical_values(
    town: TownArea,
    fields: dict[str, np.ndarray],
    lat: np.ndarray,
    lon: np.ndarray,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for dsl_field, spec in PHYSICAL_EVIDENCE_SPECS.items():
        raw = fields.get(str(spec.get("source_field") or ""))
        if raw is None:
            continue
        transformed = _transform_physical_grid(raw, str(spec.get("transform") or ""))
        value = _sample_town_grid_mean(town, transformed, lat, lon)
        if value is not None:
            values[dsl_field] = value
    return values


def _sample_town_grid_mean(
    town: TownArea,
    values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
) -> float | None:
    grid = _prepare_physical_grid(values, lat, lon)
    if grid is None:
        return None
    lat_values = np.asarray(lat, dtype=float)
    lon_values = np.asarray(lon, dtype=float)
    sampled: list[float] = []
    for point in town.points:
        lat_idx, lon_idx = _nearest_grid_indices(lat_values, lon_values, point.lat, point.lon)
        raw = float(grid[lat_idx, lon_idx])
        if math.isfinite(raw):
            sampled.append(raw)
    if not sampled:
        return None
    return float(np.nanmean(np.asarray(sampled, dtype=float)))


def _prepare_physical_grid(values: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray | None:
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


def _nearest_grid_indices(lat_values: np.ndarray, lon_values: np.ndarray, lat: float, lon: float) -> tuple[int, int]:
    query_lon = _normalize_query_lon(lon_values, lon)
    lat_idx = int(np.nanargmin(np.abs(lat_values - float(lat))))
    lon_idx = int(np.nanargmin(np.abs(lon_values - query_lon)))
    return lat_idx, lon_idx


def _normalize_query_lon(lon_values: np.ndarray, lon: float) -> float:
    lon_min = float(np.nanmin(lon_values))
    lon_max = float(np.nanmax(lon_values))
    query = float(lon)
    if lon_min >= 0.0 and lon_max > 180.0 and query < 0.0:
        return query % 360.0
    if lon_min < 0.0 and lon_max <= 180.0 and query > 180.0:
        return ((query + 180.0) % 360.0) - 180.0
    return query


def _transform_physical_grid(values: np.ndarray, transform: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if transform == "_to_gkg":
        valid = np.abs(arr[np.isfinite(arr)])
        if valid.size and float(np.nanmax(valid)) < 1.0:
            return arr * 1000.0
    return arr


def _physical_value_key(raw_key: Any) -> tuple[int, str] | None:
    if isinstance(raw_key, tuple) and len(raw_key) == 2:
        try:
            return int(raw_key[0]), str(raw_key[1])
        except (TypeError, ValueError):
            return None
    if isinstance(raw_key, str):
        if "|" in raw_key:
            hour, town_code = raw_key.split("|", 1)
        elif ":" in raw_key:
            hour, town_code = raw_key.split(":", 1)
        else:
            return None
        try:
            return int(hour), str(town_code)
        except ValueError:
            return None
    return None


def _risk_metadata_with_dsl_fields(risk_metadata: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for hazard, field, label, source in RISK_DSL_FIELDS:
        meta = dict(risk_metadata.get(hazard) or {})
        meta.setdefault("hazard_type", hazard)
        meta.setdefault("label", label)
        meta["dsl_field"] = field
        meta["source_grid"] = meta.get("source_grid") or source
        meta["score_range"] = [0, 1]
        meta["score_unit"] = "risk_score"
        meta["score_direction"] = "higher_is_riskier"
        out[hazard] = meta
    return out


def _area_risk_result_for_response(area_risk_result: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(area_risk_result)
    _strip_source_paths(result)
    summary = result.get("summary")
    if isinstance(summary, dict) and "max_score" in summary:
        summary["max_score"] = _round_score(float(summary["max_score"]))
    for item in result.get("items") or []:
        for risk in item.get("risks") or []:
            for key in ("score", "max_score", "mean_score", "p90_score"):
                value = _as_float(risk.get(key))
                if value is not None:
                    risk[key] = _round_score(value)
            metadata = risk.get("metadata")
            if isinstance(metadata, dict):
                metadata["score_range"] = [0, 1]
                metadata["score_unit"] = "risk_score"
            chain = risk.get("evidence_chain")
            if not isinstance(chain, dict):
                continue
            max_sample = chain.get("max_sample")
            if isinstance(max_sample, dict):
                value = _as_float(max_sample.get("score"))
                if value is not None:
                    max_sample["score"] = _round_score(value)
            for factor in chain.get("dominant_factors") or []:
                for key in ("mean_score", "mean_contribution", "max_contribution"):
                    value = _as_float(factor.get(key))
                    if value is not None:
                        factor[key] = _round_score(value)
    return result


def _strip_source_paths(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value.keys()):
            if key in {"source_paths", "source_path"}:
                value.pop(key, None)
            else:
                _strip_source_paths(value[key])
    elif isinstance(value, list):
        for item in value:
            _strip_source_paths(item)


def _town_mapping_lines(towns: list[dict[str, Any]]) -> list[str]:
    counties: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for town in towns:
        county_code = str(town.get("county_code") or "")
        county_name = str(town.get("county_name") or "")
        county_short = county_code[-3:] if county_code else ""
        bucket = counties.setdefault(county_short, {"name": county_name, "towns": []})
        s5 = str(town.get("s5") or "") or _s5_from_codes(county_code, town.get("town_code"))
        bucket["towns"].append((s5, str(town.get("town_name") or "")))
    lines = []
    for county_short, item in counties.items():
        towns_text = ",".join(f"{s5}{name}" for s5, name in item["towns"])
        lines.append(f"@S:{county_short}={item['name']}>{towns_text};")
    return lines


def _towns_from_result_or_scope(area_risk_result: dict[str, Any], region_scope: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in area_risk_result.get("items") or []:
        area = item.get("area") or {}
        code = str(area.get("town_code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(area)
    if out:
        return out
    return [town.to_dict(include_points=False) for town in region_scope.get("towns") or []]


def _public_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_code": scope.get("region_code"),
        "region_level": scope.get("region_level"),
        "region_name": scope.get("region_name"),
        "town_count": scope.get("town_count"),
    }


def _infer_region_level(code: str, towns: list[TownArea]) -> str:
    if any(town.code == code for town in towns):
        return "town"
    if any(town.county_code == code for town in towns):
        return "county"
    if any(town.city_code == code for town in towns):
        return "city"
    return "region"


def _region_name_for_level(code: str, level: str, towns: list[TownArea]) -> str:
    first = towns[0]
    if level == "city":
        return first.city_name
    if level == "county":
        return first.county_name
    if level == "town":
        return first.name
    return code


def _towns_for_region_name(name: str, towns: list[TownArea]) -> tuple[str, str, str, list[TownArea]] | None:
    city_matches = [town for town in towns if town.city_name == name]
    if city_matches:
        return city_matches[0].city_code, "city", city_matches[0].city_name, city_matches
    county_matches = [town for town in towns if town.county_name == name]
    if county_matches:
        return county_matches[0].county_code, "county", county_matches[0].county_name, county_matches
    town_matches = [town for town in towns if town.name == name]
    if town_matches:
        town = town_matches[0]
        return town.code, "town", town.name, [town]
    return None


def _configured_forecast_hours(data_code: str) -> list[int]:
    for item in list_data_sources().get("items") or []:
        if str(item.get("code")) == str(data_code):
            return [int(hour) for hour in item.get("forecast_hours") or []]
    return []


def _dedupe_ints(values: list[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        number = int(value)
        if number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out


def _dsl_time(value: datetime) -> str:
    return value.strftime("%y%m%d%H%M")


def _item_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    area = item.get("area") or {}
    return int(item.get("forecast_hour") or 0), str(area.get("county_code") or ""), str(area.get("town_code") or "")


def _s5_from_codes(county_code: Any, town_code: Any) -> str:
    county = str(county_code or "")[-3:]
    town = str(town_code or "")[-2:]
    return f"{county}{town}"


def _format_threshold(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "NA"
    text = str(Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_value(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "NA"
    return str(Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_score(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
