from __future__ import annotations

import json
from dataclasses import dataclass

import cv2
import numpy as np

from app.db.models import FormType, Template
from app.schemas.common import DetectionResult, TemplatePayload
from app.services.ocr import ocr_crop
from app.services.preprocess import load_image
from app.services.template_learn import template_from_json


@dataclass
class _Candidate:
    form_type_id: int
    form_type_name: str
    keyword_score: float
    layout_score: float
    feature_score: float

    @property
    def combined(self) -> float:
        return 0.35 * self.keyword_score + 0.45 * self.layout_score + 0.20 * self.feature_score


def _page_ocr_text(image_path: str, top_ratio: float = 0.35) -> str:
    """OCR upper portion of page for keyword matching."""
    img = load_image(image_path)
    h = img.shape[0]
    region = img[: max(int(h * top_ratio), 1), :]
    text = ocr_crop(region).text
    return text.upper()


def _keyword_score(page_text: str, anchors: list[str]) -> float:
    if not anchors:
        return 0.0
    hits = sum(1 for a in anchors if a.upper() in page_text)
    return hits / len(anchors)


def _layout_similarity(a_path: str, b_path: str, size: int = 128) -> float:
    """Pixel layout similarity on grayscale resize (0–1)."""
    try:
        a = load_image(a_path)
        b = load_image(b_path)
    except ValueError:
        return 0.0
    a_g = cv2.resize(
        cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if len(a.shape) == 3 else a, (size, size)
    )
    b_g = cv2.resize(
        cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if len(b.shape) == 3 else b, (size, size)
    )
    diff = np.abs(a_g.astype(np.float32) - b_g.astype(np.float32))
    return 1.0 - float(diff.sum()) / (255.0 * size * size)


def _orb_similarity(a_path: str, b_path: str) -> float:
    """ORB feature match ratio for same-form detection (0–1)."""
    try:
        a = load_image(a_path)
        b = load_image(b_path)
    except ValueError:
        return 0.0
    a_g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if len(a.shape) == 3 else a
    b_g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if len(b.shape) == 3 else b
    orb = cv2.ORB_create(nfeatures=800)
    kp1, des1 = orb.detectAndCompute(a_g, None)
    kp2, des2 = orb.detectAndCompute(b_g, None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)
    good = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        m, n = pair[0], pair[1]
        if m.distance < 0.75 * n.distance:
            good += 1
    return min(1.0, good / 25.0)


def _best_sample_layout(
    probe_path: str, sample_paths: list[str]
) -> tuple[float, float]:
    """Return best (layout, orb) scores across all reference samples."""
    layout = 0.0
    feature = 0.0
    for ref in sample_paths:
        if not ref or ref == probe_path:
            continue
        layout = max(layout, _layout_similarity(probe_path, ref))
        feature = max(feature, _orb_similarity(probe_path, ref))
    return layout, feature


def detect_form_type(
    image_path: str,
    form_types: list[FormType],
    templates: dict[int, Template],
    sample_paths: dict[int, list[str]] | None = None,
    threshold: float = 0.20,
) -> DetectionResult:
    published = [ft for ft in form_types if templates.get(ft.id)]
    if len(published) == 1:
        ft = published[0]
        return DetectionResult(
            form_type_id=ft.id,
            form_type_name=ft.name,
            score=1.0,
            method="single_published_type",
        )

    page_text = _page_ocr_text(image_path)
    candidates: list[_Candidate] = []

    for ft in form_types:
        if ft.id not in templates:
            continue

        anchors: list[str] = []
        if ft.anchor_keywords:
            anchors = json.loads(ft.anchor_keywords)
        tmpl = templates[ft.id]
        payload = template_from_json(tmpl.fields_json)
        if payload.anchors:
            anchors = list({*anchors, *payload.anchors})
        for _key, field in payload.fields.items():
            if field.label:
                token = "".join(c for c in field.label.upper() if c.isalnum())
                if len(token) >= 3:
                    anchors.append(token)

        kw = _keyword_score(page_text, anchors)

        refs: list[str] = []
        if sample_paths and ft.id in sample_paths:
            refs = sample_paths[ft.id]
        layout, feature = _best_sample_layout(image_path, refs)

        candidates.append(
            _Candidate(ft.id, ft.name, kw, layout, feature)
        )

    if not candidates:
        return DetectionResult(
            form_type_id=None, form_type_name=None, score=0.0, method="no_templates"
        )

    best = max(candidates, key=lambda c: c.combined)
    if best.combined < threshold:
        return DetectionResult(
            form_type_id=None,
            form_type_name=None,
            score=best.combined,
            method="below_threshold",
        )
    return DetectionResult(
        form_type_id=best.form_type_id,
        form_type_name=best.form_type_name,
        score=best.combined,
        method="keyword_layout_features",
    )
