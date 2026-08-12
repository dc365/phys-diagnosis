from __future__ import annotations

import multiprocessing
import os
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class NafpWorkerError(RuntimeError):
    """An isolated NAFP worker failed without taking the API process down."""

    def __init__(
        self,
        message: str,
        *,
        action: str,
        exit_code: int | None = None,
        remote_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.exit_code = exit_code
        self.remote_type = remote_type


@dataclass
class _LayerFlight:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None


_process_gate = threading.BoundedSemaphore(
    max(1, int(os.getenv("WEATHER_DIAG_NAFP_MAX_WORKERS", "1")))
)
_status_lock = threading.RLock()
_active_worker_pids: set[int] = set()
_worker_started_count = 0
_worker_failure_count = 0
_last_worker_error: str | None = None

_layer_lock = threading.RLock()
_layer_cache: OrderedDict[tuple[str, str, str, str, int], tuple[float, dict[str, Any]]] = OrderedDict()
_layer_flights: dict[tuple[str, str, str, str, int], _LayerFlight] = {}


def _worker_main(action: str, payload: dict[str, Any], reply) -> None:
    try:
        if action == "probe":
            if payload.get("crash"):
                os._exit(139)
            result = {
                "worker_pid": os.getpid(),
                "parent_pid": int(payload["parent_pid"]),
            }
        elif action == "layer":
            from weather_diag.diagnosis.nafp_layers import load_nafp_layer

            result = load_nafp_layer(**payload)
        elif action == "situation":
            from weather_diag.diagnosis.nafp_situation import diagnose_nafp_situation

            result = diagnose_nafp_situation(**payload)
        elif action == "point":
            from weather_diag.diagnosis.point import diagnose_nafp_point

            result = diagnose_nafp_point(**payload)
        elif action == "area_risks":
            from weather_diag.diagnosis.area_risk import evaluate_area_risks

            result = evaluate_area_risks(**payload)
        else:
            raise ValueError(f"unsupported NAFP worker action: {action}")
        reply.send({"ok": True, "result": result})
    except BaseException as exc:
        try:
            reply.send(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "traceback": traceback.format_exc(limit=30),
                }
            )
        except BaseException:
            pass
    finally:
        reply.close()


def _record_worker_started(pid: int) -> None:
    global _worker_started_count
    with _status_lock:
        _worker_started_count += 1
        _active_worker_pids.add(int(pid))


def _record_worker_finished(pid: int, error: str | None = None) -> None:
    global _worker_failure_count, _last_worker_error
    with _status_lock:
        _active_worker_pids.discard(int(pid))
        if error:
            _worker_failure_count += 1
            _last_worker_error = error


def _remote_exception(action: str, message: dict[str, Any]) -> BaseException:
    error_type = str(message.get("error_type") or "RuntimeError")
    error = str(message.get("error") or f"{action} failed")
    if error_type == "FileNotFoundError":
        return FileNotFoundError(error)
    if error_type == "KeyError":
        return KeyError(error)
    if error_type == "ValueError":
        return ValueError(error)
    if error_type == "TimeoutError":
        return TimeoutError(error)
    details = f"{action} worker failed: {error}"
    remote_traceback = str(message.get("traceback") or "").strip()
    if remote_traceback:
        details = f"{details}\n{remote_traceback}"
    return NafpWorkerError(details, action=action, remote_type=error_type)


def _run_isolated(
    action: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float | None = None,
) -> Any:
    timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else float(os.getenv("WEATHER_DIAG_NAFP_WORKER_TIMEOUT_SECONDS", "300"))
    )
    context = multiprocessing.get_context("spawn")
    with _process_gate:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker_main,
            args=(action, payload, sender),
            name=f"nafp-{action}-worker",
            daemon=False,
        )
        process.start()
        sender.close()
        _record_worker_started(process.pid)
        message: dict[str, Any] | None = None
        deadline = time.monotonic() + max(0.1, timeout)
        timed_out = False
        try:
            while time.monotonic() < deadline:
                if receiver.poll(0.1):
                    try:
                        message = receiver.recv()
                    except EOFError:
                        message = None
                    break
                if not process.is_alive():
                    break
            else:
                timed_out = True

            if timed_out and process.is_alive():
                process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(2)

            if timed_out:
                error = f"{action} worker timed out after {timeout:.1f}s"
                _record_worker_finished(process.pid, error)
                raise NafpWorkerError(
                    error,
                    action=action,
                    exit_code=process.exitcode,
                )
            if message is None:
                error = f"{action} worker exited without a result (exit code {process.exitcode})"
                _record_worker_finished(process.pid, error)
                raise NafpWorkerError(
                    error,
                    action=action,
                    exit_code=process.exitcode,
                )
            if not message.get("ok"):
                remote_error = _remote_exception(action, message)
                _record_worker_finished(process.pid, str(remote_error))
                raise remote_error
            _record_worker_finished(process.pid)
            return message["result"]
        finally:
            receiver.close()
            with _status_lock:
                _active_worker_pids.discard(int(process.pid))


def probe_nafp_process(*, crash: bool = False) -> dict[str, int]:
    return _run_isolated(
        "probe",
        {"parent_pid": os.getpid(), "crash": bool(crash)},
        timeout_seconds=15,
    )


def diagnose_nafp_situation_isolated(
    *,
    root: str | Path,
    run_time: str,
    forecast_hour: int,
) -> dict[str, Any]:
    return _run_isolated(
        "situation",
        {
            "root": str(Path(root).resolve()),
            "run_time": run_time,
            "forecast_hour": int(forecast_hour),
        },
    )


def diagnose_nafp_point_isolated(
    *,
    root: str | Path,
    run_time: str,
    forecast_hour: int,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    return _run_isolated(
        "point",
        {
            "root": str(Path(root).resolve()),
            "run_time": run_time,
            "forecast_hour": int(forecast_hour),
            "lat": float(lat),
            "lon": float(lon),
        },
    )


def evaluate_nafp_area_risks_isolated(
    *,
    root: str | Path,
    run_time: str,
    forecast_hours: list[int],
    towns: list[Any],
    risk_types: list[str] | None = None,
    include_evidence: bool = True,
    include_samples: bool = False,
) -> dict[str, Any]:
    return _run_isolated(
        "area_risks",
        {
            "root": str(Path(root).resolve()),
            "run_time": run_time,
            "forecast_hours": [int(hour) for hour in forecast_hours],
            "towns": towns,
            "risk_types": risk_types,
            "include_evidence": bool(include_evidence),
            "include_samples": bool(include_samples),
        },
    )


def _layer_key(
    layer_id: str,
    data_code: str | None,
    root: str | Path | None,
    run_time: str,
    forecast_hour: int,
) -> tuple[str, str, str, str, int]:
    root_key = str(Path(root).resolve()) if root is not None else ""
    return (
        str(layer_id),
        str(data_code or ""),
        root_key,
        str(run_time),
        int(forecast_hour),
    )


def _prune_layer_cache_locked(now: float) -> None:
    expired = [key for key, (expires_at, _) in _layer_cache.items() if expires_at <= now]
    for key in expired:
        _layer_cache.pop(key, None)
    max_entries = max(1, int(os.getenv("WEATHER_DIAG_NAFP_LAYER_CACHE_SIZE", "16")))
    while len(_layer_cache) > max_entries:
        _layer_cache.popitem(last=False)


def clear_nafp_layer_cache() -> None:
    with _layer_lock:
        _layer_cache.clear()
        _layer_flights.clear()


def load_nafp_layer_isolated(
    layer_id: str,
    *,
    data_code: str | None = None,
    root: str | Path | None = None,
    run_time: str,
    forecast_hour: int,
) -> dict[str, Any]:
    key = _layer_key(layer_id, data_code, root, run_time, forecast_hour)
    now = time.monotonic()
    with _layer_lock:
        _prune_layer_cache_locked(now)
        cached = _layer_cache.get(key)
        if cached and cached[0] > now:
            _layer_cache.move_to_end(key)
            return cached[1]
        flight = _layer_flights.get(key)
        owner = flight is None
        if owner:
            flight = _LayerFlight()
            _layer_flights[key] = flight

    assert flight is not None
    if not owner:
        wait_seconds = float(os.getenv("WEATHER_DIAG_NAFP_WORKER_TIMEOUT_SECONDS", "300")) + 10.0
        if not flight.event.wait(wait_seconds):
            raise TimeoutError(f"timed out waiting for shared NAFP layer calculation: {layer_id}")
        if flight.error is not None:
            raise flight.error
        assert flight.result is not None
        return flight.result

    try:
        payload = {
            "layer_id": layer_id,
            "data_code": data_code,
            "root": str(Path(root).resolve()) if root is not None else None,
            "run_time": run_time,
            "forecast_hour": int(forecast_hour),
        }
        result = _run_isolated("layer", payload)
        ttl = max(1.0, float(os.getenv("WEATHER_DIAG_NAFP_LAYER_CACHE_TTL_SECONDS", "300")))
        with _layer_lock:
            flight.result = result
            _layer_cache[key] = (time.monotonic() + ttl, result)
            _layer_cache.move_to_end(key)
            _prune_layer_cache_locked(time.monotonic())
        return result
    except BaseException as exc:
        with _layer_lock:
            flight.error = exc
        raise
    finally:
        with _layer_lock:
            _layer_flights.pop(key, None)
            flight.event.set()


def nafp_process_status() -> dict[str, Any]:
    with _status_lock, _layer_lock:
        return {
            "execution_mode": "isolated_process",
            "max_workers": max(1, int(os.getenv("WEATHER_DIAG_NAFP_MAX_WORKERS", "1"))),
            "active_worker_pids": sorted(_active_worker_pids),
            "worker_started_count": _worker_started_count,
            "worker_failure_count": _worker_failure_count,
            "last_worker_error": _last_worker_error,
            "layer_cache_entries": len(_layer_cache),
            "layer_inflight_count": len(_layer_flights),
        }
