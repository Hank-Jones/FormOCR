import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Correction, Form, FormType, ProcessingJob, Template, TemplateSample
from app.db.session import get_db
from app.schemas.common import FormTypeCreate, FormTypeOut, FormTypeUpdate
from app.services.field_styles import parse_field_styles

router = APIRouter(prefix="/form-types", tags=["form-types"])


def _form_type_out(ft: FormType) -> FormTypeOut:
    return FormTypeOut(
        id=ft.id,
        name=ft.name,
        version=ft.version,
        status=ft.status,
        anchor_keywords=json.loads(ft.anchor_keywords) if ft.anchor_keywords else None,
        field_styles=parse_field_styles(ft.field_styles_json),
        created_at=ft.created_at,
    )


@router.get("", response_model=list[FormTypeOut])
def list_form_types(db: Session = Depends(get_db)):
    items = db.query(FormType).order_by(FormType.created_at.desc()).all()
    return [_form_type_out(ft) for ft in items]


@router.post("", response_model=FormTypeOut)
def create_form_type(body: FormTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(FormType).filter(FormType.name == body.name).first()
    if existing:
        raise HTTPException(400, "Form type name already exists")
    ft = FormType(name=body.name, status="draft")
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
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Name is required")
        existing = (
            db.query(FormType)
            .filter(FormType.name == name, FormType.id != form_type_id)
            .first()
        )
        if existing:
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
            "fields_json": json.loads(t.fields_json),
        }
        for t in templates
    ]


@router.delete("/{form_type_id}")
def delete_form_type(form_type_id: int, db: Session = Depends(get_db)):
    ft = db.query(FormType).filter(FormType.id == form_type_id).first()
    if not ft:
        raise HTTPException(404, "Form type not found")

    form_ids = [
        f.id for f in db.query(Form.id).filter(Form.form_type_id == form_type_id).all()
    ]
    if form_ids:
        db.query(Correction).filter(Correction.form_id.in_(form_ids)).delete(
            synchronize_session=False
        )
        db.query(Form).filter(Form.id.in_(form_ids)).delete(synchronize_session=False)

    db.query(TemplateSample).filter(TemplateSample.form_type_id == form_type_id).delete(
        synchronize_session=False
    )
    db.query(Template).filter(Template.form_type_id == form_type_id).delete(
        synchronize_session=False
    )
    db.query(ProcessingJob).filter(ProcessingJob.form_type_id == form_type_id).update(
        {ProcessingJob.form_type_id: None}, synchronize_session=False
    )
    db.delete(ft)
    db.commit()
    return {"ok": True, "deleted_id": form_type_id}
