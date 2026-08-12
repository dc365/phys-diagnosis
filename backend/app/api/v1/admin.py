from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.responses import ok
from backend.app.services.algorithm_rules import (
    catalog_payload,
    load_threshold_matrix,
    rule_explanations_payload,
    save_threshold_matrix,
)


class ThresholdMatrixUpdate(BaseModel):
    algorithm_id: str
    updated_by: str | None = None
    remark: str | None = None
    entries: list[dict[str, Any]] = Field(default_factory=list)
    level_thresholds: list[dict[str, Any]] = Field(default_factory=list)


router = APIRouter(prefix="/admin/algorithms", tags=["admin-algorithms"])


@router.get("/catalog")
def get_algorithm_catalog():
    return ok(catalog_payload())


@router.get("/threshold-matrix")
def get_threshold_matrix():
    return ok(load_threshold_matrix())


@router.get("/rule-explanations")
def get_rule_explanations():
    return ok(rule_explanations_payload())


@router.put("/threshold-matrix")
def update_threshold_matrix(request: ThresholdMatrixUpdate):
    return ok(save_threshold_matrix(request.model_dump()))
