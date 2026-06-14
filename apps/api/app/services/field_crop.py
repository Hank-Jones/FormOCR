"""Crop template field regions from form page images."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.schemas.common import FieldType
from app.services.preprocess import load_image
from app.schemas.common import TemplatePayload
from app.services.template_learn import bbox_on_processed_page, denormalize_bbox


def pad_ratio_for_field(field_type: FieldType | str) -> float:
    if field_type == FieldType.date or field_type == "date":
        return 0.28
    return 0.12


def crop_field_from_image(
    image: np.ndarray,
    bbox_norm: list[float],
    *,
    pad_ratio: float | None = None,
    field_type: FieldType | str = FieldType.custom,
    template: TemplatePayload | None = None,
) -> np.ndarray:
    if image.size == 0:
        return np.array([])
    if pad_ratio is None:
        pad_ratio = pad_ratio_for_field(field_type)
    h, w = image.shape[:2]
    box = bbox_norm
    if template is not None:
        box = bbox_on_processed_page(bbox_norm, template, w, h)
    x, y, bw, bh = denormalize_bbox(box, w, h)
    pad_w = int(bw * pad_ratio)
    pad_h = int(bh * pad_ratio)
    x1 = max(0, x - pad_w)
    y1 = max(0, y - pad_h)
    x2 = min(w, x + bw + pad_w)
    y2 = min(h, y + bh + pad_h)
    if x2 <= x1 or y2 <= y1:
        return np.array([])
    return image[y1:y2, x1:x2]


def encode_crop_jpeg(crop: np.ndarray, *, quality: int = 88) -> bytes:
    if crop.size == 0:
        raise ValueError("empty crop")
    if len(crop.shape) == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


def crop_field_from_paths(
    image_path: str | Path,
    bbox_norm: list[float],
    *,
    field_type: FieldType | str = FieldType.custom,
    pad_ratio: float | None = None,
    template: TemplatePayload | None = None,
) -> np.ndarray:
    return crop_field_from_image(
        load_image(image_path),
        bbox_norm,
        pad_ratio=pad_ratio,
        field_type=field_type,
        template=template,
    )
