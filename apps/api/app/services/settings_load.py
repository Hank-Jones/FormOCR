"""Apply persisted AppSettings rows into the in-process Settings singleton."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AppSettings
from app.services.ocr import uses_qwen_only


def _bool_val(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def apply_db_settings(db: Session) -> None:
    rows = db.query(AppSettings).all()
    by_key = {r.key: r.value for r in rows}
    if "ocr_lang" in by_key:
        lang = by_key["ocr_lang"].strip().lower()
        if lang in ("ch", "en", "ko"):
            settings.ocr_lang = lang
    if "handwriting_ocr_enabled" in by_key:
        settings.handwriting_ocr_enabled = _bool_val(by_key["handwriting_ocr_enabled"])
    if "handwriting_ocr_model" in by_key:
        m = by_key["handwriting_ocr_model"].strip()
        if m:
            settings.handwriting_ocr_model = m
    if "ocr_engine" in by_key:
        eng = by_key["ocr_engine"].strip().lower()
        if eng in ("qwen", "hybrid"):
            settings.ocr_engine = eng
    if "handwriting_ocr_timeout_s" in by_key:
        try:
            settings.handwriting_ocr_timeout_s = float(by_key["handwriting_ocr_timeout_s"])
        except ValueError:
            pass
    if "ai_correction_enabled" in by_key:
        settings.ai_correction_enabled = _bool_val(by_key["ai_correction_enabled"])
    if "ollama_model" in by_key and not uses_qwen_only():
        m = by_key["ollama_model"].strip()
        if m:
            settings.ollama_model = m
