from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Form, FormType, Template
from app.schemas.common import AnnotationField, FieldExtraction, TemplateField, TemplatePayload
from app.services.ai_correct import (
    correct_fields,
    fields_eligible_for_ai,
    merge_ai_corrections,
)
from app.services.extract import extract_fields_parallel
from app.services.form_detect import detect_form_type
from app.services.job_cancel import raise_if_job_cancelled
from app.services.preprocess import preprocess_file
from app.services.template_learn import template_from_json
from app.services.progress import (
    append_job_step,
    get_job_progress,
    set_job_progress,
    update_job_pipeline,
)
from app.services.field_styles import parse_field_styles
from app.services.validate import validate_extraction

logger = logging.getLogger("formocr.pipeline")


def _track_job_form(job_id: int | None, form: Form) -> None:
    if job_id is None:
        return
    progress = get_job_progress(job_id) or {}
    ids: list[int] = list(progress.get("form_ids") or [])
    if form.id not in ids:
        ids.append(form.id)
    set_job_progress(job_id, current_form_id=form.id, form_ids=ids)


def _begin_job_form(
    db: Session,
    *,
    job_id: int | None,
    image_path: Path,
    processed_path: Path,
    working: Form | None,
) -> Form | None:
    """Create or refresh in-progress form row so UI can show input/preprocess previews."""
    if job_id is None:
        return working
    if working is None:
        working = Form(
            job_id=job_id,
            raw_image_path=str(image_path),
            processed_image_path=str(processed_path),
            review_status="processing",
        )
        db.add(working)
        db.commit()
        db.refresh(working)
    else:
        working.raw_image_path = str(image_path)
        working.processed_image_path = str(processed_path)
        if working.review_status not in ("pending", "approved", "rejected"):
            working.review_status = "processing"
        db.commit()
        db.refresh(working)
    _track_job_form(job_id, working)
    return working


def save_upload(data: bytes, suffix: str) -> Path:
    settings.ensure_dirs()
    name = f"{uuid.uuid4().hex}{suffix}"
    path = settings.images_dir / name
    path.write_bytes(data)
    return path


def rasterize_pdf(pdf_path: Path) -> list[Path]:
    import fitz

    doc = fitz.open(str(pdf_path))
    paths: list[Path] = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        out = settings.images_dir / f"{pdf_path.stem}_p{i}.png"
        pix.save(str(out))
        paths.append(out)
    doc.close()
    return paths


def get_latest_template(db: Session, form_type_id: int) -> Template | None:
    return (
        db.query(Template)
        .filter(Template.form_type_id == form_type_id)
        .order_by(Template.version.desc())
        .first()
    )


def _clamp_bbox_norm(bbox: list[float]) -> list[float]:
    x, y, w, h = [float(v) for v in bbox[:4]]
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.01, min(1.0 - x, w))
    h = max(0.01, min(1.0 - y, h))
    return [x, y, w, h]


def _apply_field_overrides(
    payload: TemplatePayload,
    field_overrides: list[AnnotationField],
    *,
    processed_w: int,
    processed_h: int,
    page_transform,
) -> None:
    override_fields: dict[str, TemplateField] = {}
    for field in field_overrides:
        key = field.key.strip()
        if not key:
            continue
        bbox = _clamp_bbox_norm(field.bbox_norm)
        if page_transform is not None:
            bbox = _clamp_bbox_norm(page_transform.apply_bbox_norm(bbox))
        override_fields[key] = TemplateField(
            bbox_norm=[round(v, 4) for v in bbox],
            field_type=field.field_type,
            tolerance=0.02,
            label=(field.label or key).strip() or key,
            style_key=field.style_key,
            allowed_values=field.allowed_values,
            line_count=field.line_count,
        )
    if override_fields:
        payload.fields = override_fields
        payload.reference_size = [int(processed_w), int(processed_h)]


async def process_form_image(
    db: Session,
    image_path: Path,
    *,
    form_type_id: int | None = None,
    job_id: int | None = None,
    auto_detect: bool = True,
    use_ai: bool | None = None,
    field_overrides: list[AnnotationField] | None = None,
) -> Form:
    raise_if_job_cancelled(job_id)
    if job_id is not None:
        update_job_pipeline(job_id, preprocess="active")
        set_job_progress(job_id, phase="preprocess", message="Preparing image…")
    processed_path = settings.images_dir / f"{image_path.stem}_proc{image_path.suffix}"
    _pw, _ph, _page_transform = preprocess_file(
        image_path,
        processed_path,
        auto_orient=settings.preprocess_auto_orient,
        deskew=settings.preprocess_deskew,
        align=settings.preprocess_align,
        denoise=settings.preprocess_denoise,
        sharpen=settings.preprocess_sharpen,
        contrast=settings.preprocess_contrast,
        high_resolution=settings.preprocess_high_resolution,
    )
    if job_id is not None:
        update_job_pipeline(job_id, preprocess="done")
        set_job_progress(
            job_id,
            phase="preprocess",
            message="Image preprocessing done",
            preview_raw_path=str(image_path),
            preview_processed_path=str(processed_path),
        )

    working_form = _begin_job_form(
        db,
        job_id=job_id,
        image_path=image_path,
        processed_path=processed_path,
        working=None,
    )
    ocr_image_path = processed_path

    detected_id = form_type_id
    detection_score = None
    if auto_detect and form_type_id is None:
        if job_id is not None:
            set_job_progress(job_id, phase="detect", message="Detecting form type…")
        form_types = db.query(FormType).all()
        templates = {
            t.form_type_id: t
            for t in db.query(Template).all()
        }
        latest = {}
        for t in templates.values():
            if t.form_type_id not in latest or t.version > latest[t.form_type_id].version:
                latest[t.form_type_id] = t
        from app.db.models import TemplateSample

        sample_paths: dict[int, list[str]] = {}
        for s in db.query(TemplateSample).all():
            sample_paths.setdefault(s.form_type_id, []).append(s.image_path)
        result = detect_form_type(
            str(ocr_image_path), form_types, latest, sample_paths=sample_paths
        )
        detected_id = result.form_type_id
        detection_score = result.score

    if detected_id is None:
        form = working_form or Form(
            form_type_id=None,
            job_id=job_id,
            raw_image_path=str(image_path),
            processed_image_path=str(processed_path),
            review_status="needs_type",
            detection_score=detection_score,
        )
        if working_form is None:
            db.add(form)
        else:
            form.form_type_id = None
            form.review_status = "needs_type"
            form.detection_score = detection_score
        db.commit()
        db.refresh(form)
        _track_job_form(job_id, form)
        return form

    tmpl = get_latest_template(db, detected_id)
    if not tmpl:
        form = working_form or Form(
            form_type_id=detected_id,
            job_id=job_id,
            raw_image_path=str(image_path),
            processed_image_path=str(processed_path),
            review_status="no_template",
            detection_score=detection_score,
        )
        if working_form is None:
            db.add(form)
        else:
            form.form_type_id = detected_id
            form.review_status = "no_template"
            form.detection_score = detection_score
        db.commit()
        db.refresh(form)
        _track_job_form(job_id, form)
        return form

    payload = template_from_json(tmpl.fields_json)
    ft_row = db.query(FormType).filter(FormType.id == detected_id).first()
    if ft_row and ft_row.field_styles_json:
        payload.field_styles = parse_field_styles(ft_row.field_styles_json)
    if field_overrides:
        _apply_field_overrides(
            payload,
            field_overrides,
            processed_w=_pw,
            processed_h=_ph,
            page_transform=_page_transform,
        )
    if working_form is not None:
        working_form.form_type_id = detected_id
        db.commit()
        db.refresh(working_form)
        _track_job_form(job_id, working_form)
    if job_id is not None:
        n_fields = len(payload.fields)
        set_job_progress(
            job_id,
            phase="ocr",
            fields_total=n_fields,
            fields_done=0,
            message=f"Reading {n_fields} fields…",
        )

    raise_if_job_cancelled(job_id)
    extractions = await extract_fields_parallel(
        str(ocr_image_path),
        payload,
        processed_path=str(ocr_image_path),
        job_id=job_id,
    )
    raise_if_job_cancelled(job_id)
    ext_dict = {k: v.model_dump() for k, v in extractions.items()}
    validated, confidence = validate_extraction(extractions, payload)

    corrected = dict(validated)
    ai_error: str | None = None
    do_ai = use_ai if use_ai is not None else settings.ai_correction_enabled
    ai_model = settings.ollama_model

    if do_ai:
        ai_keys = fields_eligible_for_ai(validated, confidence, payload)
        if ai_keys:
            if job_id is not None:
                set_job_progress(
                    job_id,
                    phase="ai",
                    message=f"AI correction ({ai_model})…",
                    ai_model=ai_model,
                    ai_error=None,
                )
                update_job_pipeline(job_id, llm="active")
            ai_input = {k: validated[k] for k in ai_keys}
            ai_result, ai_error = await correct_fields(
                ai_input,
                ai_keys,
                {k: v.field_type.value for k, v in payload.fields.items()},
            )
            if ai_error:
                logger.warning("AI correction failed: %s", ai_error)
                if job_id is not None:
                    append_job_step(job_id, f"AI error: {ai_error}")
                    set_job_progress(
                        job_id,
                        phase="ai",
                        message=f"AI failed: {ai_error[:120]}",
                        ai_model=ai_model,
                        ai_error=ai_error,
                    )
            elif ai_result:
                if job_id is not None:
                    update_job_pipeline(job_id, llm="done")
                corrected = merge_ai_corrections(
                    validated,
                    ai_result,
                    payload,
                    confidence,
                    extractions,
                )
                for key, ai_val in ai_result.items():
                    if key in extractions and ai_val is not None:
                        ex = extractions[key]
                        extractions[key] = ex.model_copy(
                            update={"phi3_text": str(ai_val).strip()}
                        )
                ext_dict = {k: v.model_dump() for k, v in extractions.items()}
            else:
                ai_error = ai_error or f"{ai_model} returned no changes"
                if job_id is not None:
                    append_job_step(job_id, ai_error)
        elif job_id is not None:
            update_job_pipeline(job_id, llm="off")

    if job_id is not None:
        update_job_pipeline(job_id, vlm="done")
        set_job_progress(job_id, phase="save", message="Saving results…")

    form = working_form or Form(
        form_type_id=detected_id,
        job_id=job_id,
        raw_image_path=str(image_path),
        processed_image_path=str(processed_path),
        review_status="pending",
        detection_score=detection_score,
    )
    if working_form is None:
        db.add(form)
    form.form_type_id = detected_id
    form.raw_image_path = str(image_path)
    form.processed_image_path = str(processed_path)
    form.extracted_json = json.dumps(ext_dict)
    form.validated_json = json.dumps(validated)
    form.corrected_json = json.dumps(corrected)
    form.confidence_json = json.dumps(confidence)
    form.review_status = "pending"
    form.detection_score = detection_score
    db.commit()
    db.refresh(form)
    _track_job_form(job_id, form)
    return form
