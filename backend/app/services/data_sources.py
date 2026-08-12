from __future__ import annotations

import os
import re
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from weather_diag.config import PROJECT_ROOT, load_yaml


FALLBACK_NAFP_SOURCE = {
    "code": "NAFP_ECTHIN_NC",
    "label": "ECTHIN",
    "name": "NAFP_ECTHIN_NC",
    "model": "EC",
    "format": "nc",
    "root": "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC",
    "forecast_hour_start": 0,
    "forecast_hour_end": 240,
    "forecast_hour_step": 3,
    "enabled": True,
    "default": True,
}


class DataSourceError(ValueError):
    pass


NAFP_FORECAST_FILE_RE = re.compile(r"^(?P<stamp>\d{8})\.(?P<forecast_hour>\d{3})$")
_inventory_cache: dict[tuple[str, str, str, str, int], tuple[float, dict[str, Any]]] = {}
_inventory_cache_lock = threading.RLock()


def _expand_root(value: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def _forecast_hour_range(raw: dict[str, Any]) -> dict[str, int]:
    start = int(raw.get("forecast_hour_start", raw.get("forecast_start", 0)))
    end = int(raw.get("forecast_hour_end", raw.get("forecast_end", start)))
    step = int(raw.get("forecast_hour_step", raw.get("forecast_step", 1)))
    if step <= 0:
        raise DataSourceError("forecast_hour_step must be positive")
    if end < start:
        raise DataSourceError("forecast_hour_end must be >= forecast_hour_start")
    return {"start": start, "end": end, "step": step}


def _forecast_hours_from_range(hour_range: dict[str, int]) -> list[int]:
    return list(range(hour_range["start"], hour_range["end"] + 1, hour_range["step"]))


def _normalize_source(raw: dict[str, Any]) -> dict[str, Any]:
    code = str(raw.get("code") or "").strip()
    root = str(raw.get("root") or "").strip()
    if not code or not root:
        raise DataSourceError("data source requires code and root")
    hour_range = _forecast_hour_range(raw)
    return {
        "code": code,
        "label": str(
            raw.get("label")
            or raw.get("display_name")
            or raw.get("mode_name")
            or raw.get("name")
            or code
        ),
        "name": str(raw.get("name") or code),
        "model": str(raw.get("model") or ""),
        "format": str(raw.get("format") or ""),
        "root": _expand_root(root),
        "forecast_hour_range": hour_range,
        "forecast_hours": _forecast_hours_from_range(hour_range),
        "enabled": bool(raw.get("enabled", True)),
        "default": bool(raw.get("default", False)),
    }


def list_data_sources() -> dict[str, Any]:
    config = load_yaml("data_sources.yaml")
    raw_items = config.get("data_sources") or config.get("items") or [FALLBACK_NAFP_SOURCE]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        try:
            item = _normalize_source(raw)
        except DataSourceError:
            continue
        if item["code"] in seen:
            continue
        seen.add(item["code"])
        items.append(item)
    if not items:
        items = [_normalize_source(FALLBACK_NAFP_SOURCE)]
    default = next((item for item in items if item["default"] and item["enabled"]), None)
    default = default or next((item for item in items if item["enabled"]), None) or items[0]
    return {"default_code": default["code"], "items": items}


def resolve_data_root(data_code: str | None = None, root: str | Path | None = None) -> Path:
    code = str(data_code or "").strip()
    if code:
        for item in list_data_sources()["items"]:
            if item["code"] == code and item["enabled"]:
                return Path(item["root"])
        raise DataSourceError(f"unknown data code: {code}")
    if root:
        return Path(root)
    default_code = list_data_sources()["default_code"]
    return resolve_data_root(default_code)


def _run_time_from_path_parts(parts: tuple[str, ...]) -> datetime | None:
    if len(parts) < 4:
        return None
    year, month, day, hour = parts[-4:]
    try:
        return datetime(int(year), int(month), int(day), int(hour))
    except ValueError:
        return None


def _iter_nafp_forecast_files(root: Path, element: str, level: str) -> list[Path]:
    probe_root = root / element / str(level)
    if probe_root.exists():
        return [path for path in probe_root.glob("*/*/*/*/*") if path.is_file()]
    return [path for path in root.glob("*/*/*/*/*/*/*") if path.is_file()]


def _numeric_child_dirs(parent: Path) -> list[Path]:
    try:
        return sorted(
            (path for path in parent.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return []


def _recent_nafp_run_dirs(probe_root: Path, max_run_times: int) -> list[tuple[datetime, Path]]:
    runs: list[tuple[datetime, Path]] = []
    for year_dir in _numeric_child_dirs(probe_root):
        for month_dir in _numeric_child_dirs(year_dir):
            for day_dir in _numeric_child_dirs(month_dir):
                for hour_dir in _numeric_child_dirs(day_dir):
                    try:
                        run_time = datetime(
                            int(year_dir.name),
                            int(month_dir.name),
                            int(day_dir.name),
                            int(hour_dir.name),
                        )
                    except ValueError:
                        continue
                    runs.append((run_time, hour_dir))
                    if len(runs) >= max_run_times:
                        return runs
    return runs


def _discover_nafp_run_inventory_uncached(
    *,
    data_root: Path,
    data_code: str,
    element: str,
    level: str,
    max_run_times: int,
) -> dict[str, Any]:
    run_hours: dict[str, set[int]] = {}
    probe_root = data_root / element / str(level)

    if data_root.exists():
        run_dirs = _recent_nafp_run_dirs(probe_root, max_run_times) if probe_root.exists() else []
        if run_dirs:
            for run_time, run_dir in run_dirs:
                try:
                    files = list(run_dir.iterdir())
                except OSError:
                    continue
                for path in files:
                    if not path.is_file():
                        continue
                    match = NAFP_FORECAST_FILE_RE.match(path.name)
                    if match:
                        run_hours.setdefault(run_time.isoformat(), set()).add(
                            int(match.group("forecast_hour"))
                        )
        else:
            for path in _iter_nafp_forecast_files(data_root, element, level):
                match = NAFP_FORECAST_FILE_RE.match(path.name)
                if not match:
                    continue
                try:
                    relative_parent = path.parent.relative_to(data_root)
                except ValueError:
                    continue
                run_time = _run_time_from_path_parts(relative_parent.parts)
                if run_time:
                    run_hours.setdefault(run_time.isoformat(), set()).add(
                        int(match.group("forecast_hour"))
                    )

    run_times = [
        {"run_time": run_time, "forecast_hours": sorted(hours)}
        for run_time, hours in sorted(run_hours.items(), reverse=True)
        if hours
    ][:max_run_times]
    return {
        "data_code": data_code,
        "root": str(data_root),
        "probe": {"element": element, "level": str(level)},
        "default_run_time": run_times[0]["run_time"] if run_times else None,
        "run_times": run_times,
    }


def clear_nafp_run_inventory_cache() -> None:
    with _inventory_cache_lock:
        _inventory_cache.clear()


def discover_nafp_run_inventory(
    *,
    data_code: str | None = None,
    root: str | Path | None = None,
    element: str = "gh",
    level: str = "500",
    max_run_times: int = 20,
) -> dict[str, Any]:
    data_root = (Path(root) if root is not None else resolve_data_root(data_code)).resolve()
    safe_max = max(1, min(int(max_run_times or 20), 200))
    code = str(data_code or "")
    key = (str(data_root), code, str(element), str(level), safe_max)
    now = monotonic()
    ttl_seconds = max(1.0, float(os.getenv("WEATHER_DIAG_RUN_INVENTORY_TTL_SECONDS", "30")))
    with _inventory_cache_lock:
        cached = _inventory_cache.get(key)
        if cached is not None and cached[0] > now:
            return deepcopy(cached[1])

    payload = _discover_nafp_run_inventory_uncached(
        data_root=data_root,
        data_code=code,
        element=str(element),
        level=str(level),
        max_run_times=safe_max,
    )
    with _inventory_cache_lock:
        _inventory_cache[key] = (now + ttl_seconds, payload)
    return deepcopy(payload)
