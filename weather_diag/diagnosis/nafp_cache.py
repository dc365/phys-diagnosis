from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import perf_counter, time
from typing import Any, Callable

from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis.nafp_situation_integrated import extend_nafp_situation_result


MAX_NAFP_SITUATION_CACHE_SIZE = 128


@dataclass(frozen=True)
class NafpSituationCacheKey:
    root: str
    run_time: str
    forecast_hour: int


@dataclass
class NafpSituationCacheEntry:
    result: dict[str, Any]
    created_at: float
    compute_ms: float
    hit_count: int = 0


_cache: OrderedDict[NafpSituationCacheKey, NafpSituationCacheEntry] = OrderedDict()
_lock = RLock()


def nafp_situation_cache_key(
    root: str | Path,
    run_time: str,
    forecast_hour: int,
) -> NafpSituationCacheKey:
    return NafpSituationCacheKey(
        root=str(Path(root).resolve()),
        run_time=parse_run_time(run_time).isoformat(),
        forecast_hour=int(forecast_hour),
    )


def clear_nafp_situation_cache() -> None:
    with _lock:
        _cache.clear()


def nafp_situation_cache_info() -> dict[str, Any]:
    with _lock:
        return {
            "size": len(_cache),
            "max_size": MAX_NAFP_SITUATION_CACHE_SIZE,
            "keys": [
                {
                    "root": key.root,
                    "run_time": key.run_time,
                    "forecast_hour": key.forecast_hour,
                    "hit_count": entry.hit_count,
                    "compute_ms": round(entry.compute_ms, 1),
                }
                for key, entry in _cache.items()
            ],
        }


def _store_cache_entry(
    key: NafpSituationCacheKey,
    result: dict[str, Any],
    compute_ms: float,
) -> NafpSituationCacheEntry:
    entry = NafpSituationCacheEntry(
        result=result,
        created_at=time(),
        compute_ms=compute_ms,
    )
    _cache[key] = entry
    _cache.move_to_end(key)
    while len(_cache) > MAX_NAFP_SITUATION_CACHE_SIZE:
        _cache.popitem(last=False)
    return entry


def _extend_result_safely(
    result: dict[str, Any],
    key: NafpSituationCacheKey,
) -> dict[str, Any]:
    try:
        return extend_nafp_situation_result(
            result,
            root=Path(key.root),
            run_time=key.run_time,
            forecast_hour=key.forecast_hour,
        )
    except Exception as exc:
        result.setdefault("weather_system_integration", {})["error"] = str(exc)
        return result


def get_or_compute_nafp_situation(
    *,
    root: str | Path,
    run_time: str,
    forecast_hour: int,
    compute: Callable[..., dict[str, Any]],
    force: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = nafp_situation_cache_key(root, run_time, forecast_hour)
    with _lock:
        entry = _cache.get(key)
        if entry is not None and not force:
            entry.hit_count += 1
            entry.result = _extend_result_safely(entry.result, key)
            _cache.move_to_end(key)
            return entry.result, {
                "cache_status": "hit",
                "compute_ms": round(entry.compute_ms, 1),
                "hit_count": entry.hit_count,
            }

    start = perf_counter()
    result = compute(
        root=Path(key.root),
        run_time=key.run_time,
        forecast_hour=key.forecast_hour,
    )
    result = _extend_result_safely(result, key)
    compute_ms = (perf_counter() - start) * 1000

    with _lock:
        entry = _store_cache_entry(key, result, compute_ms)
        return entry.result, {
            "cache_status": "refreshed" if force else "computed",
            "compute_ms": round(compute_ms, 1),
            "hit_count": entry.hit_count,
        }
