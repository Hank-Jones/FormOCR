"""Remove processed forms, jobs, and their image files (keeps templates & form types)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Correction, Form, ProcessingJob
from app.services.file_cleanup import collect_related_image_paths, safe_unlink_paths
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


def clear_processing_history(db: Session, *, force: bool = False) -> dict[str, int]:
    stale_marked = reconcile_stale_jobs(db) if force else 0
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

    cleanup_paths: set[Path] = set()
    for form in forms:
        cleanup_paths.update(collect_related_image_paths(form.raw_image_path, images_root))
        cleanup_paths.update(collect_related_image_paths(form.processed_image_path, images_root))

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
    files_deleted = safe_unlink_paths(cleanup_paths, images_root)

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
