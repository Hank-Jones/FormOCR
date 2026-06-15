"""Multiline field OCR hints and post-VLM text normalization."""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.schemas.common import TemplateField


def effective_line_count(field: TemplateField | None) -> int | None:
    if not field or not field.line_count:
        return None
    n = int(field.line_count)
    return n if n >= 2 else None


def is_multiline_field(field: TemplateField | None) -> bool:
    return effective_line_count(field) is not None


def multiline_ocr_hint(line_count: int) -> str:
    return (
        f" MULTILINE: exactly {line_count} lines top-to-bottom; "
        f"output {line_count} lines separated by newline (\\n), one line per row."
    )


def multiline_ocr_prompt(*, line_count: int, lang: str, is_date: bool = False) -> str:
    lang_hint = {"ko": "Korean", "ch": "Chinese", "en": "English"}.get(lang, lang)
    if is_date:
        return (
            f"You read handwritten {lang_hint} dates on a form.\n"
            f"This box has {line_count} date lines stacked vertically.\n"
            f"Output exactly {line_count} lines separated by newlines, top to bottom.\n"
            "Output ONLY the text. No labels or explanation.\n"
        )
    return (
        f"You read handwritten {lang_hint} text on a form field.\n"
        f"The field has exactly {line_count} lines of text, stacked top to bottom.\n"
        "Read each line in order. Do not merge lines or add words.\n"
        f"Output exactly {line_count} lines separated by newline characters (\\n).\n"
        "Output ONLY the text — no row numbers, labels, or explanation.\n"
        "If a line is blank or unreadable, output an empty line for that row.\n"
    )


def _split_single_line(text: str, line_count: int) -> list[str]:
    """Heuristics when the VLM returns one line instead of many."""
    t = text.strip()
    if not t:
        return [""] * line_count

    numbered = re.split(r"\s*(?=\d{1,2}[\.\):\-]\s+)", t)
    numbered = [re.sub(r"^\d{1,2}[\.\):\-]\s*", "", p).strip() for p in numbered if p.strip()]
    if len(numbered) >= line_count:
        return numbered[:line_count]

    for sep in (" | ", " / ", " // ", " · ", " • "):
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if len(parts) >= line_count:
                return parts[:line_count]

    if line_count == 2 and "  " in t:
        parts = [p.strip() for p in re.split(r"\s{2,}", t) if p.strip()]
        if len(parts) >= 2:
            return parts[:line_count]

    return [t]


def _merge_to_line_count(lines: list[str], line_count: int) -> list[str]:
    if len(lines) <= line_count:
        return lines
    while len(lines) > line_count:
        # Merge the pair of adjacent lines with the smallest combined length.
        best_i = 0
        best_len = len(lines[0]) + len(lines[1])
        for i in range(len(lines) - 1):
            pair_len = len(lines[i]) + len(lines[i + 1])
            if pair_len < best_len:
                best_len = pair_len
                best_i = i
        merged = f"{lines[best_i]} {lines[best_i + 1]}".strip()
        lines = lines[:best_i] + [merged] + lines[best_i + 2 :]
    return lines


def normalize_multiline_text(text: str, line_count: int | None) -> str:
    """Shape VLM output to the expected number of lines."""
    if not text:
        return ""
    if not line_count or line_count < 2:
        return text.strip()

    t = text.replace("\\n", "\n").replace("\\r\\n", "\n").replace("\r\n", "\n")
    t = t.replace("\r", "\n").replace("\u2028", "\n")
    # VLM sometimes uses slash or pipe instead of newlines inside JSON strings.
    if "\n" not in t and line_count > 1:
        for sep in ("|", "/", "·", "•"):
            if sep in t and t.count(sep) >= line_count - 1:
                parts = [p.strip() for p in t.split(sep)]
                if len(parts) >= line_count:
                    t = "\n".join(parts[:line_count])
                    break

    lines = [ln.strip() for ln in t.split("\n")]
    while lines and not lines[-1]:
        lines.pop()

    if len(lines) == 1:
        lines = _split_single_line(lines[0], line_count)
    elif len(lines) > line_count:
        lines = _merge_to_line_count(lines, line_count)

    while len(lines) < line_count:
        lines.append("")

    return "\n".join(lines[:line_count])


def apply_multiline_to_result(text: str, field: TemplateField | None) -> str:
    n = effective_line_count(field)
    if not n:
        return text
    return normalize_multiline_text(text, n)


def draw_line_guides(crop: np.ndarray, line_count: int) -> np.ndarray:
    """Light horizontal guides so the VLM can see row boundaries."""
    if line_count < 2 or crop.size == 0:
        return crop
    out = crop.copy()
    if len(out.shape) == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    h = out.shape[0]
    for i in range(1, line_count):
        y = int(h * i / line_count)
        cv2.line(out, (0, y), (out.shape[1] - 1, y), (210, 210, 210), 1)
    return out


def multiline_crop_min_height(line_count: int) -> int:
    return max(120, min(400, 44 * line_count))
