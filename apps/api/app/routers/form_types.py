import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Correction, Form, FormType, ProcessingJob, Template, TemplateSample
from app.db.session import get_db
from app.schemas.common import FormTypeCreate, FormTypeOut, FormTypeUpdate
from app.services.file_cleanup import collect_related_image_paths, safe_unlink_paths
from app.services.field_styles import parse_field_styles

router = APIRouter(prefix="/form-types", tags=["form-types"])
_MAX_FORM_TYPE_NAME = 128


def _json_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [str(item) for item in parsed]


def _json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if len(name) > _MAX_FORM_TYPE_NAME:
        raise HTTPException(400, f"Name must be {_MAX_FORM_TYPE_NAME} characters or fewer")
    return name


def _name_exists(db: Session, name: str, exclude_id: int | None = None) -> bool:
    q = db.query(FormType).filter(func.lower(func.trim(FormType.name)) == name.lower())
    if exclude_id is not None:
        q = q.filter(FormType.id != exclude_id)
    return q.first() is not None


def _form_type_out(ft: FormType) -> FormTypeOut:
    return FormTypeOut(
        id=ft.id,
        name=ft.name,
        version=ft.version,
        status=ft.status,
        anchor_keywords=_json_list(ft.anchor_keywords),
        field_styles=parse_field_styles(ft.field_styles_json),
        created_at=ft.created_at,
    )


@router.get("", response_model=list[FormTypeOut])
def list_form_types(db: Session = Depends(get_db)):
    items = db.query(FormType).order_by(FormType.created_at.desc()).all()
    return [_form_type_out(ft) for ft in items]


@router.post("", response_model=FormTypeOut)
def create_form_type(body: FormTypeCreate, db: Session = Depends(get_db)):
    name = _normalize_name(body.name)
    if _name_exists(db, name):
        raise HTTPException(400, "Form type name already exists")
    ft = FormType(name=name, status="draft")
    db.add(ft)
    db.commit()
    db.refresh(ft)
    return _form_type_out(ft)


@router.patch("/{form_type_id}", response_model=FormTypeOut)
def update_form_type(
    form_type_id: int, body: FormTypeUpdate, db: Session = Depends(get_db)
):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    if body.name is not None:
        name = _normalize_name(body.name)
        if _name_exists(db, name, exclude_id=form_type_id):
            raise HTTPException(400, "Form type name already exists")
        ft.name = name
    db.commit()
    db.refresh(ft)
    return _form_type_out(ft)


@router.get("/{form_type_id}", response_model=FormTypeOut)
def get_form_type(form_type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    return _form_type_out(ft)


class FieldStylesUpdate(BaseModel):
    field_styles: dict[str, list[str]]


@router.get("/{form_type_id}/field-styles")
def get_field_styles(form_type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    return {"field_styles": parse_field_styles(ft.field_styles_json)}


@router.put("/{form_type_id}/field-styles")
def put_field_styles(
    form_type_id: int, body: FieldStylesUpdate, db: Session = Depends(get_db)
):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    cleaned: dict[str, list[str]] = {}
    for name, vals in body.field_styles.items():
        key = str(name).strip()
        if not key:
            continue
        items = [str(v).strip() for v in vals if str(v).strip()]
        if items:
            cleaned[key] = items
    ft.field_styles_json = json.dumps(cleaned, ensure_ascii=False)
    db.commit()
    return {"field_styles": cleaned}


@router.get("/{form_type_id}/templates")
def list_templates(form_type_id: int, db: Session = Depends(get_db)):
    templates = (
        db.query(Template)
        .filter(Template.form_type_id == form_type_id)
        .order_by(Template.version.desc())
        .all()
    )
    return [
        {
            "id": t.id,
            "version": t.version,
            "published_at": t.published_at.isoformat(),
            "fields_json": _json_object(t.fields_json),
        }
        for t in templates
    ]


@router.delete("/{form_type_id}")
def delete_form_type(form_type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")
    active_jobs = (
        db.query(ProcessingJob)
        .filter(
            ProcessingJob.form_type_id == form_type_id,
            ProcessingJob.status.in_(("pending", "running")),
        )
        .count()
    )
    if active_jobs:
        raise HTTPException(409, "Cannot delete form type while jobs are running")

    forms = db.query(Form).filter(Form.form_type_id == form_type_id).all()
    samples = (
        db.query(TemplateSample)
        .filter(TemplateSample.form_type_id == form_type_id)
        .all()
    )
    images_root = settings.images_dir.resolve()
    cleanup_paths: set[Path] = set()
    for form in forms:
        cleanup_paths.update(collect_related_image_paths(form.raw_image_path, images_root))
        cleanup_paths.update(collect_related_image_paths(form.processed_image_path, images_root))
    for sample in samples:
        cleanup_paths.update(collect_related_image_paths(sample.image_path, images_root))
        cleanup_paths.update(collect_related_image_paths(sample.processed_path, images_root))

    form_ids = [f.id for f in forms]
    corrections_deleted = 0
    if form_ids:
        corrections_deleted = (
            db.query(Correction)
            .filter(Correction.form_id.in_(form_ids))
            .delete(synchronize_session=False)
        )
    forms_deleted = (
        db.query(Form).filter(Form.id.in_(form_ids)).delete(synchronize_session=False)
        if form_ids
        else 0
    )

    samples_deleted = (
        db.query(TemplateSample)
        .filter(TemplateSample.form_type_id == form_type_id)
        .delete(synchronize_session=False)
    )
    templates_deleted = (
        db.query(Template)
        .filter(Template.form_type_id == form_type_id)
        .delete(synchronize_session=False)
    )
    jobs_deleted = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.form_type_id == form_type_id)
        .delete(synchronize_session=False)
    )
    db.delete(ft)
    db.commit()
    files_deleted = safe_unlink_paths(cleanup_paths, images_root)
    return {
        "ok": True,
        "deleted_id": form_type_id,
        "forms_deleted": forms_deleted,
        "samples_deleted": samples_deleted,
        "templates_deleted": templates_deleted,
        "corrections_deleted": corrections_deleted,
        "jobs_deleted": jobs_deleted,
        "files_deleted": files_deleted,
    }
