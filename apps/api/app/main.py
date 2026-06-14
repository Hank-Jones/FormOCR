import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.session import SessionLocal, init_db
from app.services.settings_load import apply_db_settings
from app.routers import export, form_types, forms, health, process, settings_router, templates
from app.services.ai_correct import check_ollama
from app.services.ocr import (
    ensure_qwen_session_ready,
    set_qwen_warm_in_progress,
    uses_qwen_only,
    warm_ocr,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("formocr")


async def _warm_services_background() -> None:
    loop = asyncio.get_running_loop()
    if uses_qwen_only():
        set_qwen_warm_in_progress(True)
        try:
            ok, msg = await loop.run_in_executor(None, ensure_qwen_session_ready)
        finally:
            set_qwen_warm_in_progress(False)
        logger.info("Qwen vision warm at startup: ok=%s — %s", ok, msg)
        if not ok:
            logger.warning(
                "Qwen not ready at startup (%s). Processing may retry.",
                msg,
            )
        return

    await loop.run_in_executor(None, warm_ocr)
    ollama_ok, model_ok = await check_ollama()
    from app.services.ocr import is_ocr_ready

    logger.info(
        "Background warm — OCR: %s | Ollama: %s | Model %s: %s",
        is_ocr_ready(),
        ollama_ok,
        settings.ollama_model,
        model_ok,
    )
    if not ollama_ok:
        logger.warning(
            "Ollama not reachable at %s",
            settings.ollama_host,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    db = SessionLocal()
    try:
        apply_db_settings(db)
    finally:
        db.close()
    logger.info("FormOCR API — data: %s", settings.data_dir)
    if uses_qwen_only():
        logger.info(
            "OCR engine=%s | lang=%s | vision model=%s",
            settings.ocr_engine,
            settings.ocr_lang,
            settings.handwriting_ocr_model,
        )
    else:
        logger.info("PaddleOCR home: %s", settings.paddle_home)
        logger.info(
            "OCR engine=%s | lang=%s | model=%s | AI correction=%s",
            settings.ocr_engine,
            settings.ocr_lang,
            settings.handwriting_ocr_model,
            settings.ai_correction_enabled,
        )
    asyncio.create_task(_warm_services_background())
    yield
    logger.info("FormOCR API shutting down")


app = FastAPI(title="FormOCR API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(form_types.router)
app.include_router(templates.router)
app.include_router(forms.router)
app.include_router(process.router)
app.include_router(export.router)
app.include_router(settings_router.router)


def run():
    import sys

    import uvicorn

    port = int(os.environ.get("FORMOCR_PORT", settings.port))
    # PyInstaller: import-by-string often fails; pass the app object directly.
    if getattr(sys, "frozen", False):
        uvicorn.run(app, host=settings.host, port=port, reload=False)
    else:
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=port,
            reload=False,
        )


if __name__ == "__main__":
    run()
