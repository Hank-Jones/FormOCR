# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

block_cipher = None
api_dir = Path(SPECPATH)

_bundle_datas = []
_bundle_binaries = []
_hidden = []

for _pkg in ("paddleocr", "paddle"):
    try:
        _d, _b, _h = collect_all(_pkg)
        _bundle_datas += _d
        _bundle_binaries += _b
        _hidden += _h
    except Exception:
        pass

for _pkg in ("Cython", "skimage", "imgaug"):
    try:
        _bundle_datas += collect_data_files(_pkg)
    except Exception:
        pass

for _pkg in (
    "imageio",
    "imgaug",
    "scikit-image",
    "shapely",
    "pyclipper",
    "lxml",
    "openpyxl",
    "paddleocr",
    "paddlepaddle",
):
    try:
        _bundle_datas += copy_metadata(_pkg)
    except Exception:
        pass

_hidden += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "cv2",
    "fitz",
    "Cython",
    "Cython.Compiler",
    "Cython.Compiler.Code",
]

a = Analysis(
    [str(api_dir / "run.py")],
    pathex=[str(api_dir)],
    binaries=_bundle_binaries,
    datas=_bundle_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="api-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="api-server",
)
