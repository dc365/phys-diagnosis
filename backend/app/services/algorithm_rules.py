from __future__ import annotations

from backend.app.responses import ApiError
from weather_diag.diagnosis.algorithm_rules import (
    ThresholdMatrixError,
    catalog_payload as _catalog_payload,
    load_threshold_matrix as _load_threshold_matrix,
    rule_explanations_payload as _rule_explanations_payload,
    save_threshold_matrix as _save_threshold_matrix,
)
from weather_diag.diagnosis.weather_system_governance import (
    EXTRA_THRESHOLD_ENTRY_IDS,
    WeatherSystemGovernanceError,
    augment_catalog_payload,
    augment_rule_explanations_payload,
    default_extra_threshold_entries,
    merge_threshold_matrix,
    save_extra_threshold_entries,
)


def _raise_api_error(exc: ThresholdMatrixError | WeatherSystemGovernanceError) -> None:
    code = 50003 if exc.status_code >= 500 else 40005
    raise ApiError(code, exc.msg, status_code=exc.status_code, data=exc.data) from exc


def _validate_submitted_entry_ids(entries: list[dict], base_ids: set[str]) -> None:
    seen: set[str] = set()
    known_ids = base_ids | set(EXTRA_THRESHOLD_ENTRY_IDS)
    for entry in entries:
        entry_id = str(entry.get("entry_id") or "")
        if not entry_id or entry_id in seen or entry_id not in known_ids:
            raise WeatherSystemGovernanceError(
                "invalid threshold matrix",
                status_code=400,
                data={"field": "entry_id", "entry_id": entry_id},
            )
        seen.add(entry_id)
        weight = entry.get("weight")
        if weight not in {None, ""}:
            try:
                weight_value = float(weight)
            except (TypeError, ValueError) as exc:
                raise WeatherSystemGovernanceError(
                    "invalid threshold matrix",
                    status_code=400,
                    data={"field": "weight", "entry_id": entry_id},
                ) from exc
            if not 0 <= weight_value <= 1:
                raise WeatherSystemGovernanceError(
                    "invalid threshold matrix",
                    status_code=400,
                    data={"field": "weight", "entry_id": entry_id},
                )


def catalog_payload() -> dict:
    try:
        return augment_catalog_payload(_catalog_payload())
    except (ThresholdMatrixError, WeatherSystemGovernanceError) as exc:
        _raise_api_error(exc)


def load_threshold_matrix() -> dict:
    try:
        return merge_threshold_matrix(_load_threshold_matrix())
    except (ThresholdMatrixError, WeatherSystemGovernanceError) as exc:
        _raise_api_error(exc)


def rule_explanations_payload() -> dict:
    try:
        matrix = merge_threshold_matrix(_load_threshold_matrix())
        return augment_rule_explanations_payload(_rule_explanations_payload(), matrix)
    except (ThresholdMatrixError, WeatherSystemGovernanceError) as exc:
        _raise_api_error(exc)


def save_threshold_matrix(payload: dict) -> dict:
    try:
        active_base = _load_threshold_matrix()
        base_entries = list(active_base.get("entries") or [])
        base_ids = {str(entry.get("entry_id") or "") for entry in base_entries}
        submitted_entries = list(payload.get("entries") or [])
        _validate_submitted_entry_ids(submitted_entries, base_ids)
        submitted_by_id = {
            str(entry.get("entry_id") or ""): dict(entry)
            for entry in submitted_entries
        }

        merged_base_entries = [
            submitted_by_id.get(str(entry.get("entry_id") or ""), entry)
            for entry in base_entries
        ]
        extra_defaults = default_extra_threshold_entries()
        merged_extra_entries = [
            submitted_by_id.get(str(entry.get("entry_id") or ""), entry)
            for entry in extra_defaults
        ]
        base_payload = {
            **payload,
            "entries": merged_base_entries,
            "level_thresholds": payload.get("level_thresholds") or active_base.get("level_thresholds") or [],
        }
        saved_base = _save_threshold_matrix(base_payload)
        save_extra_threshold_entries(
            merged_extra_entries,
            updated_by=payload.get("updated_by"),
            remark=payload.get("remark"),
        )

        # Threshold changes must invalidate already enriched situation results;
        # otherwise cache hits would continue using the previous weather-system
        # parameters until process restart.
        from weather_diag.diagnosis.nafp_cache import clear_nafp_situation_cache

        clear_nafp_situation_cache()
        return merge_threshold_matrix(saved_base)
    except (ThresholdMatrixError, WeatherSystemGovernanceError) as exc:
        _raise_api_error(exc)
