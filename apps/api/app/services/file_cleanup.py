from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import settings

logger = logging.getLogger("formocr")

# Current processing names are linked by file stem:
# save_upload() writes <uuid>.pdf, rasterize_pdf() writes <uuid>_pN.png,
# and preprocessing writes <uuid>_pN_proc.png.
_PDF_PAGE_STEM_RE = re.compile(r"^(?P<pdf_stem>.+)_p\d+(?:_proc)?$")


def resolve_image_path(path_str: str | None, images_root: Path | None = None) -> Path | None:
    if not path_str or not str(path_str).strip():
        return None
    root = (images_root or settings.images_dir).resolve()
    try:
        resolved = Path(path_str).resolve()
        resolved.relative_to(root)
    except (ValueError, OSError):
        logger.warning("Skipped file cleanup outside images dir: %s", path_str)
        return None
    return resolved


def _pdf_page_stem(path: Path) -> str | None:
    match = _PDF_PAGE_STEM_RE.match(path.stem)
    if not match:
        return None
    return match.group("pdf_stem")


def _pdf_page_siblings(path: Path, pdf_stem: str) -> set[Path]:
    parent = path.parent
    return {
        parent / f"{pdf_stem}.pdf",
        *parent.glob(f"{pdf_stem}_p*{path.suffix}"),
        *parent.glob(f"{pdf_stem}_p*_proc{path.suffix}"),
    }


def collect_related_image_paths(
    path_str: str | None,
    images_root: Path | None = None,
) -> set[Path]:
    resolved = resolve_image_path(path_str, images_root)
    if resolved is None:
        return set()

    paths = {resolved}
    pdf_stem = _pdf_page_stem(resolved)
    if pdf_stem:
        paths.update(_pdf_page_siblings(resolved, pdf_stem))
    return {
        p
        for p in paths
        if resolve_image_path(str(p), images_root) is not None
    }


def safe_unlink_paths(paths: set[Path], images_root: Path | None = None) -> int:
    files_deleted = 0
    for path in sorted(paths):
        resolved = resolve_image_path(str(path), images_root)
        if resolved is None:
            continue
        if resolved.is_file():
            try:
                resolved.unlink(missing_ok=True)
                files_deleted += 1
            except OSError as exc:
                logger.warning("Could not delete file during cleanup: %s (%s)", resolved, exc)
    return files_deleted
