"""Named value lists (TypeA → AA, BB, CC) for constrained OCR correction."""

from __future__ import annotations

import json
import re
from difflib import get_close_matches

from app.schemas.common import TemplateField, TemplatePayload
from app.services.multiline import effective_line_count, multiline_ocr_hint


def parse_field_styles(raw: str | None) -> dict[str, list[str]]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, vals in data.items():
        key = str(name).strip()
        if not key:
            continue
        if isinstance(vals, list):
            items = [str(v).strip() for v in vals if str(v).strip()]
        elif isinstance(vals, str):
            items = [p.strip() for p in re.split(r"[,;\n]+", vals) if p.strip()]
        else:
            continue
        if items:
            out[key] = items
    return out


def allowed_values_for_field(
    field: TemplateField | None,
    styles: dict[str, list[str]],
) -> list[str]:
    if not field:
        return []
    if field.allowed_values:
        return list(field.allowed_values)
    if field.style_key and field.style_key in styles:
        return list(styles[field.style_key])
    return []


def snap_to_allowed(text: str, allowed: list[str]) -> tuple[str, bool]:
    """Pick closest allowed value; returns (value, was_snapped)."""
    raw = (text or "").strip()
    if not allowed:
        return raw, False
    if not raw:
        return allowed[0] if len(allowed) == 1 else "", False

    for a in allowed:
        if raw == a:
            return a, False
        if raw.lower() == a.lower():
            return a, True

    # Substring / containment (OCR often adds spaces)
    compact = re.sub(r"\s+", "", raw)
    for a in allowed:
        ac = re.sub(r"\s+", "", a)
        if compact == ac or ac in compact or compact in ac:
            return a, True

    match = get_close_matches(raw, allowed, n=1, cutoff=0.45)
    if match:
        return match[0], True
    match = get_close_matches(compact, [re.sub(r"\s+", "", a) for a in allowed], n=1, cutoff=0.5)
    if match:
        for a in allowed:
            if re.sub(r"\s+", "", a) == match[0]:
                return a, True
    return raw, False


def apply_field_styles_to_validated(
    validated: dict[str, object],
    confidence: dict[str, float],
    template: TemplatePayload,
    styles: dict[str, list[str]],
) -> None:
    for key, value in list(validated.items()):
        field = template.fields.get(key)
        allowed = allowed_values_for_field(field, styles)
        if not allowed:
            continue
        snapped, did = snap_to_allowed(str(value), allowed)
        if did and snapped:
            validated[key] = snapped
            confidence[key] = max(confidence.get(key, 0.0), 0.92)


def style_hint_for_ocr(field: TemplateField, styles: dict[str, list[str]]) -> str:
    parts: list[str] = []
    n = effective_line_count(field)
    if n:
        parts.append(multiline_ocr_hint(n))
    allowed = allowed_values_for_field(field, styles)
    if allowed:
        opts = ", ".join(f'"{a}"' for a in allowed[:24])
        extra = f" (and {len(allowed) - 24} more)" if len(allowed) > 24 else ""
        parts.append(f"Allowed values ONLY: {opts}{extra}.")
    return " ".join(parts)
