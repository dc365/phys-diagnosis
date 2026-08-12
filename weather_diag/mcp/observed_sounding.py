from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from weather_diag.config import PROJECT_ROOT, load_yaml


DEFAULT_STATIONS: dict[str, dict[str, Any]] = {
    "58847": {"province": "福建", "name": "福州站"},
    "59134": {"province": "福建", "name": "厦门站"},
    "58725": {"province": "福建", "name": "南平邵武站"},
}

SOUNDING_PHYSICAL_RULES: list[dict[str, Any]] = [
    {
        "field": "CAPE",
        "label": "CAPE",
        "category": "热力不稳定",
        "unit": "J/kg",
        "operator": "gte",
        "watch": 1000,
        "high": 2000,
        "basis": "CAPE >=1000 J/kg 表示能量较充足，>=2000 J/kg 表示强对流高潜势。",
        "high_summary": "CAPE 达强对流高潜势，环境能量充足。",
        "watch_summary": "CAPE 达关注阈值，具备对流发展能量基础。",
        "neutral_summary": "CAPE 未达关注阈值，热力能量支持偏弱。",
    },
    {
        "field": "CIN",
        "label": "CIN",
        "category": "对流抑制",
        "unit": "J/kg",
        "operator": "abs_lte",
        "watch": 150,
        "high": 50,
        "basis": "|CIN| <50 J/kg 抑制较弱，50-150 J/kg 有抑制，>=150 J/kg 抑制强。",
        "high_summary": "CIN 抑制弱，低层触发更容易突破。",
        "watch_summary": "CIN 存在一定抑制，需配合系统抬升或低层辐合触发。",
        "neutral_summary": "CIN 抑制偏强，有能量也不一定能释放。",
    },
    {
        "field": "K",
        "label": "K 指数",
        "category": "对流指数",
        "unit": "degC",
        "operator": "gte",
        "watch": 32,
        "high": 35,
        "basis": "K 指数 32/35/38 常用于雷暴和短时强降水环境参考。",
        "high_summary": "K 指数较高，雷暴和短时强降水环境支持明显。",
        "watch_summary": "K 指数达到关注阈值，对流环境有一定支持。",
        "neutral_summary": "K 指数未达关注阈值，对流指数支持偏弱。",
    },
    {
        "field": "SI",
        "label": "SI",
        "category": "层结稳定度",
        "unit": "degC",
        "operator": "lte",
        "watch": 0,
        "high": -4,
        "basis": "SI <0 表示层结不稳定，越负越有利于强对流发展。",
        "high_summary": "SI 明显为负，层结不稳定支持强。",
        "watch_summary": "SI 为负，层结具备不稳定条件。",
        "neutral_summary": "SI 未达不稳定关注阈值。",
    },
    {
        "field": "DCAPE",
        "label": "DCAPE",
        "category": "下沉大风潜势",
        "unit": "J/kg",
        "operator": "gte",
        "watch": 800,
        "high": 1000,
        "basis": "DCAPE 800/1000 J/kg 可作为雷暴大风或下击暴流潜势参考。",
        "high_summary": "DCAPE 较高，下击暴流或雷暴大风潜势明显。",
        "watch_summary": "DCAPE 达关注阈值，需关注下沉冷池和阵风潜势。",
        "neutral_summary": "DCAPE 未达关注阈值，下沉大风支持偏弱。",
    },
    {
        "field": "SRH",
        "label": "SRH",
        "category": "旋转环境",
        "unit": "m2/s2",
        "operator": "gte",
        "watch": 100,
        "high": 300,
        "basis": "SRH 100/300 m2/s2 可作为旋转风暴环境参考。",
        "high_summary": "SRH 很高，旋转风暴环境支持强。",
        "watch_summary": "SRH 达关注阈值，存在一定旋转环境支持。",
        "neutral_summary": "SRH 未达关注阈值，旋转环境支持偏弱。",
    },
    {
        "field": "SHR6KM",
        "label": "0-6km 风切变",
        "category": "组织化对流",
        "unit": "m/s",
        "operator": "gte",
        "watch": 12,
        "high": 20,
        "basis": "0-6km 风切变 12/20 m/s 可作为组织化强对流和超级单体环境参考。",
        "high_summary": "0-6km 风切变强，支持组织化强对流。",
        "watch_summary": "0-6km 风切变达关注阈值，对流组织化有一定支持。",
        "neutral_summary": "0-6km 风切变未达关注阈值，组织化支持偏弱。",
    },
]


def load_observed_sounding_config() -> dict[str, Any]:
    config = load_yaml("observed_sounding.yaml")
    stations = DEFAULT_STATIONS | dict(config.get("stations") or {})
    return {
        "endpoint": os.getenv("WEATHER_DIAG_SOUNDING_ENDPOINT", str(config.get("endpoint") or "")).strip(),
        "user": os.getenv("WEATHER_DIAG_SOUNDING_USER", str(config.get("user") or "")).strip(),
        "password": os.getenv("WEATHER_DIAG_SOUNDING_PASSWORD", str(config.get("password") or "")).strip(),
        "timeout_seconds": float(os.getenv("WEATHER_DIAG_SOUNDING_TIMEOUT", config.get("timeout_seconds") or 10)),
        "test_mode": _env_bool("WEATHER_DIAG_SOUNDING_TEST_MODE", bool(config.get("test_mode", False))),
        "test_data_template": os.getenv(
            "WEATHER_DIAG_SOUNDING_TEST_DATA_TEMPLATE",
            str(config.get("test_data_template") or "test_datas/sktk_{station}.json"),
        ).strip(),
        "stations": stations,
    }


def select_observation_time(now: datetime | None = None) -> datetime:
    current = (now or datetime.now()).replace(tzinfo=None)
    today_08 = current.replace(hour=8, minute=0, second=0, microsecond=0)
    today_20 = current.replace(hour=20, minute=0, second=0, microsecond=0)
    if current < today_08:
        return today_20 - timedelta(days=1)
    if current < today_20:
        return today_08
    return today_20


def get_observed_sounding_payload(
    station_code: str | None = None,
    observation_time: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = load_observed_sounding_config()
    obs_time, _time_source = resolve_observation_time(observation_time, now)
    station_codes = _station_codes(station_code, config)
    stations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for code in station_codes:
        try:
            raw = fetch_station_payload(config, code, obs_time)
            stations.append(normalize_station_payload(raw, code, obs_time, config["stations"].get(code) or {}))
        except Exception as exc:
            failures.append({"station_code": code, "error": str(exc)})
    return {
        "request": {
            "station_codes": station_codes,
            "observation_time": obs_time.isoformat(timespec="seconds"),
        },
        "stations": stations,
        "failures": failures,
    }


def fetch_station_payload(config: dict[str, Any], station_code: str, obs_time: datetime) -> dict[str, Any]:
    if config.get("test_mode"):
        return fetch_station_test_payload(config, station_code)
    endpoint = str(config.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("observed sounding endpoint is not configured")
    time_text = obs_time.strftime("%Y-%m-%d %H:%M:%S")
    query = urlencode(
        {
            "user": config.get("user") or "",
            "password": config.get("password") or "",
            "beginTime": time_text,
            "endTime": time_text,
            "stationCode": station_code,
        }
    )
    url = f"{endpoint}?{query}"
    with urlopen(url, timeout=float(config.get("timeout_seconds") or 10)) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_station_test_payload(config: dict[str, Any], station_code: str) -> dict[str, Any]:
    template = str(config.get("test_data_template") or "test_datas/sktk_{station}.json")
    path = Path(template.format(station=station_code, station_code=station_code))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"observed sounding test data not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_station_payload(
    raw: dict[str, Any],
    station_code: str,
    obs_time: datetime,
    station_meta: dict[str, Any],
) -> dict[str, Any]:
    item = _select_data_item(raw, obs_time)
    data = item.get("data") if isinstance(item.get("data"), dict) else item
    data = data if isinstance(data, dict) else {}
    height_points = dict(data.get("heightPoints") or {})
    physical_diagnoses = diagnose_sounding_physical_quantities(height_points)
    return {
        "station_code": str(raw.get("stationCode") or station_code),
        "station_name": station_meta.get("name") or station_code,
        "province": station_meta.get("province") or "",
        "data_time": str(item.get("dataTime") or obs_time.strftime("%Y-%m-%d %H:%M:%S")),
        "message": raw.get("msg") or "",
        "height_points": height_points,
        "physical_diagnoses": physical_diagnoses,
        "physical_diagnosis_summary": _physical_diagnosis_summary(physical_diagnoses),
        "weather_diagnosis": _weather_diagnosis(physical_diagnoses),
    }


def diagnose_sounding_physical_quantities(height_points: dict[str, Any]) -> list[dict[str, Any]]:
    diagnoses: list[dict[str, Any]] = []
    for rule in SOUNDING_PHYSICAL_RULES:
        field = str(rule["field"])
        raw_value = height_points.get(field)
        value = _as_float(raw_value)
        if value is None:
            continue
        level, evaluated_value = _support_level(value, rule)
        diagnoses.append(
            {
                "field": field,
                "label": rule["label"],
                "category": rule["category"],
                "value": raw_value,
                "evaluated_value": evaluated_value,
                "unit": rule["unit"],
                "operator": rule["operator"],
                "support_level": level,
                "score": {"high": 1.0, "watch": 0.6, "neutral": 0.0}[level],
                "summary": rule[f"{level}_summary"],
                "evidence_chain": [
                    {
                        "source": f"heightPoints.{field}",
                        "value": raw_value,
                        "evaluated_value": evaluated_value,
                        "unit": rule["unit"],
                        "operator": rule["operator"],
                        "thresholds": {"watch": rule["watch"], "high": rule["high"]},
                        "support_level": level,
                        "basis": rule["basis"],
                    }
                ],
            }
        )
    return diagnoses


def resolve_observation_time(observation_time: str | None = None, now: datetime | None = None) -> tuple[datetime, str]:
    if isinstance(observation_time, str) and observation_time.strip():
        return parse_observation_time(observation_time), "specified"
    return select_observation_time(now), "latest_observation"


def parse_observation_time(value: str) -> datetime:
    text = value.strip().replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError("observation_time must be ISO format or YYYY-MM-DD HH:MM[:SS]") from exc


def _station_codes(station_code: str | None, config: dict[str, Any]) -> list[str]:
    supported_order = [str(code) for code in (config.get("stations") or DEFAULT_STATIONS)]
    supported = set(supported_order)
    if station_code is None or not str(station_code).strip():
        return supported_order
    requested = [
        part.strip()
        for chunk in str(station_code).replace(";", ",").split(",")
        for part in [chunk]
        if part.strip()
    ]
    unsupported = [code for code in requested if code not in supported]
    if unsupported:
        raise ValueError(f"unsupported sounding station: {', '.join(unsupported)}")
    return requested


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _support_level(value: float, rule: dict[str, Any]) -> tuple[str, float]:
    operator = rule["operator"]
    watch = float(rule["watch"])
    high = float(rule["high"])
    evaluated = abs(value) if operator == "abs_lte" else value
    if operator == "gte":
        if evaluated >= high:
            return "high", evaluated
        if evaluated >= watch:
            return "watch", evaluated
        return "neutral", evaluated
    if operator in {"lte", "abs_lte"}:
        if evaluated <= high:
            return "high", evaluated
        if evaluated <= watch:
            return "watch", evaluated
        return "neutral", evaluated
    return "neutral", evaluated


def _physical_diagnosis_summary(diagnoses: list[dict[str, Any]]) -> dict[str, Any]:
    high = [item for item in diagnoses if item.get("support_level") == "high"]
    watch = [item for item in diagnoses if item.get("support_level") == "watch"]
    neutral = [item for item in diagnoses if item.get("support_level") == "neutral"]
    return {
        "diagnosis_count": len(diagnoses),
        "high_count": len(high),
        "watch_count": len(watch),
        "neutral_count": len(neutral),
        "dominant_fields": [item["field"] for item in high + watch],
        "summary": "；".join(item["summary"] for item in high + watch) or "探空物理量未出现明显关注信号。",
    }


def _weather_diagnosis(diagnoses: list[dict[str, Any]]) -> dict[str, Any]:
    supporting = [item for item in diagnoses if item.get("support_level") in {"high", "watch"}]
    focus: list[str] = []
    fields = {str(item.get("field") or "") for item in supporting}
    if fields & {"CAPE", "CIN", "K", "SI"}:
        focus.append("强对流环境")
    if fields & {"CAPE", "K"}:
        focus.append("短时强降水环境")
    if fields & {"DCAPE", "SHR6KM"}:
        focus.append("雷暴大风/下击暴流环境")
    if fields & {"SRH", "SHR6KM"}:
        focus.append("旋转风暴/组织化对流环境")
    summary = "；".join(item["summary"] for item in supporting) or "本站探空暂未显示明显强天气环境信号。"
    return {
        "description": (
            "基于本站实况探空物理量的天气诊断描述，反映垂直环境对强对流、短时强降水、"
            "雷暴大风和旋转风暴等类型的支持程度；它是站点环境证据，不直接代表格点风险落区。"
        ),
        "summary": summary,
        "focus": focus,
        "evidence_fields": [str(item["field"]) for item in diagnoses],
        "limitations": "探空站代表性受站点位置和观测时次限制，仍需结合雷达、自动站、风廓线和数值预报触发条件综合判断。",
    }


def _select_data_item(raw: dict[str, Any], obs_time: datetime) -> dict[str, Any]:
    items = raw.get("dataList") if isinstance(raw.get("dataList"), list) else []
    if not items:
        return {}
    target = obs_time.strftime("%Y-%m-%d %H:%M:%S")
    for item in items:
        if isinstance(item, dict) and item.get("dataTime") == target:
            return item
    first = items[0]
    return first if isinstance(first, dict) else {}
