from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.responses import ApiError, ok
from weather_diag.config import PROJECT_ROOT
from weather_diag.diagnosis.sounding_preprocess import (
    discover_sounding_csvs,
    load_preprocess_report,
    preprocess_status,
    run_preprocess,
)


router = APIRouter(prefix="/sounding/preprocess", tags=["public-sounding-preprocess"])


class SoundingPreprocessRequest(BaseModel):
    csv_path: str | None = None
    root: str | None = None
    force: bool = False


def _resolve_optional_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(PROJECT_ROOT / path)


@router.get("/status")
def get_sounding_preprocess_status(root: str | None = None):
    return ok(preprocess_status(_resolve_optional_path(root)))


@router.post("/run")
def run_sounding_preprocess(request: SoundingPreprocessRequest):
    payload = run_preprocess(
        csv_path=_resolve_optional_path(request.csv_path),
        root=_resolve_optional_path(request.root),
        force=bool(request.force),
    )
    if payload["failed_count"] and not payload["processed_count"]:
        raise ApiError(40007, "sounding preprocess failed", status_code=400, data=payload)
    return ok(payload)


@router.get("/report")
def get_sounding_preprocess_report(csv_path: str):
    try:
        return ok(load_preprocess_report(_resolve_optional_path(csv_path) or csv_path))
    except FileNotFoundError as exc:
        raise ApiError(40409, "sounding preprocess report not found", status_code=404, data={"csv_path": csv_path}) from exc


@router.get("/files")
def get_sounding_preprocess_files(root: str | None = None):
    files = discover_sounding_csvs(_resolve_optional_path(root))
    return ok({"items": [str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path) for path in files]})
