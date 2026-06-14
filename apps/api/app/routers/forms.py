import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.db.models import Correction, Form
from app.db.session import get_db
from app.schemas.common import FormFieldMeta, FormOut, ReviewPayload
from app.services.field_crop import crop_field_from_paths, encode_crop_jpeg
from app.services.pipeline import get_latest_template, process_form_image, rasterize_pdf, save_upload
from app.services.template_learn import template_from_json

router = APIRouter(prefix="/forms", tags=["forms"])


def _template_fields_for_form(db: Session, form: Form) -> list[FormFieldMeta]:
    if not form.form_type_id:
        return []
    tmpl = get_latest_template(db, form.form_type_id)
    if not tmpl:
        return []
    payload = template_from_json(tmpl.fields_json)
    return [
        FormFieldMeta(
            key=key,
            label=field.label or key,
            field_type=field.field_type.value,
            line_count=field.line_count,
            bbox_norm=field.bbox_norm,
        )
        for key, field in payload.fields.items()
    ]


def _form_to_out(form: Form) -> FormOut:
    return FormOut(
        id=form.id,
        form_type_id=form.form_type_id,
        job_id=form.job_id,
        raw_image_path=form.raw_image_path,
        processed_image_path=form.processed_image_path,
        extracted=json.loads(form.extracted_json) if form.extracted_json else None,
        validated=json.loads(form.validated_json) if form.validated_json else None,
        corrected=json.loads(form.corrected_json) if form.corrected_json else None,
        confidence=json.loads(form.confidence_json) if form.confidence_json else None,
        review_status=form.review_status,
        detection_score=form.detection_score,
        created_at=form.created_at,
    )


@router.get("", response_model=list[FormOut])
def list_forms(
    review_status: str | None = Query(None),
    form_type_id: int | None = Query(None),
    job_id: int | None = Query(None),
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Form).order_by(Form.created_at.desc())
    if review_status:
        q = q.filter(Form.review_status == review_status)
    if form_type_id:
        q = q.filter(Form.form_type_id == form_type_id)
    if job_id is not None:
        q = q.filter(Form.job_id == job_id)
    return [_form_to_out(f) for f in q.limit(limit).all()]


@router.get("/{form_id}", response_model=FormOut)
def get_form(form_id: int, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, "Form not found")
    return _form_to_out(form)


@router.get("/{form_id}/image")
def get_form_image(form_id: int, processed: bool = False, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, "Form not found")
    path = form.processed_image_path if processed and form.processed_image_path else form.raw_image_path
    if not Path(path).exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(path)


@router.get("/{form_id}/fields", response_model=list[FormFieldMeta])
def list_form_fields(form_id: int, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, "Form not found")
    return _template_fields_for_form(db, form)


@router.get("/{form_id}/fields/{field_key}/crop")
def get_form_field_crop(form_id: int, field_key: str, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, "Form not found")
    if not form.form_type_id:
        raise HTTPException(404, "Form type not set")
    tmpl = get_latest_template(db, form.form_type_id)
    if not tmpl:
        raise HTTPException(404, "Template not found")
    payload = template_from_json(tmpl.fields_json)
    field = payload.fields.get(field_key)
    if not field:
        raise HTTPException(404, f"Unknown field: {field_key}")
    image_path = form.processed_image_path or form.raw_image_path
    if not image_path or not Path(image_path).exists():
        raise HTTPException(404, "Image file not found")
    try:
        crop = crop_field_from_paths(
            image_path,
            field.bbox_norm,
            field_type=field.field_type,
            template=payload,
        )
        jpeg = encode_crop_jpeg(crop)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return Response(content=jpeg, media_type="image/jpeg")


@router.post("/process", response_model=FormOut)
async def process_single(
    file: UploadFile = File(...),
    form_type_id: int | None = Query(None),
    auto_detect: bool = Query(False),
    use_ai: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    if form_type_id is None:
        raise HTTPException(400, "Select a form type before processing.")
    content = await file.read()
    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix == ".pdf":
        pdf_path = save_upload(content, ".pdf")
        pages = rasterize_pdf(pdf_path)
        image_path = pages[0]
    else:
        if suffix not in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
            suffix = ".png"
        image_path = save_upload(content, suffix)
    form = await process_form_image(
        db,
        image_path,
        form_type_id=form_type_id,
        auto_detect=auto_detect,
        use_ai=use_ai,
    )
    return _form_to_out(form)


@router.post("/{form_id}/review", response_model=FormOut)
def submit_review(form_id: int, body: ReviewPayload, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, "Form not found")

    old_corrected = json.loads(form.corrected_json) if form.corrected_json else {}
    form.corrected_json = json.dumps(body.corrected)
    form.review_status = body.status.value
    from datetime import datetime

    form.reviewed_at = datetime.utcnow()

    if body.corrections:
        for c in body.corrections:
            key = c.get("field_key", "")
            db.add(
                Correction(
                    form_id=form_id,
                    field_key=key,
                    before_value=c.get("before"),
                    after_value=c.get("after"),
                    user_action=c.get("action", "edit"),
                )
            )
    else:
        for key, new_val in body.corrected.items():
            old_val = old_corrected.get(key)
            if old_val != new_val:
                db.add(
                    Correction(
                        form_id=form_id,
                        field_key=key,
                        before_value=str(old_val) if old_val is not None else None,
                        after_value=str(new_val),
                        user_action="edit",
                    )
                )
    db.commit()
    db.refresh(form)
    return _form_to_out(form)
