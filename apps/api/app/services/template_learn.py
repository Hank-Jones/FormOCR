from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

import numpy as np

from app.schemas.common import AnnotationField, FieldType, TemplateField, TemplatePayload
from app.services.ocr import ocr_crop, uses_qwen_only
from app.services.preprocess import load_image


def _mad_threshold(values: list[float], k: float = 3.0) -> float:
    if len(values) < 2:
        return 1.0
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    return k * (mad or 0.01)


def aggregate_annotations(
    samples: list[list[AnnotationField]],
    form_type_name: str,
    version: int,
) -> TemplatePayload:
    by_key: dict[str, list[list[float]]] = defaultdict(list)
    field_types: dict[str, FieldType] = {}
    labels: dict[str, str] = {}
    style_keys: dict[str, str | None] = {}
    allowed_map: dict[str, list[str] | None] = {}
    line_counts: dict[str, int | None] = {}

    for sample_fields in samples:
        for f in sample_fields:
            by_key[f.key].append(f.bbox_norm)
            field_types[f.key] = f.field_type
            labels[f.key] = f.label
            style_keys[f.key] = f.style_key
            allowed_map[f.key] = f.allowed_values
            if f.line_count and f.line_count >= 2:
                prev = line_counts.get(f.key)
                line_counts[f.key] = max(prev or 0, f.line_count)

    fields: dict[str, TemplateField] = {}
    for key, boxes in by_key.items():
        arr = np.array(boxes)
        median = np.median(arr, axis=0).tolist()
        deviations = np.max(np.abs(arr - median), axis=0)
        tolerance = float(max(deviations.max(), 0.01))
        fields[key] = TemplateField(
            bbox_norm=[round(x, 4) for x in median],
            field_type=field_types.get(key, FieldType.custom),
            tolerance=round(tolerance, 4),
            label=labels.get(key),
            style_key=style_keys.get(key),
            allowed_values=allowed_map.get(key),
            line_count=line_counts.get(key),
        )

    return TemplatePayload(
        form_type=form_type_name,
        version=version,
        fields=fields,
        anchors=[],
        field_styles={},
    )


def _clean_anchor_token(text: str) -> str:
    """Keep Latin digits/letters and CJK/Japanese kana for anchor tokens."""
    t = (text or "").strip()
    if not t:
        return ""
    parts: list[str] = []
    for c in t:
        o = ord(c)
        if c.isalnum():
            parts.append(c)
        elif 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7A3 or 0x3040 <= o <= 0x30FF:
            parts.append(c)
    return "".join(parts)


def _anchors_from_labels(
    field_labels: list[str] | None,
    field_keys: list[str] | None = None,
    *,
    min_len: int = 1,
    limit: int = 15,
) -> list[str]:
    """Fast anchors for publish — no VLM/Paddle (avoids blocking on Ollama)."""
    from collections import Counter

    tokens: Counter[str] = Counter()
    for label in field_labels or []:
        cleaned = _clean_anchor_token(label)
        if len(cleaned) >= min_len:
            tokens[cleaned] += 3
    for key in field_keys or []:
        cleaned = _clean_anchor_token(key)
        if len(cleaned) >= min_len:
            tokens[cleaned] += 2
    return [t for t, _ in tokens.most_common(limit)]


def extract_anchor_keywords(
    image_paths: list[str],
    field_labels: list[str] | None = None,
    field_keys: list[str] | None = None,
    header_ratio: float = 0.25,
    min_len: int = 3,
) -> list[str]:
    from collections import Counter

    if uses_qwen_only():
        return _anchors_from_labels(
            field_labels,
            field_keys,
            min_len=1,
            limit=15,
        )

    tokens: Counter[str] = Counter()
    for path in image_paths:
        try:
            img = load_image(path)
            h = img.shape[0]
            header = img[: int(h * header_ratio), :]
            text = ocr_crop(header, is_date=False).text
            for word in text.upper().split():
                cleaned = "".join(c for c in word if c.isalnum())
                if len(cleaned) >= min_len:
                    tokens[cleaned] += 1
        except Exception:
            continue
    if field_labels:
        for label in field_labels:
            cleaned = _clean_anchor_token(label)
            if len(cleaned) >= min_len:
                tokens[cleaned] += 3
    for key in field_keys or []:
        cleaned = _clean_anchor_token(key)
        if len(cleaned) >= min_len:
            tokens[cleaned] += 2
    return [t for t, _ in tokens.most_common(15)]


def template_to_json(template: TemplatePayload) -> str:
    return json.dumps(template.model_dump(), default=str)


def template_from_json(data: str) -> TemplatePayload:
    return TemplatePayload.model_validate(json.loads(data))


def denormalize_bbox(
    bbox_norm: list[float], width: int, height: int
) -> tuple[int, int, int, int]:
    x, y, w, h = bbox_norm
    return (
        int(x * width),
        int(y * height),
        int(w * width),
        int(h * height),
    )


def bbox_on_processed_page(
    bbox_norm: list[float],
    template: TemplatePayload,
    page_w: int,
    page_h: int,
) -> list[float]:
    """Map template bbox (processed-sample space) onto a processed form page."""
    from app.services.preprocess_transform import map_bbox_to_processed_page

    ref_w, ref_h = page_w, page_h
    if template.reference_size and len(template.reference_size) >= 2:
        ref_w, ref_h = int(template.reference_size[0]), int(template.reference_size[1])
    return map_bbox_to_processed_page(
        bbox_norm,
        page_w=page_w,
        page_h=page_h,
        template_ref_w=ref_w,
        template_ref_h=ref_h,
    )
