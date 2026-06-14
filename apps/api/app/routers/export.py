import csv
import json
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.db.models import Form
from app.db.session import get_db

router = APIRouter(prefix="/export", tags=["export"])


def _query_forms(
    db: Session,
    form_type_id: int | None,
    review_status: str | None,
    since: datetime | None,
) -> list[Form]:
    q = db.query(Form).order_by(Form.created_at.desc())
    if form_type_id:
        q = q.filter(Form.form_type_id == form_type_id)
    if review_status:
        q = q.filter(Form.review_status == review_status)
    if since:
        q = q.filter(Form.created_at >= since)
    return q.all()


def _loads_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _display_fields(form: Form) -> dict[str, str]:
    corrected = _loads_obj(form.corrected_json)
    validated = _loads_obj(form.validated_json)
    extracted = _loads_obj(form.extracted_json)
    keys = list(dict.fromkeys([*corrected.keys(), *validated.keys(), *extracted.keys()]))
    out: dict[str, str] = {}
    for key in keys:
        corrected_value = corrected.get(key)
        validated_value = validated.get(key)
        extracted_value = extracted.get(key)
        if corrected_value not in (None, ""):
            out[key] = str(corrected_value)
        elif validated_value not in (None, ""):
            out[key] = str(validated_value)
        elif isinstance(extracted_value, dict) and extracted_value.get("text") not in (None, ""):
            out[key] = str(extracted_value["text"])
    return out


def _row_data(form: Form) -> dict[str, Any]:
    return {
        "form_id": form.id,
        "form_type": form.form_type.name if form.form_type else "",
        "status": form.review_status,
        "created": form.created_at.date().isoformat(),
        **_display_fields(form),
    }


def _parse_columns(columns: str | None) -> list[str]:
    if not columns:
        return []
    return [col.strip() for col in columns.split(",") if col.strip()]


def _columns(rows: list[dict[str, Any]], columns: str | None = None) -> list[str]:
    requested = _parse_columns(columns)
    keys: list[str] = []
    for key in requested:
        if any(key in row for row in rows) and key not in keys:
            keys.append(key)
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys


@router.get("/json")
def export_json(
    form_type_id: int | None = None,
    review_status: str | None = Query(None),
    columns: str | None = Query(None),
    db: Session = Depends(get_db),
):
    forms = _query_forms(db, form_type_id, review_status, None)
    rows = [_row_data(f) for f in forms]
    keys = _columns(rows, columns)
    return [{key: row.get(key, "") for key in keys} for row in rows]


@router.get("/csv")
def export_csv(
    form_type_id: int | None = None,
    review_status: str | None = None,
    columns: str | None = Query(None),
    db: Session = Depends(get_db),
):
    forms = _query_forms(db, form_type_id, review_status, None)
    rows = [_row_data(f) for f in forms]
    if not rows:
        return Response(content="", media_type="text/csv")
    keys = _columns(rows, columns)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=formocr_export.csv"},
    )


@router.get("/xlsx")
def export_xlsx(
    form_type_id: int | None = None,
    review_status: str | None = None,
    columns: str | None = Query(None),
    db: Session = Depends(get_db),
):
    forms = _query_forms(db, form_type_id, review_status, None)
    rows = [_row_data(f) for f in forms]
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    if rows:
        keys = _columns(rows, columns)
        ws.append(keys)
        for r in rows:
            ws.append([r.get(k, "") for k in keys])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=formocr_export.xlsx"},
    )
