from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from weather_diag.config import ADMIN_DIR, ensure_dirs
from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.nafp_cache import get_or_compute_nafp_situation
from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation


PRECOMPUTE_DIR = ADMIN_DIR / "nafp_precompute"
RESULT_DIR = PRECOMPUTE_DIR / "results"
STATE_PATH = PRECOMPUTE_DIR / "state.json"
STATE_VERSION = "nafp-precompute-v1"

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_current_job_id: str | None = None
_last_loaded = False


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
    if STATE_PATH.exists():
        try:
            state = _safe_read_json(STATE_PATH)
            _jobs = {str(item["job_id"]): item for item in state.get("jobs", []) if item.get("job_id")}
            _current_job_id = state.get("current_job_id")
        except Exception:
            _jobs = {}
            _current_job_id = None
    _last_loaded = True


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
            "status": latest.get("status") if latest else "idle",
            "current_job_id": _current_job_id,
            "latest_job": latest,
            "jobs": jobs[:20],
            "result_file_count": len(list(RESULT_DIR.glob("**/*.json"))) if RESULT_DIR.exists() else 0,
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
            if entry.get("cache_status") in {"hit", "precomputed"}:
                job["hit_count"] = int(job.get("hit_count") or 0) + 1
        if failed is not None:
            job.setdefault("failed", []).append(failed)
            job["failed_count"] = int(job.get("failed_count") or 0) + 1
        job["updated_at"] = _now()
        _persist_state_locked()


def _run_job(job_id: str, compute: Callable[..., dict[str, Any]] = diagnose_nafp_situation) -> None:
    global _current_job_id
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
        _persist_state_locked()


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
    job_id = uuid.uuid4().hex[:16]
    job = {
        "job_id": job_id,
        "data_code": data_code,
        "root": str(Path(root).resolve()),
        "run_time": parse_run_time(run_time).isoformat(),
        "forecast_hours": hours,
        "force": bool(force),
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "started_at": None,
        "completed_at": None,
        "total_count": len(hours),
        "completed_count": 0,
        "failed_count": 0,
        "computed_count": 0,
        "hit_count": 0,
        "entries": [],
        "failed": [],
    }
    with _lock:
        _load_state_locked()
        _jobs[job_id] = job
        _persist_state_locked()
    if background:
        thread = threading.Thread(target=_run_job, args=(job_id,), name=f"nafp-precompute-{job_id}", daemon=True)
        thread.start()
    else:
        _run_job(job_id)
    return _job_summary(job)


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
        max_hours = int(os.getenv("WEATHER_DIAG_PRECOMPUTE_MAX_HOURS", "999"))
        hours = hours[:max(1, max_hours)]
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
