"""Cooperative cancellation for long-running batch jobs."""

from __future__ import annotations

from app.services.progress import is_job_cancelled


class JobCancelledError(Exception):
    """Raised when the user cancels an in-progress job."""


def raise_if_job_cancelled(job_id: int | None) -> None:
    if job_id is not None and is_job_cancelled(job_id):
        raise JobCancelledError("Cancelled by user")
