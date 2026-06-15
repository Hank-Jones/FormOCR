import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form as FastApiForm, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Form, FormType, ProcessingJob
from app.db.session import SessionLocal, get_db
from app.schemas.common import AnnotationsPayload, FormOut, JobOut, ProcessOptions
from app.routers.forms import _form_to_out
from app.services.job_cancel import JobCancelledError, raise_if_job_cancelled
from app.services.pipeline import process_form_image, rasterize_pdf, save_upload
from app.services.progress import (
    append_job_step,
    get_job_progress,
    is_job_cancelled,
    request_job_cancel,
    set_job_progress,
    update_job_pipeline,
)

router = APIRouter(prefix="/process", tags=["process"])


def _job_to_out(job: ProcessingJob) -> JobOut:
    progress = get_job_progress(job.id) or {}
    return JobOut(
        id=job.id,
        status=job.status,
        form_type_id=job.form_type_id,
        total_count=job.total_count,
        processed_count=job.processed_count,
        created_at=job.created_at,
        completed_at=job.completed_at,
        phase=progress.get("phase"),
        message=progress.get("message"),
        fields_total=progress.get("fields_total"),
        fields_done=progress.get("fields_done"),
        progress_percent=progress.get("progress_percent"),
        ocr_lang=progress.get("ocr_lang"),
        handwriting_model=progress.get("handwriting_model"),
        ai_model=progress.get("ai_model"),
        ocr_engine_counts=progress.get("ocr_engine_counts"),
        ai_error=progress.get("ai_error"),
        steps=progress.get("steps"),
        last_field_key=progress.get("last_field_key"),
        last_field_engine=progress.get("last_field_engine"),
        form_ids=progress.get("form_ids"),
        current_form_id=progress.get("current_form_id"),
        preview_raw_path=progress.get("preview_raw_path"),
        preview_processed_path=progress.get("preview_processed_path"),
        pipeline=progress.get("pipeline"),
    )


def _resolve_job_preview_path(job_id: int, variant: str) -> Path:
    progress = get_job_progress(job_id) or {}
    key = "preview_processed_path" if variant == "processed" else "preview_raw_path"
    path_str = progress.get(key)
    if not path_str:
        raise HTTPException(404, "Preview not available yet")
    path = Path(path_str).resolve()
    images_root = settings.images_dir.resolve()
    try:
        path.relative_to(images_root)
    except ValueError as e:
        raise HTTPException(403, "Invalid preview path") from e
    if not path.is_file():
        raise HTTPException(404, "Preview image not found")
    return path


def _mark_processing_forms_cancelled(db: Session, job_id: int) -> None:
    forms = (
        db.query(Form)
        .filter(Form.job_id == job_id, Form.review_status == "processing")
        .all()
    )
    for form in forms:
        form.review_status = "cancelled"


def _finalize_cancelled_job(db: Session, job_id: int) -> None:
    _mark_processing_forms_cancelled(db, job_id)
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if job and job.status not in ("completed", "failed", "cancelled"):
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
    db.commit()
    set_job_progress(job_id, phase="cancelled", message="Cancelled by user")
    update_job_pipeline(job_id, vlm="idle")


async def _run_job(job_id: int, paths: list[Path], options: ProcessOptions):
    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            return
        if is_job_cancelled(job_id):
            _finalize_cancelled_job(db, job_id)
            return
        job.status = "running"
        db.commit()
        update_job_pipeline(
            job_id,
            preprocess="pending",
            vision="pending",
            vlm="idle",
            compute="unknown",
            llm="off",
        )
        total_files = len(paths)
        for i, path in enumerate(paths):
            raise_if_job_cancelled(job_id)
            set_job_progress(
                job_id,
                file_index=i,
                total_files=total_files,
                phase="file",
                message=f"Processing file {i + 1} of {total_files}…",
                fields_total=0,
                fields_done=0,
            )
            try:
                form = await process_form_image(
                    db,
                    path,
                    form_type_id=options.form_type_id,
                    job_id=job_id,
                    auto_detect=options.auto_detect,
                    use_ai=options.use_ai,
                    field_overrides=options.field_overrides,
                )
                raise_if_job_cancelled(job_id)
                ids: list[int] = list(get_job_progress(job_id).get("form_ids") or [])
                if form.id not in ids:
                    ids.append(form.id)
                set_job_progress(job_id, form_ids=ids, current_form_id=form.id)
            except JobCancelledError:
                append_job_step(job_id, f"Cancelled during {path.name}")
                _finalize_cancelled_job(db, job_id)
                return
            except Exception as e:
                err = str(e).strip() or repr(e)
                append_job_step(job_id, f"File failed: {path.name}: {err[:200]}")
                set_job_progress(
                    job_id,
                    phase="error",
                    message=f"Failed on {path.name}: {err[:120]}",
                    ai_error=err[:300],
                )
                raise
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.processed_count = i + 1
                db.commit()
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job:
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            db.commit()
    except JobCancelledError:
        append_job_step(job_id, "Job cancelled by user")
        _finalize_cancelled_job(db, job_id)
    except Exception as e:
        err = str(e).strip() or repr(e)
        append_job_step(job_id, f"Job failed: {err[:200]}")
        set_job_progress(job_id, phase="error", message=err[:200], ai_error=err[:300])
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job:
            job.status = "failed"
            db.commit()
    finally:
        db.close()


@router.post("/batch", response_model=JobOut)
async def batch_process(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    field_overrides: str | None = FastApiForm(None),
    form_type_id: int | None = Query(None),
    auto_detect: bool = Query(False),
    use_ai: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    if form_type_id is None:
        raise HTTPException(400, "Select a form type before processing.")
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    if ft.status != "published":
        raise HTTPException(
            400,
            "Form type must be published. Finish the template and publish first.",
        )

    parsed_field_overrides = None
    if field_overrides:
        try:
            parsed_field_overrides = AnnotationsPayload.model_validate(
                json.loads(field_overrides)
            ).fields
        except Exception as e:
            raise HTTPException(400, "Invalid field override payload") from e

    paths: list[Path] = []
    for file in files:
        content = await file.read()
        suffix = Path(file.filename or "upload.png").suffix.lower()
        if suffix == ".pdf":
            pdf_path = save_upload(content, ".pdf")
            paths.extend(rasterize_pdf(pdf_path))
        else:
            if suffix not in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
                suffix = ".png"
            paths.append(save_upload(content, suffix))

    job = ProcessingJob(
        status="pending",
        form_type_id=form_type_id,
        total_count=len(paths),
        processed_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    options = ProcessOptions(
        form_type_id=form_type_id,
        auto_detect=auto_detect,
        use_ai=use_ai,
        field_overrides=parsed_field_overrides,
    )
    background_tasks.add_task(_run_job, job.id, paths, options)
    return _job_to_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 20, db: Session = Depends(get_db)):
    jobs = (
        db.query(ProcessingJob)
        .order_by(ProcessingJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_job_to_out(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("completed", "failed", "cancelled"):
        return _job_to_out(job)
    request_job_cancel(job_id)
    append_job_step(job_id, "Cancel requested")
    set_job_progress(
        job_id,
        phase="cancelled",
        message="Cancelling… (finishes current OCR step)",
    )
    if job.status == "pending":
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
        _mark_processing_forms_cancelled(db, job_id)
        db.commit()
        append_job_step(job_id, "Job cancelled by user")
    else:
        db.commit()
    return _job_to_out(job)


@router.get("/jobs/{job_id}/preview-image")
def get_job_preview_image(
    job_id: int,
    variant: Literal["raw", "processed"] = Query("raw"),
    db: Session = Depends(get_db),
):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    path = _resolve_job_preview_path(job_id, variant)
    return FileResponse(path)


@router.get("/jobs/{job_id}/forms", response_model=list[FormOut])
def get_job_forms(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    forms = (
        db.query(Form)
        .filter(Form.job_id == job_id)
        .order_by(Form.id.asc())
        .all()
    )
    return [_form_to_out(f) for f in forms]
