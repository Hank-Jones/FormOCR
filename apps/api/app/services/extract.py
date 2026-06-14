from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cv2
import numpy as np

from app.config import settings
from app.schemas.common import FieldExtraction, FieldType, TemplatePayload
from app.services.job_cancel import raise_if_job_cancelled
from app.services.ocr import (
    OcrCropResult,
    ensure_qwen_session_ready,
    extract_fields_qwen_composite,
    is_qwen_session_ready,
    ocr_crop,
    ollama_gpu_status,
    uses_qwen_only,
)
from app.services.progress import (
    append_job_step,
    get_job_progress,
    is_job_cancelled,
    set_job_progress,
    update_job_pipeline,
)
from app.services.preprocess import load_image
from app.services.template_learn import bbox_on_processed_page, denormalize_bbox

_executor = ThreadPoolExecutor(max_workers=4)

_MIN_IMAGE_SIDE = 900


def _ensure_min_resolution(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    side = max(h, w)
    if side >= _MIN_IMAGE_SIDE:
        return image
    scale = _MIN_IMAGE_SIDE / side
    return cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )


def _crop_field(
    image: np.ndarray,
    bbox_norm: list[float],
    *,
    pad_ratio: float = 0.12,
    template: TemplatePayload | None = None,
) -> np.ndarray:
    h, w = image.shape[:2]
    box = bbox_norm
    if template is not None:
        box = bbox_on_processed_page(bbox_norm, template, w, h)
    x, y, bw, bh = denormalize_bbox(box, w, h)
    pad_w = int(bw * pad_ratio)
    pad_h = int(bh * pad_ratio)
    x1 = max(0, x - pad_w)
    y1 = max(0, y - pad_h)
    x2 = min(w, x + bw + pad_w)
    y2 = min(h, y + bh + pad_h)
    if x2 <= x1 or y2 <= y1:
        return np.array([])
    return image[y1:y2, x1:x2]


def _to_field_extraction(crop_result) -> FieldExtraction:
    return FieldExtraction(
        text=crop_result.text,
        confidence=crop_result.confidence,
        engine=crop_result.engine,
        qwen_text=crop_result.qwen_text or None,
        paddle_text=crop_result.paddle_text or None,
        tesseract_text=crop_result.tesseract_text or None,
    )


async def extract_fields_parallel(
    image_path: str,
    template: TemplatePayload,
    processed_path: str | None = None,
    *,
    job_id: int | None = None,
) -> dict[str, FieldExtraction]:
    """Extract all fields — one Qwen page call (fast) or per-field hybrid."""
    raise_if_job_cancelled(job_id)
    path = processed_path or image_path
    raw = load_image(path)
    # Large upscaling helps Paddle; it slows full-page Qwen vision calls.
    image = raw if uses_qwen_only() else _ensure_min_resolution(raw)
    loop = asyncio.get_event_loop()
    fields = list(template.fields.items())
    total = len(fields)
    hw_model = settings.handwriting_ocr_model
    lang = (settings.ocr_lang or "ch").strip().lower()

    if uses_qwen_only():
        raise_if_job_cancelled(job_id)
        already_warm = await loop.run_in_executor(_executor, is_qwen_session_ready)
        if job_id is not None and not already_warm:
            update_job_pipeline(job_id, vision="warming", vlm="idle")
            set_job_progress(
                job_id,
                phase="ocr",
                message=f"Loading {hw_model} (missed startup warm-up)…",
                handwriting_model=hw_model,
                ocr_lang=lang,
            )
        ready, ready_msg = await loop.run_in_executor(
            _executor, ensure_qwen_session_ready
        )
        raise_if_job_cancelled(job_id)
        gpu = await loop.run_in_executor(_executor, ollama_gpu_status)
        if job_id is not None:
            if ready:
                compute = "unknown"
                if gpu.get("loaded"):
                    compute = "gpu" if gpu.get("on_gpu") else "cpu"
                update_job_pipeline(job_id, vision="ready", compute=compute)
            else:
                update_job_pipeline(job_id, vision="error")
                append_job_step(job_id, f"Vision not ready: {ready_msg[:120]}")

        if job_id is not None and total > 0:
            cpu_slow = bool(gpu.get("loaded")) and not bool(gpu.get("on_gpu"))
            batch_hint = " (CPU/RAM — may take 5–25 min, stay on this page)" if cpu_slow else ""
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=0,
                message=f"Reading fields with {hw_model} (batch){batch_hint}…",
                handwriting_model=hw_model,
                ocr_lang=lang,
            )
            update_job_pipeline(job_id, vlm="active")

        def _on_chunk(done: int, chunk_total: int, chunk_len: int) -> None:
            if job_id is None:
                return
            raise_if_job_cancelled(job_id)
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=done,
                ocr_chunk_size=chunk_len,
                ocr_chunk_progress=0.0,
                message=f"Reading fields ({done}/{total})…",
                handwriting_model=hw_model,
                ocr_lang=lang,
            )

        def _on_vlm_pulse(frac: float) -> None:
            if job_id is None:
                return
            progress = get_job_progress(job_id) or {}
            done = int(progress.get("fields_done") or 0)
            chunk_len = int(progress.get("ocr_chunk_size") or 1)
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=done,
                ocr_chunk_size=chunk_len,
                ocr_chunk_progress=frac,
                message=f"Reading fields ({done}/{total})…",
                handwriting_model=hw_model,
                ocr_lang=lang,
            )

        def _batch() -> dict[str, OcrCropResult]:
            return extract_fields_qwen_composite(
                image,
                template,
                on_chunk_done=_on_chunk if job_id else None,
                on_vlm_pulse=_on_vlm_pulse if job_id else None,
                should_cancel=(lambda: is_job_cancelled(job_id)) if job_id else None,
            )

        crop_map = await loop.run_in_executor(_executor, _batch)
        raise_if_job_cancelled(job_id)

        def _field_needs_retry(v: OcrCropResult) -> bool:
            if v.engine != "none":
                return False
            if (v.text or "").strip():
                return False
            err = (v.qwen_error or "").lower()
            return (
                not err
                or "timed out" in err
                or "timeout" in err
                or err == "empty"
                or "batch empty" in err
                or "parse failed" in err
                or "composite batch" in err
            )

        retry_keys = [k for k, v in crop_map.items() if _field_needs_retry(v)]
        if retry_keys:
            if job_id is not None:
                sample = crop_map.get(retry_keys[0])
                err_hint = (sample.qwen_error or "no text")[:90] if sample else ""
                append_job_step(
                    job_id,
                    f"Batch OCR incomplete ({len(retry_keys)} fields): {err_hint}",
                )
                update_job_pipeline(job_id, vlm="active")

            retry_items = [(k, f) for k, f in fields if k in retry_keys]

            def _run_field(item: tuple[str, Any]):
                key, field = item
                pad = 0.28 if field.field_type == FieldType.date else 0.12
                crop = _crop_field(
                    image, field.bbox_norm, pad_ratio=pad, template=template
                )
                is_date = field.field_type == FieldType.date
                return key, ocr_crop(
                    crop,
                    is_date=is_date,
                    line_count=field.line_count,
                    field=field,
                )

            # One Ollama vision request at a time — parallel calls queue and hit read timeouts.
            done = 0
            for item in retry_items:
                raise_if_job_cancelled(job_id)
                key, result = _run_field(item)
                crop_map[key] = result
                done += 1
                if job_id is not None and total > 0:
                    set_job_progress(
                        job_id,
                        phase="ocr",
                        fields_total=total,
                        fields_done=total - len(retry_keys) + done,
                        message=f"Field {key} ({done}/{len(retry_keys)} retry)…",
                        handwriting_model=hw_model,
                        last_field_key=key,
                    )

        results = {k: _to_field_extraction(v) for k, v in crop_map.items()}
        engine_counts: Counter[str] = Counter(fe.engine for fe in results.values())

        if job_id is not None:
            update_job_pipeline(job_id, vlm="done")
            summary = ", ".join(f"{k}={v}" for k, v in sorted(engine_counts.items()))
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=total,
                message=f"OCR finished ({summary})",
                ocr_engine_counts=dict(engine_counts),
            )
        return results

    # Hybrid: per-field Paddle + optional Qwen (legacy)
    results: dict[str, FieldExtraction] = {}
    engine_counts: Counter[str] = Counter()

    if job_id is not None:
        update_job_pipeline(job_id, vision="ready", vlm="active", compute="unknown")
        if total > 0:
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=0,
                message=f"Reading fields (0/{total})…",
                ocr_lang=lang,
            )

    for idx, (key, field) in enumerate(fields):
        raise_if_job_cancelled(job_id)
        pad = 0.28 if field.field_type == FieldType.date else 0.12
        crop = _crop_field(
            image, field.bbox_norm, pad_ratio=pad, template=template
        )
        is_date = field.field_type == FieldType.date

        def _run(c: np.ndarray = crop, date_field: bool = is_date):
            return ocr_crop(c, is_date=date_field)

        if job_id is not None and total > 0:
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=idx,
                message=f"Field {key} ({idx + 1}/{total})…",
                last_field_key=key,
            )

        crop_result = await loop.run_in_executor(_executor, _run)
        fe = _to_field_extraction(crop_result)
        results[key] = fe
        engine_counts[fe.engine] += 1

        if job_id is not None:
            set_job_progress(
                job_id,
                phase="ocr",
                fields_total=total,
                fields_done=idx + 1,
                message=f"Field {key}: {fe.engine}",
                last_field_engine=fe.engine,
                ocr_engine_counts=dict(engine_counts),
            )

    if job_id is not None and total > 0:
        update_job_pipeline(job_id, vlm="done")
    return results
