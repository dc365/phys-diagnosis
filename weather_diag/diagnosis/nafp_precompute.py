from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from backend.app.services.nafp_process import (
    diagnose_nafp_situation_isolated,
    nafp_process_status,
)
from weather_diag.config import ADMIN_DIR, ensure_dirs
from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.nafp_cache import get_or_compute_nafp_situation


PRECOMPUTE_DIR = ADMIN_DIR / "nafp_precompute"
RESULT_DIR = PRECOMPUTE_DIR / "results"
STATE_PATH = PRECOMPUTE_DIR / "state.json"
STATE_VERSION = "nafp-precompute-v1"

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_current_job_id: str | None = None
_last_loaded = False
_active_flights: dict[tuple[str, str, str, int], tuple[str, threading.Event]] = {}
_active_job_ids: set[str] = set()
_job_queue: queue.Queue[str] = queue.Queue()
_worker_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        import numpy as np

        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, (np.bool_,)):
            return bool(value)
    except Exception:
        pass
    return str(value)


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def _safe_read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(*parts: Any) -> str:
    text = "|".join(str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _result_id(root: str | Path, run_time: str | datetime, forecast_hour: int, data_code: str | None = None) -> str:
    rt = parse_run_time(run_time).isoformat()
    root_text = str(Path(root).resolve())
    return _fingerprint(data_code or "", root_text, rt, int(forecast_hour))


def result_path(root: str | Path, run_time: str | datetime, forecast_hour: int, data_code: str | None = None) -> Path:
    rt = parse_run_time(run_time).strftime("%Y%m%d%H")
    code = str(data_code or "default").replace("/", "_")
    return RESULT_DIR / code / rt / f"fh{int(forecast_hour):03d}-{_result_id(root, run_time, forecast_hour, data_code)}.json"


def _work_key(
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
    data_code: str | None = None,
) -> tuple[str, str, str, int]:
    return (
        str(data_code or ""),
        str(Path(root).resolve()),
        parse_run_time(run_time).isoformat(),
        int(forecast_hour),
    )


def precomputed_result_exists(root: str | Path, run_time: str | datetime, forecast_hour: int, data_code: str | None = None) -> bool:
    return result_path(root, run_time, forecast_hour, data_code).exists()


def load_precomputed_result(root: str | Path, run_time: str | datetime, forecast_hour: int, data_code: str | None = None) -> dict[str, Any]:
    path = result_path(root, run_time, forecast_hour, data_code)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return _safe_read_json(path)["result"]


def store_precomputed_result(
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
    result: dict[str, Any],
    *,
    data_code: str | None = None,
    compute_ms: float | None = None,
) -> Path:
    path = result_path(root, run_time, forecast_hour, data_code)
    payload = {
        "version": STATE_VERSION,
        "data_code": data_code,
        "root": str(Path(root).resolve()),
        "run_time": parse_run_time(run_time).isoformat(),
        "forecast_hour": int(forecast_hour),
        "created_at": _now(),
        "compute_ms": compute_ms,
        "result": result,
    }
    _safe_write_json(path, payload)
    return path


def _load_state_locked() -> None:
    global _last_loaded, _jobs, _current_job_id
    if _last_loaded:
        return
    ensure_dirs()
    PRECOMPUTE_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    state_changed = False
    if STATE_PATH.exists():
        try:
            state = _safe_read_json(STATE_PATH)
            _jobs = {str(item["job_id"]): item for item in state.get("jobs", []) if item.get("job_id")}
            interrupted_at = _now()
            for job in _jobs.values():
                if job.get("status") not in {"queued", "running"}:
                    continue
                job.update(
                    {
                        "status": "interrupted",
                        "completed_at": interrupted_at,
                        "updated_at": interrupted_at,
                    }
                )
                state_changed = True
            _current_job_id = None
        except Exception:
            _jobs = {}
            _current_job_id = None
    _last_loaded = True
    if state_changed:
        _persist_state_locked()


def _persist_state_locked() -> None:
    PRECOMPUTE_DIR.mkdir(parents=True, exist_ok=True)
    _safe_write_json(
        STATE_PATH,
        {
            "version": STATE_VERSION,
            "updated_at": _now(),
            "current_job_id": _current_job_id,
            "jobs": list(_jobs.values())[-50:],
        },
    )


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    total = int(job.get("total_count") or 0)
    completed = int(job.get("completed_count") or 0)
    failed = int(job.get("failed_count") or 0)
    return {
        **job,
        "progress": round((completed + failed) / total, 3) if total else 0.0,
    }


def precompute_status() -> dict[str, Any]:
    with _lock:
        _load_state_locked()
        jobs = [_job_summary(job) for job in sorted(_jobs.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)]
        latest = jobs[0] if jobs else None
        return {
            "version": STATE_VERSION,
            "status": "running" if _active_job_ids else (latest.get("status") if latest else "idle"),
            "current_job_id": _current_job_id,
            "active_job_ids": sorted(_active_job_ids),
            "queued_job_count": _job_queue.qsize(),
            "latest_job": latest,
            "jobs": jobs[1:6],
            "result_file_count": len(list(RESULT_DIR.glob("**/*.json"))) if RESULT_DIR.exists() else 0,
            "worker": nafp_process_status(),
        }


def _update_job(job_id: str, **updates: Any) -> None:
    with _lock:
        _load_state_locked()
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = _now()
        _persist_state_locked()


def _append_job_entry(job_id: str, entry: dict[str, Any] | None = None, failed: dict[str, Any] | None = None) -> None:
    with _lock:
        _load_state_locked()
        job = _jobs.get(job_id)
        if not job:
            return
        if entry is not None:
            job.setdefault("entries", []).append(entry)
            job["completed_count"] = int(job.get("completed_count") or 0) + 1
            if entry.get("cache_status") in {"computed", "refreshed"}:
                job["computed_count"] = int(job.get("computed_count") or 0) + 1
            if entry.get("cache_status") in {"hit", "precomputed", "waited"}:
                job["hit_count"] = int(job.get("hit_count") or 0) + 1
        if failed is not None:
            job.setdefault("failed", []).append(failed)
            job["failed_count"] = int(job.get("failed_count") or 0) + 1
        job["updated_at"] = _now()
        _persist_state_locked()


def _finish_flight(job_id: str, key: tuple[str, str, str, int]) -> None:
    with _lock:
        flight = _active_flights.get(key)
        if flight is None or flight[0] != job_id:
            return
        _active_flights.pop(key, None)
        flight[1].set()


def _run_job(job_id: str, compute: Callable[..., dict[str, Any]] | None = None) -> None:
    global _current_job_id
    compute = compute or diagnose_nafp_situation_isolated
    with _lock:
        _load_state_locked()
        job = _jobs.get(job_id)
        if not job:
            return
        _current_job_id = job_id
        job.update({"status": "running", "started_at": _now(), "updated_at": _now()})
        _persist_state_locked()

    root = Path(str(job["root"]))
    data_code = job.get("data_code")
    run_time = str(job["run_time"])
    force = bool(job.get("force"))
    for hour in list(job.get("forecast_hours") or []):
        hour = int(hour)
        key = _work_key(root, run_time, hour, data_code)
        try:
            path = result_path(root, run_time, hour, data_code)
            start = perf_counter()
            if path.exists() and not force:
                result = load_precomputed_result(root, run_time, hour, data_code)
                cache_status = "precomputed"
                compute_ms = 0.0
            else:
                result, cache_meta = get_or_compute_nafp_situation(
                    root=root,
                    run_time=run_time,
                    forecast_hour=hour,
                    compute=compute,
                    force=force,
                )
                compute_ms = float(cache_meta.get("compute_ms") or ((perf_counter() - start) * 1000))
                cache_status = str(cache_meta.get("cache_status") or ("refreshed" if force else "computed"))
                store_precomputed_result(root, run_time, hour, result, data_code=data_code, compute_ms=compute_ms)
            _append_job_entry(
                job_id,
                entry={
                    "forecast_hour": hour,
                    "cache_status": cache_status,
                    "compute_ms": round(compute_ms, 1),
                    "result_path": str(path),
                    "system_count": len(result.get("systems") or []),
                    "risk_count": len(result.get("risk_diagnoses") or []),
                },
            )
        except Exception as exc:
            _append_job_entry(
                job_id,
                failed={"forecast_hour": hour, "error": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            _finish_flight(job_id, key)

    with _lock:
        _load_state_locked()
        job = _jobs.get(job_id)
        if job:
            failed_count = int(job.get("failed_count") or 0)
            total = int(job.get("total_count") or 0)
            job.update({
                "status": "failed" if failed_count and failed_count >= total else "completed",
                "completed_at": _now(),
                "updated_at": _now(),
            })
        if _current_job_id == job_id:
            _current_job_id = None
        _active_job_ids.discard(job_id)
        _persist_state_locked()


def _worker_loop() -> None:
    while True:
        job_id = _job_queue.get()
        try:
            _run_job(job_id)
        finally:
            _job_queue.task_done()


def _ensure_worker_locked() -> None:
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="nafp-precompute-worker",
        daemon=True,
    )
    _worker_thread.start()


def _completed_precompute_summary(
    *,
    root: Path,
    run_time: str,
    forecast_hours: list[int],
    data_code: str | None,
) -> dict[str, Any]:
    return {
        "job_id": None,
        "data_code": data_code,
        "root": str(root),
        "run_time": run_time,
        "forecast_hours": forecast_hours,
        "force": False,
        "status": "completed",
        "created_at": _now(),
        "updated_at": _now(),
        "started_at": None,
        "completed_at": _now(),
        "total_count": len(forecast_hours),
        "completed_count": len(forecast_hours),
        "failed_count": 0,
        "computed_count": 0,
        "hit_count": len(forecast_hours),
        "entries": [],
        "failed": [],
        "progress": 1.0,
        "deduplicated": True,
        "ready_forecast_hours": forecast_hours,
        "execution_mode": "isolated_process",
    }


def submit_precompute_job(
    *,
    root: str | Path,
    run_time: str | datetime,
    forecast_hours: list[int],
    data_code: str | None = None,
    force: bool = False,
    background: bool = True,
) -> dict[str, Any]:
    hours = sorted({int(hour) for hour in forecast_hours})
    root_path = Path(root).resolve()
    normalized_run_time = parse_run_time(run_time).isoformat()
    if not hours:
        raise ValueError("forecast_hours is required")

    with _lock:
        _load_state_locked()
        ready_hours: list[int] = []
        active_hours: list[int] = []
        missing_hours: list[int] = []
        active_job_ids: list[str] = []
        for hour in hours:
            key = _work_key(root_path, normalized_run_time, hour, data_code)
            active = _active_flights.get(key)
            if active is not None:
                active_hours.append(hour)
                active_job_ids.append(active[0])
            elif not force and precomputed_result_exists(root_path, normalized_run_time, hour, data_code):
                ready_hours.append(hour)
            else:
                missing_hours.append(hour)

        if not missing_hours:
            if active_job_ids:
                existing_job = _jobs[active_job_ids[0]]
                return {
                    **_job_summary(existing_job),
                    "deduplicated": True,
                    "active_forecast_hours": active_hours,
                    "ready_forecast_hours": ready_hours,
                }
            return _completed_precompute_summary(
                root=root_path,
                run_time=normalized_run_time,
                forecast_hours=hours,
                data_code=data_code,
            )
        job_id = uuid.uuid4().hex[:16]
        job = {
            "job_id": job_id,
            "data_code": data_code,
            "root": str(root_path),
            "run_time": normalized_run_time,
            "forecast_hours": missing_hours,
            "requested_forecast_hours": hours,
            "deduplicated_forecast_hours": active_hours,
            "ready_forecast_hours": ready_hours,
            "force": bool(force),
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
            "started_at": None,
            "completed_at": None,
            "total_count": len(missing_hours),
            "completed_count": 0,
            "failed_count": 0,
            "computed_count": 0,
            "hit_count": 0,
            "entries": [],
            "failed": [],
            "execution_mode": "isolated_process",
        }
        _jobs[job_id] = job
        _active_job_ids.add(job_id)
        for hour in missing_hours:
            _active_flights[_work_key(root_path, normalized_run_time, hour, data_code)] = (
                job_id,
                threading.Event(),
            )
        _persist_state_locked()
    if background:
        with _lock:
            _ensure_worker_locked()
        _job_queue.put(job_id)
    else:
        _run_job(job_id)
    return _job_summary(_jobs[job_id])


def wait_for_precomputed_result(
    root: str | Path,
    run_time: str | datetime,
    forecast_hour: int,
    data_code: str | None = None,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        return load_precomputed_result(root, run_time, forecast_hour, data_code)
    except FileNotFoundError:
        pass

    submit_precompute_job(
        root=root,
        run_time=run_time,
        forecast_hours=[int(forecast_hour)],
        data_code=data_code,
        force=False,
        background=True,
    )
    key = _work_key(root, run_time, forecast_hour, data_code)
    with _lock:
        flight = _active_flights.get(key)

    if flight is not None:
        wait_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(os.getenv("WEATHER_DIAG_PRECOMPUTE_WAIT_SECONDS", "300"))
        )
        if not flight[1].wait(max(0.1, wait_timeout)):
            raise TimeoutError(
                f"timed out waiting for NAFP precompute: run_time={key[2]} forecast_hour={key[3]}"
            )

    try:
        return load_precomputed_result(root, run_time, forecast_hour, data_code)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"NAFP precompute completed without a result: run_time={key[2]} forecast_hour={key[3]}"
        ) from exc


def schedule_single_if_missing(*, root: str | Path, run_time: str | datetime, forecast_hour: int, data_code: str | None = None) -> dict[str, Any] | None:
    if precomputed_result_exists(root, run_time, forecast_hour, data_code):
        return None
    return submit_precompute_job(root=root, run_time=run_time, forecast_hours=[int(forecast_hour)], data_code=data_code, force=False, background=True)


def autostart_precompute_for_latest(data_sources: dict[str, Any]) -> dict[str, Any] | None:
    if str(os.getenv("WEATHER_DIAG_AUTO_PRECOMPUTE", "1")).lower() in {"0", "false", "no"}:
        return None
    try:
        from backend.app.services.data_sources import discover_nafp_run_inventory, resolve_data_root

        code = data_sources.get("default_code")
        source = next((item for item in data_sources.get("items") or [] if item.get("code") == code), None)
        if not source:
            return None
        inventory = discover_nafp_run_inventory(data_code=code, max_run_times=1)
        latest = (inventory.get("run_times") or [None])[0]
        if not latest:
            return None
        hours = [int(hour) for hour in latest.get("forecast_hours") or source.get("forecast_hours") or []]
        if not hours:
            return None
        max_hours = max(1, int(os.getenv("WEATHER_DIAG_PRECOMPUTE_MAX_HOURS", "1")))
        preferred_hour = int(os.getenv("WEATHER_DIAG_PRECOMPUTE_DEFAULT_HOUR", "24"))
        if preferred_hour in hours:
            hours = [preferred_hour, *[hour for hour in hours if hour != preferred_hour]]
        hours = hours[:max_hours]
        return submit_precompute_job(
            root=resolve_data_root(code),
            run_time=latest["run_time"],
            forecast_hours=hours,
            data_code=code,
            force=False,
            background=True,
        )
    except Exception:
        return None
