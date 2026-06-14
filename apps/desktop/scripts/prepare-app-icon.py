#!/usr/bin/env python3
"""Prepare the committed app-icon source (square 1024) for Tauri icon generation."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "assets" / "app" / "app-icon.png"
OUT = ROOT / "src-tauri" / "app-icon.png"
ICO_OUT = ROOT / "src-tauri" / "icons" / "icon.ico"
TARGET = 1024
WIN_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def center_crop_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def prepare_master_png() -> Image.Image | None:
    if not SOURCE.is_file():
        print(f"Missing app icon source: {SOURCE}", file=sys.stderr)
        print("Add a square PNG at src/assets/app/app-icon.png (FormOCR app icon only).", file=sys.stderr)
        return None

    im = Image.open(SOURCE).convert("RGBA")
    im = center_crop_square(im)
    if im.size[0] != TARGET:
        im = im.resize((TARGET, TARGET), Image.Resampling.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, "PNG", optimize=True)
    print(f"Prepared {OUT} ({TARGET}x{TARGET}) from {SOURCE}")
    return im


def write_windows_ico(im: Image.Image, ico_path: Path) -> None:
    """Multi-size ICO for Windows shell, taskbar, and shortcuts."""
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(s, s) for s in WIN_ICO_SIZES]
    im.save(ico_path, format="ICO", sizes=sizes)
    print(f"Wrote {ico_path} ({len(sizes)} sizes)")


def finalize_windows_ico() -> int:
    if not OUT.is_file():
        print(f"Missing {OUT}; run prepare-app-icon first", file=sys.stderr)
        return 1
    im = Image.open(OUT).convert("RGBA")
    write_windows_ico(im, ICO_OUT)
    return 0


def main() -> int:
    if prepare_master_png() is None:
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ico-only":
        raise SystemExit(finalize_windows_ico())
    raise SystemExit(main())
