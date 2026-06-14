"""Track preprocess geometry so template bboxes stay aligned with the processed page."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _affine3x3(affine_2x3: np.ndarray) -> np.ndarray:
    m = np.eye(3, dtype=np.float64)
    m[:2, :] = affine_2x3
    return m


def _rotate_matrix_cw(degrees: int, w: int, h: int) -> tuple[np.ndarray, int, int]:
    """Clockwise rotation matrix mapping source (w×h) pixel coords to destination."""
    if degrees == 0:
        return np.eye(3, dtype=np.float64), w, h
    if degrees == 90:
        # (x, y) → (y, w - 1 - x); destination size h×w
        m = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, w - 1.0], [0.0, 0.0, 1.0]])
        return m, h, w
    if degrees == 180:
        m = np.array([[-1.0, 0.0, w - 1.0], [0.0, -1.0, h - 1.0], [0.0, 0.0, 1.0]])
        return m, w, h
    if degrees == 270:
        # (x, y) → (h - 1 - y, x); destination size h×w
        m = np.array([[0.0, -1.0, h - 1.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        return m, h, w
    raise ValueError(f"Unsupported rotation: {degrees}")


@dataclass
class PreprocessTransform:
    """
    Maps pixel coordinates from the original upload (before preprocess)
    to the final processed page image.

    Compose order matches preprocess: orient → deskew → content align.
    """

    src_w: int
    src_h: int
    dst_w: int
    dst_h: int
    matrix: np.ndarray = field(default_factory=lambda: np.eye(3, dtype=np.float64))

    @classmethod
    def identity(cls, w: int, h: int) -> PreprocessTransform:
        return cls(src_w=w, src_h=h, dst_w=w, dst_h=h)

    def apply_point(self, x: float, y: float) -> tuple[float, float]:
        v = self.matrix @ np.array([x, y, 1.0], dtype=np.float64)
        return float(v[0]), float(v[1])

    def apply_bbox_norm(self, bbox: list[float]) -> list[float]:
        """Transform normalized bbox (source image) → normalized bbox (processed image)."""
        x, y, bw, bh = bbox
        corners = [
            (x * self.src_w, y * self.src_h),
            ((x + bw) * self.src_w, y * self.src_h),
            ((x + bw) * self.src_w, (y + bh) * self.src_h),
            (x * self.src_w, (y + bh) * self.src_h),
        ]
        pts = [self.apply_point(px, py) for px, py in corners]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1 = max(0.0, min(float(self.dst_w), min(xs)))
        y1 = max(0.0, min(float(self.dst_h), min(ys)))
        x2 = max(0.0, min(float(self.dst_w), max(xs)))
        y2 = max(0.0, min(float(self.dst_h), max(ys)))
        if x2 <= x1 or y2 <= y1:
            return [0.0, 0.0, 0.01, 0.01]
        return [
            x1 / self.dst_w,
            y1 / self.dst_h,
            (x2 - x1) / self.dst_w,
            (y2 - y1) / self.dst_h,
        ]

    def append_rotate_cw(self, degrees: int) -> None:
        step, new_w, new_h = _rotate_matrix_cw(degrees, self.dst_w, self.dst_h)
        self.matrix = step @ self.matrix
        self.dst_w, self.dst_h = new_w, new_h

    def append_affine(self, affine_2x3: np.ndarray, *, new_w: int, new_h: int) -> None:
        self.matrix = _affine3x3(affine_2x3) @ self.matrix
        self.dst_w, self.dst_h = new_w, new_h

    def append_translate(self, dx: float, dy: float) -> None:
        t = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])
        self.matrix = t @ self.matrix

    def to_dict(self) -> dict:
        return {
            "src_w": self.src_w,
            "src_h": self.src_h,
            "dst_w": self.dst_w,
            "dst_h": self.dst_h,
            "matrix": self.matrix.round(6).tolist(),
        }


def map_bbox_to_processed_page(
    bbox_norm: list[float],
    *,
    page_w: int,
    page_h: int,
    template_ref_w: int | None = None,
    template_ref_h: int | None = None,
    page_transform: PreprocessTransform | None = None,
    template_transform: PreprocessTransform | None = None,
) -> list[float]:
    """
    Return bbox_norm usable on the processed page image.

    - Template bboxes stored in processed-sample space (reference_size): use as-is
      when page matches reference aspect (optional scale).
    - Template bboxes on raw sample + template_transform: map raw → template processed,
      then scale to page if reference dims differ.
    - page_transform alone: map raw template bbox through form preprocess.
    """
    if page_transform is not None and template_transform is not None:
        # raw template corners → template processed
        return template_transform.apply_bbox_norm(bbox_norm)

    if page_transform is not None:
        return page_transform.apply_bbox_norm(bbox_norm)

    if template_ref_w and template_ref_h and page_w and page_h:
        # Bboxes are normalized in processed-page space, so no extra scaling.
        return bbox_norm

    return bbox_norm
