from __future__ import annotations

from fastapi import APIRouter, UploadFile

from backend.app.responses import ok
from backend.app.services.files import load_file, save_upload


router = APIRouter(prefix="/files", tags=["public-files"])


@router.post("/upload")
def upload_file(file: UploadFile):
    record = save_upload(file)
    return ok(record.model_dump())


@router.get("/{file_id}")
def get_file(file_id: str):
    record = load_file(file_id)
    return ok(record.model_dump())
