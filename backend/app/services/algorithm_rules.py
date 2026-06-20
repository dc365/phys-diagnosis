from __future__ import annotations

from backend.app.responses import ApiError
from weather_diag.diagnosis.algorithm_rules import (
    ThresholdMatrixError,
    catalog_payload as _catalog_payload,
    load_threshold_matrix as _load_threshold_matrix,
    rule_explanations_payload as _rule_explanations_payload,
    save_threshold_matrix as _save_threshold_matrix,
)


def _raise_api_error(exc: ThresholdMatrixError) -> None:
    code = 50003 if exc.status_code >= 500 else 40005
    raise ApiError(code, exc.msg, status_code=exc.status_code, data=exc.data) from exc


def catalog_payload() -> dict:
    try:
        return _catalog_payload()
    except ThresholdMatrixError as exc:
        _raise_api_error(exc)


def load_threshold_matrix() -> dict:
    try:
        return _load_threshold_matrix()
    except ThresholdMatrixError as exc:
        _raise_api_error(exc)


def rule_explanations_payload() -> dict:
    try:
        return _rule_explanations_payload()
    except ThresholdMatrixError as exc:
        _raise_api_error(exc)


def save_threshold_matrix(payload: dict) -> dict:
    try:
        return _save_threshold_matrix(payload)
    except ThresholdMatrixError as exc:
        _raise_api_error(exc)
