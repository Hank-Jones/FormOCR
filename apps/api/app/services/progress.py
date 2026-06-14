"""In-memory job progress for UI polling (batch and single-file jobs)."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_by_job: dict[int, dict[str, Any]] = {}
_cancelled: set[int] = set()


def request_job_cancel(job_id: int) -> None:
    with _lock:
        _cancelled.add(job_id)


def clear_job_cancel(job_id: int) -> None:
    with _lock:
        _cancelled.discard(job_id)


def is_job_cancelled(job_id: int) -> bool:
    with _lock:
        return job_id in _cancelled


def compute_progress_percent(state: dict[str, Any]) -> int:
    """
    Map file index + phase + field OCR into 0–99 (100 reserved for job completed).
    """
    total_files = max(1, int(state.get("total_files") or 1))
    file_index = max(0, min(int(state.get("file_index") or 0), total_files - 1))
    phase = (state.get("phase") or "").strip().lower()
    fields_total = int(state.get("fields_total") or 0)
    fields_done = max(0, int(state.get("fields_done") or 0))

    if phase == "error":
        within = 0.0
    elif phase == "cancelled":
        within = 0.0
    elif phase == "file":
        within = 0.03
    elif phase == "preprocess":
        within = 0.12
    elif phase == "detect":
        within = 0.20
    elif phase == "ocr":
        if fields_total > 0:
            chunk_prog = float(state.get("ocr_chunk_progress") or 0)
            chunk_prog = max(0.0, min(0.95, chunk_prog))
            chunk_size = max(1.0, float(state.get("ocr_chunk_size") or 1))
            effective = min(
                float(fields_total),
                float(fields_done) + chunk_prog * chunk_size,
            )
            within = 0.24 + 0.66 * (effective / fields_total)
        else:
            within = 0.40
    elif phase == "ai":
        within = 0.92
    elif phase == "save":
        within = 0.97
    else:
        within = 0.08

    frac = (file_index + within) / total_files
    return min(99, max(0, int(round(frac * 100))))


def set_job_progress(job_id: int, **kwargs: Any) -> None:
    with _lock:
        state = _by_job.setdefault(job_id, {})
        for key, value in kwargs.items():
            if value is not None:
                state[key] = value
        state["progress_percent"] = compute_progress_percent(state)


def update_job_pipeline(job_id: int, **parts: str) -> None:
    """Merge UI pipeline chip states (preprocess, vision, vlm, compute, llm)."""
    with _lock:
        state = _by_job.setdefault(job_id, {})
        pipe: dict[str, str] = dict(state.get("pipeline") or {})
        for key, value in parts.items():
            if value is not None:
                pipe[key] = value
        state["pipeline"] = pipe


def append_job_step(job_id: int, line: str) -> None:
    with _lock:
        state = _by_job.setdefault(job_id, {})
        steps: list[str] = list(state.get("steps") or [])
        steps.append(line)
        state["steps"] = steps[-40:]


def get_job_progress(job_id: int) -> dict[str, Any] | None:
    with _lock:
        raw = _by_job.get(job_id)
        return dict(raw) if raw else None


def clear_job_progress(job_id: int) -> None:
    with _lock:
        _by_job.pop(job_id, None)
        _cancelled.discard(job_id)


def clear_all_job_progress() -> None:
    with _lock:
        _by_job.clear()
        _cancelled.clear()
