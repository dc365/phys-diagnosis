from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
from time import perf_counter, time
from typing import Any, Callable

from weather_diag.data.nafp import parse_run_time
from weather_diag.diagnosis import system_links
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


@dataclass
class NafpSituationFlight:
    event: Event
    error: BaseException | None = None


_cache: OrderedDict[NafpSituationCacheKey, NafpSituationCacheEntry] = OrderedDict()
_flights: dict[NafpSituationCacheKey, NafpSituationFlight] = {}
_lock = RLock()


def _patch_support_weights() -> None:
    labels = {
        "shear_line": "切变线",
        "front_with_shear": "锋区切变线",
        "low_level_convergence_axis": "低层辐合轴",
        "upper_divergence_axis": "高空辐散轴",
        "cold_vortex": "冷涡",
        "mid_level_vortex": "低涡",
        "upper_jet": "高空急流",
        "upper_jet_exit_region": "急流出口辐散区",
        "pv_anomaly": "高空PV异常",
        "surface_front_candidate": "地面锋区候选",
        "dryline_candidate": "干线候选",
    }
    system_links.TYPE_LABELS.update(labels)
    system_links.SUPPORT_WEIGHTS.setdefault("heavy_rain_potential", {}).update(
        {
            "shear_line": 0.78,
            "front_with_shear": 0.82,
            "cold_vortex": 0.62,
            "mid_level_vortex": 0.58,
            "upper_jet": 0.68,
            "upper_jet_exit_region": 0.74,
            "pv_anomaly": 0.52,
        }
    )
    system_links.SUPPORT_WEIGHTS.setdefault("convection_potential", {}).update(
        {
            "shear_line": 0.92,
            "front_with_shear": 0.94,
            "cold_vortex": 0.82,
            "mid_level_vortex": 0.72,
            "upper_jet": 0.78,
            "upper_jet_exit_region": 0.82,
            "pv_anomaly": 0.76,
            "surface_front_candidate": 0.78,
            "dryline_candidate": 0.82,
        }
    )
    system_links.SUPPORT_WEIGHTS.setdefault("dynamic_lift_potential", {}).update(
        {
            "shear_line": 0.82,
            "front_with_shear": 0.84,
            "cold_vortex": 0.88,
            "mid_level_vortex": 0.78,
            "upper_jet": 0.82,
            "upper_jet_exit_region": 0.9,
            "pv_anomaly": 0.84,
        }
    )


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
            "inflight_count": len(_flights),
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
        _patch_support_weights()
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
            _cache.move_to_end(key)
            return entry.result, {
                "cache_status": "hit",
                "compute_ms": round(entry.compute_ms, 1),
                "hit_count": entry.hit_count,
            }
        flight = _flights.get(key)
        if flight is None:
            flight = NafpSituationFlight(event=Event())
            _flights[key] = flight
            owns_flight = True
        else:
            owns_flight = False

    if not owns_flight:
        flight.event.wait()
        with _lock:
            if flight.error is not None:
                raise flight.error
            entry = _cache.get(key)
            if entry is None:
                raise RuntimeError(f"NAFP situation flight completed without a cache entry: {key}")
            entry.hit_count += 1
            _cache.move_to_end(key)
            return entry.result, {
                "cache_status": "waited",
                "compute_ms": round(entry.compute_ms, 1),
                "hit_count": entry.hit_count,
            }

    start = perf_counter()
    try:
        result = compute(
            root=Path(key.root),
            run_time=key.run_time,
            forecast_hour=key.forecast_hour,
        )
        result = _extend_result_safely(result, key)
        compute_ms = (perf_counter() - start) * 1000
    except BaseException as exc:
        with _lock:
            flight.error = exc
            _flights.pop(key, None)
            flight.event.set()
        raise

    with _lock:
        entry = _store_cache_entry(key, result, compute_ms)
        _flights.pop(key, None)
        flight.event.set()
        return entry.result, {
            "cache_status": "refreshed" if force else "computed",
            "compute_ms": round(compute_ms, 1),
            "hit_count": entry.hit_count,
        }
