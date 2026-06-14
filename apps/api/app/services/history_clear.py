"""Remove processed forms, jobs, and their image files (keeps templates & form types)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Correction, Form, ProcessingJob
from app.services.progress import clear_all_job_progress

logger = logging.getLogger("formocr")

CLEAR_HISTORY_FORBIDDEN = "Cannot clear history while a job is still running"
_STALE_JOB_HOURS = 6


def reconcile_stale_jobs(db: Session) -> int:
    """Mark abandoned pending/running jobs as failed so history can be cleared."""
    cutoff = datetime.utcnow() - timedelta(hours=_STALE_JOB_HOURS)
    stale = (
        db.query(ProcessingJob)
        .filter(
            ProcessingJob.status.in_(("pending", "running")),
            ProcessingJob.created_at < cutoff,
        )
        .all()
    )
    for job in stale:
        job.status = "failed"
        job.completed_at = datetime.utcnow()
    if stale:
        db.commit()
        logger.info("Marked %s stale jobs as failed", len(stale))
    return len(stale)


def _safe_unlink(path_str: str | None, images_root: Path) -> bool:
    if not path_str or not str(path_str).strip():
        return False
    try:
        resolved = Path(path_str).resolve()
        resolved.relative_to(images_root.resolve())
    except (ValueError, OSError):
        logger.warning("Skipped unlink outside images dir: %s", path_str)
        return False
    if resolved.is_file():
        resolved.unlink(missing_ok=True)
        return True
    return False


def abandon_active_jobs(db: Session) -> int:
    """Mark all pending/running jobs failed (user confirmed force clear)."""
    active = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status.in_(("pending", "running")))
        .all()
    )
    now = datetime.utcnow()
    for job in active:
        job.status = "failed"
        job.completed_at = now
    if active:
        db.commit()
        clear_all_job_progress()
        logger.info("Abandoned %s active jobs for force clear", len(active))
    return len(active)


def clear_processing_history(db: Session, *, force: bool = False) -> dict[str, int]:
    stale_marked = reconcile_stale_jobs(db)
    if force:
        stale_marked += abandon_active_jobs(db)
    running = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status.in_(("pending", "running")))
        .count()
    )
    if running:
        raise ValueError(CLEAR_HISTORY_FORBIDDEN)

    images_root = settings.images_dir.resolve()
    forms = db.query(Form).all()
    form_ids = [f.id for f in forms]

    files_deleted = 0
    for form in forms:
        if _safe_unlink(form.raw_image_path, images_root):
            files_deleted += 1
        if _safe_unlink(form.processed_image_path, images_root):
            files_deleted += 1

    corrections_deleted = 0
    if form_ids:
        corrections_deleted = (
            db.query(Correction)
            .filter(Correction.form_id.in_(form_ids))
            .delete(synchronize_session=False)
        )

    forms_deleted = (
        db.query(Form).delete(synchronize_session=False) if forms else 0
    )
    jobs_deleted = db.query(ProcessingJob).delete(synchronize_session=False)

    db.commit()
    clear_all_job_progress()

    logger.info(
        "Cleared history: forms=%s jobs=%s corrections=%s files=%s",
        forms_deleted,
        jobs_deleted,
        corrections_deleted,
        files_deleted,
    )
    return {
        "forms_deleted": forms_deleted,
        "jobs_deleted": jobs_deleted,
        "corrections_deleted": corrections_deleted,
        "files_deleted": files_deleted,
        "stale_jobs_marked": stale_marked,
    }
