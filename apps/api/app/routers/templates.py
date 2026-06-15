import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.models import FormType, Template, TemplateSample
from app.db.session import get_db
from app.schemas.common import AnnotationField, AnnotationsPayload, TemplateSampleOut
from app.config import settings
from app.services.pipeline import rasterize_pdf, save_upload
from app.services.preprocess import load_image, preprocess_file, preprocess_page
from app.services.field_styles import parse_field_styles
from app.services.template_learn import (
    _anchors_from_labels,
    aggregate_annotations,
    extract_anchor_keywords,
    template_to_json,
    template_from_json,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _parse_annotations(raw: str | None) -> list[AnnotationField] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return AnnotationsPayload.model_validate(data).fields
    except Exception:
        return None


@router.post("/samples", response_model=TemplateSampleOut)
async def upload_sample(
    form_type_id: int = Form(...),
    file: UploadFile = File(...),
    page_index: int = Form(0),
    db: Session = Depends(get_db),
):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")

    content = await file.read()
    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix == ".pdf":
        pdf_path = save_upload(content, ".pdf")
        pages = rasterize_pdf(pdf_path)
        if not pages:
            raise HTTPException(400, "PDF has no pages")
        image_path = pages[min(page_index, len(pages) - 1)]
    else:
        if suffix not in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
            suffix = ".png"
        image_path = save_upload(content, suffix)

    processed_path = image_path.parent / f"{image_path.stem}_proc{image_path.suffix}"
    processed_str: str | None = None
    w, h = 0, 0
    try:
        w, h, _transform = preprocess_file(
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
        processed_str = str(processed_path)
    except Exception as exc:
        import logging

        logging.getLogger("formocr").warning(
            "Preprocess failed for sample (using raw image): %s", exc
        )
        img = load_image(image_path)
        h, w = img.shape[:2]
    if w < 1 or h < 1:
        img = load_image(image_path)
        h, w = img.shape[:2]
    sample = TemplateSample(
        form_type_id=form_type_id,
        image_path=str(image_path),
        processed_path=processed_str,
        page_index=page_index,
        width=w,
        height=h,
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return TemplateSampleOut(
        id=sample.id,
        form_type_id=sample.form_type_id,
        image_path=sample.image_path,
        page_index=sample.page_index,
        width=sample.width,
        height=sample.height,
        annotations=None,
    )


@router.get("/samples/{sample_id}/image")
def get_sample_image(sample_id: int, db: Session = Depends(get_db)):
    sample = db.query(TemplateSample).filter(TemplateSample.id == sample_id).first()
    if not sample:
        raise HTTPException(404, "Sample not found")
    path = Path(sample.image_path)
    if sample.processed_path:
        proc = Path(sample.processed_path)
        if proc.exists():
            path = proc
    if not path.exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(path)


@router.get("/samples/{sample_id}", response_model=TemplateSampleOut)
def get_sample(sample_id: int, db: Session = Depends(get_db)):
    sample = db.query(TemplateSample).filter(TemplateSample.id == sample_id).first()
    if not sample:
        raise HTTPException(404, "Sample not found")
    return TemplateSampleOut(
        id=sample.id,
        form_type_id=sample.form_type_id,
        image_path=sample.image_path,
        page_index=sample.page_index,
        width=sample.width,
        height=sample.height,
        annotations=_parse_annotations(sample.annotation_json),
    )


@router.get("/form-type/{form_type_id}/samples", response_model=list[TemplateSampleOut])
def list_samples(form_type_id: int, db: Session = Depends(get_db)):
    samples = (
        db.query(TemplateSample)
        .filter(TemplateSample.form_type_id == form_type_id)
        .order_by(TemplateSample.created_at)
        .all()
    )
    return [
        TemplateSampleOut(
            id=s.id,
            form_type_id=s.form_type_id,
            image_path=s.image_path,
            page_index=s.page_index,
            width=s.width,
            height=s.height,
            annotations=_parse_annotations(s.annotation_json),
        )
        for s in samples
    ]


@router.put("/samples/{sample_id}/annotations")
def save_annotations(
    sample_id: int,
    body: AnnotationsPayload,
    db: Session = Depends(get_db),
):
    sample = db.query(TemplateSample).filter(TemplateSample.id == sample_id).first()
    if not sample:
        raise HTTPException(404, "Sample not found")
    sample.annotation_json = json.dumps(body.model_dump(mode="json"))
    db.commit()
    return {"ok": True, "field_count": len(body.fields)}


@router.post("/{form_type_id}/publish")
def publish_template(form_type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")

    samples = (
        db.query(TemplateSample)
        .filter(TemplateSample.form_type_id == form_type_id)
        .all()
    )
    annotated: list[TemplateSample] = []
    all_fields: list[list[AnnotationField]] = []
    labels: list[str] = []
    field_keys: list[str] = []
    for s in samples:
        if not s.annotation_json:
            continue
        try:
            payload = AnnotationsPayload.model_validate(json.loads(s.annotation_json))
        except Exception:
            continue
        if not payload.fields:
            continue
        annotated.append(s)
        all_fields.append(payload.fields)
        labels.extend(f.label for f in payload.fields if f.label)
        field_keys.extend(f.key for f in payload.fields if f.key)
    if not annotated:
        raise HTTPException(
            400,
            "Draw at least one field on a sample image before publishing.",
        )

    new_version = ft.version + 1
    template = aggregate_annotations(all_fields, ft.name, new_version)
    template.field_styles = parse_field_styles(ft.field_styles_json)

    ref = annotated[0]
    raw_img = load_image(ref.image_path)
    raw_h, raw_w = raw_img.shape[:2]
    _, sample_transform = preprocess_page(
        raw_img,
        auto_orient=settings.preprocess_auto_orient,
        deskew=settings.preprocess_deskew,
        align=settings.preprocess_align,
        denoise=settings.preprocess_denoise,
        sharpen=settings.preprocess_sharpen,
        contrast=settings.preprocess_contrast,
        high_resolution=settings.preprocess_high_resolution,
    )
    proc_w, proc_h = sample_transform.dst_w, sample_transform.dst_h
    stored_w, stored_h = ref.width or 0, ref.height or 0
    # Legacy: field boxes drawn on the raw upload (stored size matches raw).
    if stored_w == raw_w and stored_h == raw_h and (proc_w != raw_w or proc_h != raw_h):
        for field in template.fields.values():
            field.bbox_norm = sample_transform.apply_bbox_norm(field.bbox_norm)
    template.reference_size = [proc_w, proc_h]
    image_paths = [s.image_path for s in annotated]
    try:
        anchors = extract_anchor_keywords(
            image_paths, field_labels=labels, field_keys=field_keys
        )
    except Exception:
        anchors = _anchors_from_labels(labels, field_keys)
    if not anchors:
        anchors = _anchors_from_labels(labels, field_keys)
    template.anchors = anchors

    tmpl_row = Template(
        form_type_id=form_type_id,
        version=new_version,
        fields_json=template_to_json(template),
    )
    ft.version = new_version
    ft.status = "published"
    ft.anchor_keywords = json.dumps(anchors)
    db.add(tmpl_row)
    db.commit()
    db.refresh(tmpl_row)
    return {
        "template_id": tmpl_row.id,
        "version": new_version,
        "template": template.model_dump(),
        "anchors": anchors,
    }


@router.get("/{form_type_id}/latest")
def get_latest_template(form_type_id: int, db: Session = Depends(get_db)):
    tmpl = (
        db.query(Template)
        .filter(Template.form_type_id == form_type_id)
        .order_by(Template.version.desc())
        .first()
    )
    if not tmpl:
        raise HTTPException(404, "No published template")
    return template_from_json(tmpl.fields_json)
