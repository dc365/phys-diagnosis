from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from weather_diag.config import ADMIN_DIR


CONFIG_PATH = ADMIN_DIR / "auto_diagnostics_schedule.json"
DEFAULT_CONFIG = {
    "enabled": True,
    "mode": "interval",
    "interval_minutes": 60,
    "fixed_times": [],
    "tasks": {"nafp_precompute": True, "sounding_preprocess": True},
}

_LOCK = threading.RLock()
_SCHEDULER_THREAD: threading.Thread | None = None
_SCHEDULER_STATE: dict[str, Any] = {
    "last_interval_run": None,
    "fixed_run_keys": set(),
    "last_scan": None,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_fixed_times(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    times: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            hour, minute = [int(part) for part in text.split(":", 1)]
        except Exception:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            times.add(f"{hour:02d}:{minute:02d}")
    return sorted(times)


def _normalize_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = {**DEFAULT_CONFIG, **(payload or {})}
    raw_tasks = raw.get("tasks") if isinstance(raw.get("tasks"), dict) else {}
    try:
        interval = int(raw.get("interval_minutes") or DEFAULT_CONFIG["interval_minutes"])
    except (TypeError, ValueError):
        interval = DEFAULT_CONFIG["interval_minutes"]
    config = {
        "enabled": bool(raw.get("enabled", True)),
        "mode": "fixed" if raw.get("mode") == "fixed" else "interval",
        "interval_minutes": max(1, interval),
        "fixed_times": _normalize_fixed_times(raw.get("fixed_times")),
        "tasks": {
            "nafp_precompute": bool(raw_tasks.get("nafp_precompute", True)),
            "sounding_preprocess": bool(raw_tasks.get("sounding_preprocess", True)),
        },
    }
    if raw.get("updated_at"):
        config["updated_at"] = str(raw["updated_at"])
    return config


def load_auto_schedule_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _normalize_config(None)
    try:
        return _normalize_config(_read_json(CONFIG_PATH))
    except Exception:
        return _normalize_config(None)


def save_auto_schedule_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = _normalize_config(payload)
    config["updated_at"] = _now()
    _write_json(CONFIG_PATH, config)
    return config


def run_auto_diagnostics_once(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _normalize_config(config or load_auto_schedule_config())
    results: dict[str, Any] = {}
    if cfg["tasks"].get("nafp_precompute"):
        from backend.app.services.data_sources import list_data_sources
        from weather_diag.diagnosis.nafp_precompute import autostart_precompute_for_latest

        results["nafp_precompute"] = autostart_precompute_for_latest(list_data_sources())
    if cfg["tasks"].get("sounding_preprocess"):
        from weather_diag.diagnosis.sounding_preprocess import autostart_sounding_preprocess

        results["sounding_preprocess"] = autostart_sounding_preprocess()
    scan = {"status": "scanned", "scanned_at": _now(), "tasks": results}
    with _LOCK:
        _SCHEDULER_STATE["last_scan"] = scan
    return scan


def tick_auto_diagnosis_scheduler(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now().astimezone()).astimezone()
    config = load_auto_schedule_config()
    if not config.get("enabled"):
        return {"status": "skipped", "reason": "disabled"}

    with _LOCK:
        if config["mode"] == "fixed":
            current_time = current.strftime("%H:%M")
            if current_time not in config.get("fixed_times", []):
                return {"status": "skipped", "reason": "not_fixed_time"}
            key = f"{current.date().isoformat()} {current_time}"
            if key in _SCHEDULER_STATE["fixed_run_keys"]:
                return {"status": "skipped", "reason": "already_ran"}
            _SCHEDULER_STATE["fixed_run_keys"].add(key)
        else:
            last = _SCHEDULER_STATE.get("last_interval_run")
            interval_seconds = int(config["interval_minutes"]) * 60
            if last is not None and (current - last).total_seconds() < interval_seconds:
                return {"status": "skipped", "reason": "waiting_interval"}
            _SCHEDULER_STATE["last_interval_run"] = current

    return run_auto_diagnostics_once(config)


def auto_scheduler_status() -> dict[str, Any]:
    with _LOCK:
        thread = _SCHEDULER_THREAD
        last_interval_run = _SCHEDULER_STATE.get("last_interval_run")
        return {
            "config": load_auto_schedule_config(),
            "running": bool(thread and thread.is_alive()),
            "last_interval_run": last_interval_run.isoformat() if isinstance(last_interval_run, datetime) else None,
            "last_scan": _SCHEDULER_STATE.get("last_scan"),
        }


def _scheduler_loop() -> None:
    tick_auto_diagnosis_scheduler()
    while True:
        time.sleep(60)
        tick_auto_diagnosis_scheduler()


def start_auto_diagnosis_scheduler() -> dict[str, Any] | None:
    if str(os.getenv("WEATHER_DIAG_AUTO_DIAG_SCHEDULER", "1")).lower() in {"0", "false", "no", "off"}:
        return None
    global _SCHEDULER_THREAD
    with _LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return {"status": "running"}
        thread = threading.Thread(target=_scheduler_loop, name="auto-diagnosis-scheduler", daemon=True)
        _SCHEDULER_THREAD = thread
        thread.start()
    return {"status": "started"}
