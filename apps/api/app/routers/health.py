from __future__ import annotations

import asyncio
import time
from pathlib import Path
import sys
from threading import Lock

from fastapi import APIRouter

from app.config import settings
from app.schemas.common import HealthResponse
from app.services.ai_correct import check_ollama, check_ollama_model
from app.services.ocr import (
    is_ocr_ready,
    is_qwen_warm_in_progress,
    ocr_error,
    ollama_gpu_status,
    uses_qwen_only,
)

router = APIRouter(tags=["health"])

_HEALTH_CACHE_TTL_S = 8.0
_health_cache: tuple[float, HealthResponse] | None = None
_health_cache_lock = Lock()


def _api_build_stamp() -> str | None:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        stamp = root / "FORMOCR_API_BUILD.txt"
        if stamp.is_file():
            return stamp.read_text(encoding="ascii").strip()
    return None


@router.get("/health/live", response_model=HealthResponse)
async def health_live():
    """Fast liveness check — used while the desktop app starts (no OCR warm-up)."""
    return HealthResponse(
        status="ok",
        api=True,
        ocr_ready=False,
        ocr_warming=False,
        ollama_ready=False,
        ollama_model_present=False,
        handwriting_ocr_enabled=settings.handwriting_ocr_enabled,
        handwriting_model_present=False,
        handwriting_ollama_model=settings.handwriting_ocr_model,
        data_dir=str(settings.data_dir),
        paddle_models_dir=str(settings.paddle_home),
        ocr_error=None,
        ollama_model=settings.ollama_model,
        ocr_lang=settings.ocr_lang,
        api_build=_api_build_stamp(),
        ollama_host=settings.ollama_host,
    )


def _health_warming_fast() -> HealthResponse:
    """Avoid Ollama HTTP while qwen warmup runs — /api/tags can block 30s+."""
    cached = _cached_health_if_fresh(max_age_s=30.0)
    if cached is not None:
        return cached.model_copy(
            update={
                "ocr_ready": is_ocr_ready(),
                "ocr_warming": not is_ocr_ready(),
                "ocr_error": ocr_error(),
            }
        )
    return HealthResponse(
        status="degraded",
        api=True,
        ocr_ready=is_ocr_ready(),
        ocr_warming=True,
        ollama_ready=False,
        ollama_model_present=False,
        handwriting_ocr_enabled=settings.handwriting_ocr_enabled,
        handwriting_model_present=False,
        handwriting_ollama_model=settings.handwriting_ocr_model,
        data_dir=str(settings.data_dir),
        paddle_models_dir=str(settings.paddle_home),
        ocr_error=ocr_error(),
        ollama_model=settings.ollama_model,
        ocr_lang=settings.ocr_lang,
        api_build=_api_build_stamp(),
        ollama_host=settings.ollama_host,
    )


def _cached_health_if_fresh(*, max_age_s: float) -> HealthResponse | None:
    with _health_cache_lock:
        if _health_cache is None:
            return None
        age = time.monotonic() - _health_cache[0]
        if age <= max_age_s:
            return _health_cache[1]
    return None


def _store_health_cache(resp: HealthResponse) -> None:
    global _health_cache
    with _health_cache_lock:
        _health_cache = (time.monotonic(), resp)


async def _health_compute() -> HealthResponse:
    loop = asyncio.get_running_loop()
    err = ocr_error()
    gpu = await loop.run_in_executor(None, ollama_gpu_status)
    if uses_qwen_only():
        hw_ok, hw_model_ok = await check_ollama_model(settings.handwriting_ocr_model)
        ollama_ok, model_ok = hw_ok, hw_model_ok
        all_ok = is_ocr_ready() and hw_ok and hw_model_ok
    else:
        ollama_ok, model_ok = await check_ollama()
        hw_ok, hw_model_ok = (False, False)
        if settings.handwriting_ocr_enabled:
            hw_ok, hw_model_ok = await check_ollama_model(settings.handwriting_ocr_model)
        all_ok = is_ocr_ready() and ollama_ok and model_ok
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        api=True,
        ocr_ready=is_ocr_ready(),
        ocr_warming=is_qwen_warm_in_progress() and not is_ocr_ready(),
        ollama_ready=ollama_ok,
        ollama_model_present=model_ok if not uses_qwen_only() else hw_model_ok,
        handwriting_ocr_enabled=settings.handwriting_ocr_enabled,
        handwriting_model_present=hw_ok and hw_model_ok,
        handwriting_ollama_model=settings.handwriting_ocr_model,
        data_dir=str(settings.data_dir),
        paddle_models_dir=str(settings.paddle_home),
        ocr_error=err,
        ollama_model=settings.ollama_model,
        ocr_lang=settings.ocr_lang,
        api_build=_api_build_stamp(),
        ollama_host=settings.ollama_host,
        ollama_on_gpu=gpu.get("on_gpu") if gpu.get("loaded") else None,
        ollama_vram_mb=gpu.get("vram_mb") if gpu.get("loaded") else None,
        ollama_gpu_summary=gpu.get("summary") or gpu.get("error"),
    )


@router.get("/health", response_model=HealthResponse)
async def health():
    if is_qwen_warm_in_progress():
        return _health_warming_fast()

    cached = _cached_health_if_fresh(max_age_s=_HEALTH_CACHE_TTL_S)
    if cached is not None:
        return cached.model_copy(
            update={
                "ocr_ready": is_ocr_ready(),
                "ocr_warming": is_qwen_warm_in_progress() and not is_ocr_ready(),
                "ocr_error": ocr_error(),
            }
        )

    resp = await _health_compute()
    _store_health_cache(resp)
    return resp
