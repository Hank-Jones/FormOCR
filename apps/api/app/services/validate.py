from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from app.schemas.common import FieldExtraction, TemplatePayload
from app.schemas.field_types import FieldType
from app.services.field_styles import apply_field_styles_to_validated
from app.services.multiline import normalize_multiline_text

_EMPTY_EXTRACTION = FieldExtraction()


def _is_cjk_char(c: str) -> bool:
    return "\u4e00" <= c <= "\u9fff"


def _validate_name(text: str) -> tuple[str, str, float]:
    cleaned = _strip_cn_label_noise(" ".join(text.split()))
    if not cleaned:
        return "", "empty", 0.0
    if any(_is_cjk_char(c) for c in cleaned):
        return cleaned, "ok", 1.0
    alpha = sum(c.isalpha() or c.isspace() for c in cleaned)
    ratio = alpha / max(len(cleaned), 1)
    if ratio < 0.5:
        return cleaned, "low_alpha_ratio", 0.5
    titled = " ".join(w.capitalize() for w in cleaned.split())
    return titled, "ok", 1.0


def _validate_phone(text: str) -> tuple[str, str, float]:
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return text, "too_short", 0.4
    if len(digits) == 10:
        formatted = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return formatted, "ok", 1.0
    if len(digits) == 11 and digits.startswith("1"):
        formatted = f"{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
        return formatted, "ok", 1.0
    return digits, "ok", 0.85


def _normalize_date_ocr(text: str) -> str:
    """Clean ID-card / form dates before parsing (e.g. 02 AUG/AUG 2021, 10 MAA/MAR 1965)."""
    t = text.strip()
    # Chinese ID row: drop label noise and OCR junk before Latin rules
    t = re.sub(r"[#*·•]+", " ", t)
    t = re.sub(r"出生|生年|出年", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"[\u4e00-\u9fff]", t):
        return t
    t = " ".join(t.upper().split())
    # Bilingual month: keep second token (often English) — MAR, AUG, OCT
    bilingual = [
        (r"\bMAA\s*/\s*MAR\b", "MAR"),
        (r"\bMRT\s*/\s*MAR\b", "MAR"),
        (r"\bMEI\s*/\s*MAY\b", "MAY"),
        (r"\bOKT\s*/\s*OCT\b", "OCT"),
        (r"\bAUG\s*/\s*AUG\b", "AUG"),
        (r"\bJUL\s*/\s*JUL\b", "JUL"),
        (r"\bFEB\s*/\s*FEB\b", "FEB"),
        (r"\bJAN\s*/\s*JAN\b", "JAN"),
        (r"\bDEC\s*/\s*DEC\b", "DEC"),
        (r"\bNOV\s*/\s*NOV\b", "NOV"),
        (r"\bSEP\s*/\s*SEP\b", "SEP"),
        (r"\bAPR\s*/\s*APR\b", "APR"),
        (r"\bJUN\s*/\s*JUN\b", "JUN"),
    ]
    for pattern, repl in bilingual:
        t = re.sub(pattern, repl, t)
    # Duplicate month without different langs: AUG/AUG -> AUG
    t = re.sub(r"\b([A-Z]{3,4})\s*/\s*\1\b", r"\1", t)
    # Remove label noise common on ID cards
    t = re.sub(
        r"\b(DATUM\s+VAN\s+AFGIFTE|DATE\s+OF\s+ISSUE|GEBOORTEDATUM|DATE\s+OF\s+BIRTH|"
        r"GELDIG\s+TOT|DATE\s+OF\s+EXPIRY|VAN\s+EXPIRY)\b",
        " ",
        t,
    )
    return " ".join(t.split())


def birth_date_from_cn_id_number(text: str) -> str | None:
    """18-digit Chinese ID embeds birth date at positions 7–14 (YYYYMMDD)."""
    digits = re.sub(r"\s+", "", text)
    m = re.search(r"\d{17}[\dXx]", digits)
    if not m:
        return None
    id18 = m.group(0)[:18].upper()
    ymd = id18[6:14]
    if not ymd.isdigit() or len(ymd) != 8:
        return None
    try:
        dt = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
        if dt.year < 1900 or dt.year > datetime.now().year:
            return None
        return dt.date().isoformat()
    except ValueError:
        return None


def _parse_chinese_date(text: str) -> tuple[str, str, float] | None:
    t = _normalize_date_ocr(text)
    if not t:
        return None

    m = re.search(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        t,
    )
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.date().isoformat(), "ok", 1.0
        except ValueError:
            pass

    # Spaced form: 1991 年 7 月 14 日 (common on ID cards)
    m = re.search(
        r"(\d{4})\s+年\s+(\d{1,2})\s+月\s+(\d{1,2})\s+日",
        t,
    )
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.date().isoformat(), "ok", 1.0
        except ValueError:
            pass

    y = re.search(r"(\d{4})\s*年", t)
    mo = re.search(r"(\d{1,2})\s*月", t)
    d = re.search(r"(\d{1,2})\s*日", t)
    if y and mo and d:
        try:
            dt = datetime(int(y.group(1)), int(mo.group(1)), int(d.group(1)))
            return dt.date().isoformat(), "ok", 0.92
        except ValueError:
            pass

    # Compact digits with markers: 1991年7月14
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})", t)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.date().isoformat(), "ok", 0.9
        except ValueError:
            pass

    return None


def _validate_date(text: str) -> tuple[str, str, float]:
    raw = text.strip()
    if not raw:
        return "", "empty", 0.0
    normalized = _normalize_date_ocr(raw)

    cn = _parse_chinese_date(raw)
    if cn:
        return cn

    # DD MON YYYY (Dutch / EU ID cards)
    m = re.search(
        r"\b(\d{1,2})\s+([A-Z]{3,9})\s+(\d{2,4})\b",
        normalized,
    )
    if m:
        day, mon, year = m.group(1), m.group(2), m.group(3)
        if len(year) == 2:
            year = f"20{year}" if int(year) < 50 else f"19{year}"
        try:
            dt = date_parser.parse(f"{day} {mon} {year}", fuzzy=False)
            return dt.date().isoformat(), "ok", 1.0
        except (ValueError, OverflowError):
            pass

    # ISO-like or numeric
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", normalized)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.date().isoformat(), "ok", 1.0
        except ValueError:
            pass

    # Avoid inventing dates from broken OCR (e.g. 生年7## → today's date).
    has_latin_month = bool(re.search(r"\b[A-Z]{3,9}\b", normalized))
    has_four_digit_year = bool(re.search(r"\b\d{4}\b", normalized))
    if has_latin_month or (has_four_digit_year and not re.search(r"[\u4e00-\u9fff]", raw)):
        try:
            dt = date_parser.parse(normalized, fuzzy=True)
            return dt.date().isoformat(), "ok", 0.85
        except (ValueError, OverflowError):
            pass

    return normalized if normalized else raw, "parse_failed", 0.25


def _validate_number(text: str) -> tuple[str, str, float]:
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not cleaned:
        return text.strip(), "not_numeric", 0.3
    # Long integer strings (ID cards, bank accounts): never use float — IEEE loss at 16+ digits.
    if re.fullmatch(r"\d+", cleaned) and len(cleaned) > 15:
        return cleaned, "ok", 1.0
    if re.fullmatch(r"\d+", cleaned):
        return cleaned, "ok", 1.0
    try:
        val = float(cleaned)
        if val == int(val):
            return str(int(val)), "ok", 1.0
        return str(val), "ok", 1.0
    except ValueError:
        return text, "not_numeric", 0.3


def _validate_email(text: str) -> tuple[str, str, float]:
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    cleaned = text.strip().lower()
    if re.match(pattern, cleaned):
        return cleaned, "ok", 1.0
    return text, "invalid_format", 0.3


def _validate_gender(text: str) -> tuple[str, str, float]:
    cleaned = _strip_cn_label_noise(text)
    if cleaned in ("男", "女", "M", "F"):
        return cleaned, "ok", 1.0
    upper = cleaned.upper()
    for token in ("MALE", "FEMALE", "M", "F", "OTHER", "NON-BINARY"):
        if token in upper.replace(".", ""):
            return cleaned.title(), "ok", 0.9
    return cleaned, "ok", 0.7


def _strip_cn_label_noise(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^[公民身份号码码]+", "", t)
    t = re.sub(r"^住址\s*", "", t)
    t = re.sub(r"^址+", "", t)
    t = re.sub(r"^民族\s*", "", t)
    t = re.sub(r"^性别\s*", "", t)
    t = re.sub(r"^姓名\s*", "", t)
    return t.strip()


def _validate_address(text: str) -> tuple[str, str, float]:
    cleaned = _strip_cn_label_noise(" ".join(text.split()))
    if not cleaned:
        return "", "empty", 0.0
    return cleaned, "ok", 0.95


def _validate_id_number(text: str) -> tuple[str, str, float]:
    compact = re.sub(r"\s+", "", _strip_cn_label_noise(text))
    m = re.search(r"\d{17}[\dXx]", compact)
    if m:
        return m.group(0).upper(), "ok", 1.0
    digits = re.sub(r"[^\dXx]", "", compact)
    if len(digits) >= 15:
        return digits.upper(), "ok", 0.9
    return text.strip(), "ok", 0.85 if digits else 0.3


def _validate_string(text: str) -> tuple[str, str, float]:
    return " ".join(text.split()).strip(), "ok", 0.95


def _validate_multiline(text: str, line_count: int) -> tuple[str, str, float]:
    normalized = normalize_multiline_text(text, line_count)
    lines = normalized.split("\n")
    filled = sum(1 for ln in lines if ln.strip())
    if filled >= line_count:
        return normalized, "ok", 0.95
    if filled > 0:
        return normalized, "ok", 0.85
    return normalized, "empty", 0.3


# Map specialized types to validator functions
_VALIDATORS: dict[FieldType, Any] = {
    FieldType.name: _validate_name,
    FieldType.phone: _validate_phone,
    FieldType.date: _validate_date,
    FieldType.number: _validate_number,
    FieldType.email: _validate_email,
    FieldType.age: _validate_number,
    FieldType.gender: _validate_gender,
    FieldType.location: _validate_string,
    FieldType.string: _validate_string,
    FieldType.college_name: _validate_name,
    FieldType.school_name: _validate_name,
    FieldType.company_name: _validate_name,
    FieldType.hobby: _validate_string,
    FieldType.address: _validate_address,
    FieldType.city: _validate_name,
    FieldType.country: _validate_name,
    FieldType.zip_code: _validate_string,
    FieldType.id_number: _validate_id_number,
    FieldType.occupation: _validate_string,
    FieldType.department: _validate_string,
    FieldType.title: _validate_string,
    FieldType.custom: _validate_string,
}


def validate_field(
    key: str,
    extraction: FieldExtraction,
    field_type: FieldType,
    *,
    line_count: int | None = None,
) -> dict[str, Any]:
    text = extraction.text
    conf = extraction.confidence
    if line_count and line_count >= 2:
        value, status, mult = _validate_multiline(text, line_count)
    else:
        fn = _VALIDATORS.get(field_type)
        if fn is None:
            return {
                "value": text.strip(),
                "status": "ok",
                "confidence": conf,
            }
        value, status, mult = fn(text)
    return {
        "value": value,
        "status": status,
        "confidence": min(1.0, conf * mult),
    }


def _apply_cn_id_date_fallback(
    validated: dict[str, Any],
    confidence: dict[str, float],
    extractions: dict[str, FieldExtraction],
    template: TemplatePayload,
) -> None:
    id_text = ""
    for key, field in template.fields.items():
        if field.field_type == FieldType.id_number:
            ext = extractions.get(key, _EMPTY_EXTRACTION)
            id_text = str(validated.get(key) or ext.text)
            break
    birth = birth_date_from_cn_id_number(id_text)
    if not birth:
        return
    for key, field in template.fields.items():
        if field.field_type != FieldType.date:
            continue
        current = str(validated.get(key, ""))
        ok_iso = re.fullmatch(r"\d{4}-\d{2}-\d{2}", current)
        if not ok_iso or confidence.get(key, 0) < 0.75:
            validated[key] = birth
            confidence[key] = max(confidence.get(key, 0), 0.88)


def validate_extraction(
    extractions: dict[str, FieldExtraction],
    template: TemplatePayload,
) -> tuple[dict[str, Any], dict[str, float]]:
    validated: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    for key, ext in extractions.items():
        field_def = template.fields.get(key)
        ft = field_def.field_type if field_def else FieldType.custom
        lc = field_def.line_count if field_def else None
        result = validate_field(key, ext, ft, line_count=lc)
        validated[key] = result["value"]
        confidence[key] = result["confidence"]
    _apply_cn_id_date_fallback(validated, confidence, extractions, template)
    styles = template.field_styles or {}
    apply_field_styles_to_validated(validated, confidence, template, styles)
    return validated, confidence
