from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AppSettings
from app.db.session import get_db
from app.services.history_clear import CLEAR_HISTORY_FORBIDDEN, clear_processing_history
from app.services.ocr import reset_ocr

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    ai_correction_enabled: bool
    ocr_lang: str
    handwriting_ocr_enabled: bool
    handwriting_ocr_model: str


class SettingsUpdate(BaseModel):
    ai_correction_enabled: bool | None = None
    ocr_lang: str | None = None
    handwriting_ocr_enabled: bool | None = None
    handwriting_ocr_model: str | None = None


class ClearHistoryRequest(BaseModel):
    confirm: bool = Field(..., description="Must be true to delete processing history")
    force: bool = Field(
        default=False,
        description="Mark stale running jobs failed, then clear if none still active",
    )


class ClearHistoryOut(BaseModel):
    forms_deleted: int
    jobs_deleted: int
    corrections_deleted: int
    files_deleted: int
    stale_jobs_marked: int = 0


def _get_setting(db: Session, key: str, default: str) -> str:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    ai = _get_setting(db, "ai_correction_enabled", str(settings.ai_correction_enabled))
    ocr_lang = _get_setting(db, "ocr_lang", settings.ocr_lang)
    hw_enabled = _get_setting(
        db, "handwriting_ocr_enabled", str(settings.handwriting_ocr_enabled)
    )
    hw_model = _get_setting(db, "handwriting_ocr_model", settings.handwriting_ocr_model)
    return SettingsOut(
        ai_correction_enabled=ai.lower() == "true",
        ocr_lang=ocr_lang,
        handwriting_ocr_enabled=hw_enabled.lower() == "true",
        handwriting_ocr_model=hw_model,
    )


@router.patch("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    if body.ai_correction_enabled is not None:
        settings.ai_correction_enabled = body.ai_correction_enabled
        _set_setting(db, "ai_correction_enabled", str(body.ai_correction_enabled))
    if body.handwriting_ocr_enabled is not None:
        settings.handwriting_ocr_enabled = body.handwriting_ocr_enabled
        _set_setting(db, "handwriting_ocr_enabled", str(body.handwriting_ocr_enabled))
    if body.handwriting_ocr_model is not None:
        settings.handwriting_ocr_model = body.handwriting_ocr_model.strip()
        _set_setting(db, "handwriting_ocr_model", settings.handwriting_ocr_model)
    if body.ocr_lang is not None:
        lang = body.ocr_lang.strip().lower()
        if lang in ("ch", "en"):
            settings.ocr_lang = lang
            _set_setting(db, "ocr_lang", lang)
            reset_ocr()
    return get_settings(db)


@router.post("/clear-history", response_model=ClearHistoryOut)
def clear_history(body: ClearHistoryRequest, db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "confirm must be true")
    try:
        stats = clear_processing_history(db, force=body.force)
    except ValueError as e:
        if str(e) == CLEAR_HISTORY_FORBIDDEN:
            raise HTTPException(409, CLEAR_HISTORY_FORBIDDEN) from e
        raise
    return ClearHistoryOut(**stats)
