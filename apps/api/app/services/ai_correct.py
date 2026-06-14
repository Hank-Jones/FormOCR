from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import settings
from app.schemas.common import FieldExtraction, TemplatePayload
from app.schemas.field_types import FieldType

_EMPTY_EXTRACTION = FieldExtraction()

# Identity / structured fields: never send to LLM (OCR + rules are more reliable).
AI_NEVER_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.name,
        FieldType.id_number,
        FieldType.gender,
        FieldType.date,
        FieldType.phone,
        FieldType.number,
        FieldType.email,
        FieldType.age,
        FieldType.zip_code,
    }
)

# Only suggest AI when validated confidence is below this.
AI_CONF_THRESHOLD = 0.82


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _digits_core(text: str) -> str:
    return re.sub(r"\D", "", text)


def _change_too_large(before: str, after: str, field_type: FieldType) -> bool:
    if not before or not after:
        return False
    if field_type == FieldType.id_number:
        b, a = _digits_core(before), _digits_core(after)
        if len(b) >= 15 and b != a:
            return True
    if _has_cjk(before) and before != after:
        return True
    if _digits_core(before) and len(_digits_core(before)) >= 11:
        return _digits_core(before) != _digits_core(after)
    return SequenceMatcher(None, before, after).ratio() < 0.72


def _looks_like_id_number(text: str) -> bool:
    return bool(re.search(r"\d{17}[\dXx]", re.sub(r"\s+", "", text)))


def fields_eligible_for_ai(
    validated: dict[str, Any],
    confidence: dict[str, float],
    template: TemplatePayload,
) -> list[str]:
    keys: list[str] = []
    for key, field in template.fields.items():
        if field.field_type in AI_NEVER_TYPES:
            continue
        val = str(validated.get(key, "")).strip()
        if not val:
            continue
        if _looks_like_id_number(val):
            continue
        if confidence.get(key, 0) >= AI_CONF_THRESHOLD:
            continue
        keys.append(key)
    return keys


def merge_ai_corrections(
    validated: dict[str, Any],
    ai_result: dict[str, Any] | None,
    template: TemplatePayload,
    confidence: dict[str, float],
    extractions: dict[str, FieldExtraction],
) -> dict[str, Any]:
    """Apply AI only when it plausibly fixes OCR; never overwrite good reads."""
    out = dict(validated)
    if not ai_result:
        return out
    for key, ai_val in ai_result.items():
        if key not in template.fields or ai_val is None:
            continue
        ft = template.fields[key].field_type
        if ft in AI_NEVER_TYPES:
            continue
        ai_s = str(ai_val).strip()
        base = str(validated.get(key, "")).strip()
        if not ai_s:
            continue
        ocr_s = extractions.get(key, _EMPTY_EXTRACTION).text.strip()
        if confidence.get(key, 0) >= AI_CONF_THRESHOLD:
            continue
        if _change_too_large(base, ai_s, ft):
            continue
        if ocr_s and _change_too_large(ocr_s, ai_s, ft):
            continue
        if _has_cjk(base) and ai_s != base:
            continue
        if _looks_like_id_number(base) or _looks_like_id_number(ocr_s):
            continue
        out[key] = ai_s
    return out


async def check_ollama() -> tuple[bool, bool]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            if r.status_code != 200:
                return False, False
            tags = r.json().get("models", [])
            names = {m.get("name", "") for m in tags}
            model_ok = any(
                settings.ollama_model in n or n.startswith(settings.ollama_model.split(":")[0])
                for n in names
            )
            return True, model_ok
    except Exception:
        return False, False


async def check_ollama_model(model: str) -> tuple[bool, bool]:
    """Check Ollama is reachable and a specific model is present in /api/tags."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            if r.status_code != 200:
                return False, False
            tags = r.json().get("models", [])
            names = {m.get("name", "") for m in tags}
            base = model.split(":")[0]
            model_ok = any(model in n or n.startswith(base) for n in names)
            return True, model_ok
    except Exception:
        return False, False


async def correct_fields(
    ocr_values: dict[str, Any],
    field_keys: list[str],
    field_types: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (parsed_json_or_none, error_message_or_none)."""
    model = settings.ollama_model
    if not settings.ai_correction_enabled:
        return None, "AI correction disabled in settings"
    ollama_ok, model_ok = await check_ollama()
    if not ollama_ok:
        return None, f"Ollama not reachable at {settings.ollama_host}"
    if not model_ok:
        return None, f"Text model {model} not loaded in Ollama (needed for AI correction)"

    type_hints = ""
    if field_types:
        type_hints = "\nField types: " + json.dumps(
            {k: field_types[k] for k in field_keys if k in field_types},
            ensure_ascii=False,
        )

    prompt = f"""You fix OCR typos on scanned forms. Rules:
- Change ONLY obvious OCR mistakes (0/O, 1/l/I, missing punctuation). 
- NEVER replace a Chinese name with a different name.
- NEVER change ID numbers, dates, or gender unless fixing a single obvious digit/letter typo.
- If the value is already correct, return it unchanged.
- Do not invent values. Use null only for truly empty unrecoverable fields.
{type_hints}

Return ONLY valid JSON with exactly these keys: {json.dumps(field_keys)}

Input:
{json.dumps(ocr_values, ensure_ascii=False)}

Output JSON:"""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload: dict = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 512},
                "format": "json",
            }
            r = await client.post(
                f"{settings.ollama_host}/api/generate",
                json=payload,
            )
            r.raise_for_status()
            raw = r.json().get("response", "")
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None, f"{model} returned no JSON"
            parsed = json.loads(match.group())
            return {k: parsed.get(k) for k in field_keys if k in parsed}, None
    except Exception as e:
        err = str(e).strip() or repr(e)
        return None, f"{model} error: {err[:300]}"
