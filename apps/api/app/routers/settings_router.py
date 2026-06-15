from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AppSettings
from app.db.session import get_db
from app.services.history_clear import CLEAR_HISTORY_FORBIDDEN, clear_processing_history
from app.services.ocr import reset_ocr

router = APIRouter(prefix="/settings", tags=["settings"])
_SUPPORTED_OCR_LANGS = {"ch", "en"}


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


def _get_nonempty_setting(db: Session, key: str, default: str) -> str:
    value = _get_setting(db, key, default).strip()
    return value or default


def _normalize_ocr_lang(raw: str) -> str:
    lang = raw.strip().lower()
    return lang if lang in _SUPPORTED_OCR_LANGS else "ch"


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    ai = _get_setting(db, "ai_correction_enabled", str(settings.ai_correction_enabled))
    ocr_lang = _normalize_ocr_lang(_get_setting(db, "ocr_lang", settings.ocr_lang))
    hw_enabled = _get_setting(
        db, "handwriting_ocr_enabled", str(settings.handwriting_ocr_enabled)
    )
    hw_model = _get_nonempty_setting(
        db, "handwriting_ocr_model", settings.handwriting_ocr_model
    )
    return SettingsOut(
        ai_correction_enabled=ai.lower() == "true",
        ocr_lang=ocr_lang,
        handwriting_ocr_enabled=hw_enabled.lower() == "true",
        handwriting_ocr_model=hw_model,
    )


@router.patch("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    current = get_settings(db)
    next_ai = current.ai_correction_enabled
    next_hw_enabled = current.handwriting_ocr_enabled
    next_hw_model = current.handwriting_ocr_model
    next_ocr_lang = current.ocr_lang

    if body.ai_correction_enabled is not None:
        next_ai = body.ai_correction_enabled
    if body.handwriting_ocr_enabled is not None:
        next_hw_enabled = body.handwriting_ocr_enabled
    if body.handwriting_ocr_model is not None:
        next_hw_model = body.handwriting_ocr_model.strip()
        if not next_hw_model:
            raise HTTPException(400, "Handwriting OCR model is required")
    if body.ocr_lang is not None:
        lang = body.ocr_lang.strip().lower()
        if lang not in _SUPPORTED_OCR_LANGS:
            raise HTTPException(400, "Unsupported OCR language")
        next_ocr_lang = lang

    ocr_lang_changed = next_ocr_lang != current.ocr_lang
    _set_setting(db, "ai_correction_enabled", str(next_ai))
    _set_setting(db, "handwriting_ocr_enabled", str(next_hw_enabled))
    _set_setting(db, "handwriting_ocr_model", next_hw_model)
    _set_setting(db, "ocr_lang", next_ocr_lang)
    db.commit()

    settings.ai_correction_enabled = next_ai
    settings.handwriting_ocr_enabled = next_hw_enabled
    settings.handwriting_ocr_model = next_hw_model
    settings.ocr_lang = next_ocr_lang
    if ocr_lang_changed:
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
