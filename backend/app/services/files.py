from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from backend.app.responses import ApiError
from backend.app.schemas import FileRecord
from weather_diag.config import RAW_DIR, ensure_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata_path(file_id: str) -> Path:
    return RAW_DIR / f"{file_id}.json"


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in {".nc", ".cdf", ".nc4"} else ".nc"


def save_upload(file: UploadFile) -> FileRecord:
    ensure_dirs()
    file_id = uuid4().hex
    stored_path = RAW_DIR / f"{file_id}{_safe_suffix(file.filename)}"
    size = 0
    with stored_path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            out.write(chunk)
    record = FileRecord(
        file_id=file_id,
        original_filename=file.filename or stored_path.name,
        stored_path=str(stored_path),
        size=size,
        created_at=utc_now(),
    )
    _metadata_path(file_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def load_file(file_id: str) -> FileRecord:
    path = _metadata_path(file_id)
    if not path.exists():
        raise ApiError(40403, "file not found", status_code=404)
    return FileRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
