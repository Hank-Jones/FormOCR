from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("formocr.ocr")


@dataclass
class OcrCropResult:
    text: str
    confidence: float
    engine: str
    qwen_text: str = ""
    paddle_text: str = ""
    tesseract_text: str = ""
    qwen_error: str = ""


_ocr_instance: Any = None
_ocr_loaded_lang: str | None = None
_ocr_lock = threading.Lock()
_ocr_infer_lock = threading.Lock()
_ocr_ready = False
_ocr_error: str | None = None

_hw_ok: bool | None = None
_hw_checked_at: float = 0.0
_hw_lock = threading.Lock()
_qwen_session_ready = False
_qwen_warm_in_progress = False
_qwen_session_lock = threading.Lock()
_ollama_vision_lock = threading.Lock()
_cpu_mode_cache: tuple[float, bool] | None = None
_HW_CACHE_OK_S = 60.0
_HW_CACHE_MISS_S = 8.0
def _composite_chunk_size(total_crops: int) -> int:
    """Fields per vision call — whole form in one call when under the safe limit."""
    single_max = max(1, int(settings.handwriting_ocr_composite_single_call_max_fields))
    chunk_fields = max(1, int(settings.handwriting_ocr_composite_chunk_fields))
    if total_crops <= single_max:
        return total_crops
    return chunk_fields


def uses_qwen_only() -> bool:
    return (settings.ocr_engine or "qwen").strip().lower() == "qwen"

# UI codes → PaddleOCR lang names
_PADDLE_LANG: dict[str, str] = {
    "ch": "ch",
    "en": "en",
}


def paddle_lang() -> str:
    key = (settings.ocr_lang or "ch").strip().lower()
    return _PADDLE_LANG.get(key, "ch")


def is_qwen_session_ready() -> bool:
    return _qwen_session_ready


def is_qwen_warm_in_progress() -> bool:
    with _qwen_session_lock:
        return _qwen_warm_in_progress


def set_qwen_warm_in_progress(active: bool) -> None:
    global _qwen_warm_in_progress
    with _qwen_session_lock:
        _qwen_warm_in_progress = active


def is_ocr_ready() -> bool:
    """True only after vision warmup finished (splash waits on this for qwen mode)."""
    if uses_qwen_only():
        return _qwen_session_ready
    return _ocr_ready


def ocr_error() -> str | None:
    return _ocr_error


def reset_ocr() -> None:
    """Force reload on next get_ocr() (e.g. after ocr_lang change)."""
    global _ocr_instance, _ocr_loaded_lang, _ocr_ready, _ocr_error
    with _ocr_lock:
        _ocr_instance = None
        _ocr_loaded_lang = None
        _ocr_ready = False
        _ocr_error = None


def _apply_paddle_home() -> None:
    """PaddleOCR 2.x uses ~/.paddleocr by default; point it at FormOCR's model dir."""
    home = str(settings.paddle_home)
    os.environ["PADDLEOCR_HOME"] = home
    os.environ["PADDLE_OCR_BASE_DIR"] = home
    import paddleocr.paddleocr as paddleocr_mod

    base = home if home.endswith(("/", "\\")) else home + os.sep
    paddleocr_mod.BASE_DIR = base


# PP-OCRv4 folder names under paddle_home/whl (must match bundled offline seed)
_PP_OCRV4_MODELS: dict[str, tuple[str, str, str, str]] = {
    # lang -> det_lang, det_dir, rec_lang, rec_dir
    "ch": ("ch", "ch_PP-OCRv4_det_infer", "ch", "ch_PP-OCRv4_rec_infer"),
    "en": ("en", "en_PP-OCRv3_det_infer", "en", "en_PP-OCRv4_rec_infer"),
}
_CLS_DIR = "ch_ppocr_mobile_v2.0_cls_infer"


def _model_bundle_ready(path: Path) -> bool:
    return (path / "inference.pdmodel").is_file() and (path / "inference.pdiparams").is_file()


def _local_paddle_model_kwargs(lang: str) -> dict[str, str]:
    """Use bundled weights by path so offline install never hits ~/.paddleocr or HTTP."""
    spec = _PP_OCRV4_MODELS.get(lang)
    if not spec:
        return {}
    det_lang, det_name, rec_lang, rec_name = spec
    root = settings.paddle_home
    det = root / "whl" / "det" / det_lang / det_name
    rec = root / "whl" / "rec" / rec_lang / rec_name
    cls = root / "whl" / "cls" / _CLS_DIR
    if not (_model_bundle_ready(det) and _model_bundle_ready(rec) and _model_bundle_ready(cls)):
        return {}
    return {
        "det_model_dir": str(det),
        "rec_model_dir": str(rec),
        "cls_model_dir": str(cls),
    }


def get_ocr():
    global _ocr_instance, _ocr_loaded_lang, _ocr_ready, _ocr_error
    lang = paddle_lang()
    with _ocr_lock:
        if _ocr_instance is None or _ocr_loaded_lang != lang:
            settings.ensure_dirs()
            _apply_paddle_home()
            from paddleocr import PaddleOCR

            kwargs: dict[str, Any] = {
                "use_angle_cls": True,
                "lang": lang,
                "show_log": False,
                **_local_paddle_model_kwargs(lang),
            }
            try:
                _ocr_instance = PaddleOCR(device="cpu", **kwargs)
            except TypeError:
                try:
                    _ocr_instance = PaddleOCR(use_gpu=False, **kwargs)
                except TypeError:
                    _ocr_instance = PaddleOCR(**kwargs)
            _ocr_loaded_lang = lang
            _ocr_ready = True
            _ocr_error = None
            logger.info("PaddleOCR loaded lang=%s models=%s", lang, settings.paddle_home)
        return _ocr_instance


def _format_ocr_error(exc: BaseException) -> str:
    msg = str(exc).strip() or repr(exc)
    if "CppSupport.cpp" in msg or "Cython\\Utility" in msg:
        return (
            "OCR engine bundle incomplete (missing Cython files). "
            "Rebuild with: npm run build:installer"
        )
    if "Download from" in msg and "failed" in msg:
        return (
            "OCR models missing or incomplete under "
            f"{settings.paddle_home}. Re-run FormOCR-Setup from a fresh "
            "FormOCR-Offline package (with Chinese PP-OCRv4 in app\\seed\\paddle)."
        )
    if len(msg) > 200:
        return msg[:200] + "..."
    return msg


def warm_ocr() -> None:
    global _ocr_error
    try:
        get_ocr()
    except Exception as e:
        _ocr_error = _format_ocr_error(e)
        logger.warning("PaddleOCR warm-up failed: %s", e, exc_info=True)


def prepare_crop_for_ocr(
    crop: np.ndarray,
    *,
    pad_ratio: float = 0.25,
    min_h: int = 64,
    min_w: int = 120,
) -> np.ndarray:
    """Pad and upscale small field crops so PaddleOCR can read them."""
    if crop.size == 0:
        return crop
    if len(crop.shape) == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    h, w = crop.shape[:2]
    pad_x = max(int(w * pad_ratio), 8)
    pad_y = max(int(h * pad_ratio), 8)
    crop = cv2.copyMakeBorder(
        crop, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_REPLICATE
    )
    h, w = crop.shape[:2]
    scale = max(min_h / max(h, 1), min_w / max(w, 1), 1.0)
    if scale > 1.0:
        crop = cv2.resize(
            crop,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
    return crop


def _parse_ocr_result(result: Any, *, sort_boxes: bool = False) -> tuple[str, float]:
    if not result:
        return "", 0.0
    page = result[0] if isinstance(result, list) and result else result
    if not page:
        return "", 0.0
    segments: list[tuple[float, str, float]] = []
    for line in page:
        if not line:
            continue
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        a, b = line[0], line[1]
        cx = 0.0
        if sort_boxes and isinstance(a, (list, tuple)) and a and isinstance(a[0], (list, tuple)):
            try:
                cx = sum(float(p[0]) for p in a) / len(a)
            except (TypeError, ValueError):
                cx = 0.0
        # det+rec: [box, (text, confidence)]
        if isinstance(b, (list, tuple)) and len(b) >= 2:
            txt = str(b[0]).strip()
            if txt:
                segments.append((cx, txt, float(b[1])))
        # rec-only: (text, confidence)
        elif isinstance(a, str) and isinstance(b, (int, float)):
            if a.strip():
                segments.append((cx, a.strip(), float(b)))
    if sort_boxes and segments:
        segments.sort(key=lambda s: s[0])
    texts = [s[1] for s in segments]
    confidences = [s[2] for s in segments]
    text = " ".join(texts).strip()
    conf = sum(confidences) / len(confidences) if confidences else 0.0
    return text, conf


def _enhance_crop(crop: np.ndarray) -> np.ndarray:
    if crop.size == 0 or len(crop.shape) < 2:
        return crop
    if len(crop.shape) == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_ch = clahe.apply(l_ch)
    return cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)


def _fallback_ocr(image: np.ndarray) -> tuple[str, float]:
    try:
        import pytesseract

        ocr_key = (settings.ocr_lang or "ch").strip().lower()
        lang = {"ch": "chi_sim+eng"}.get(ocr_key, "eng")
        text = pytesseract.image_to_string(image, lang=lang).strip()
        return text, 0.75 if text else 0.0
    except Exception:
        return "", 0.0


def _ollama_on_cpu() -> bool:
    """True when the vision model is loaded but not in GPU VRAM (typical on 6 GB laptops)."""
    global _cpu_mode_cache
    import time

    now = time.time()
    if _cpu_mode_cache and (now - _cpu_mode_cache[0]) < 45.0:
        return _cpu_mode_cache[1]
    st = ollama_gpu_status()
    on_cpu = bool(st.get("loaded")) and not bool(st.get("on_gpu"))
    _cpu_mode_cache = (now, on_cpu)
    return on_cpu


def _vision_read_timeout(base_s: float) -> float:
    """CPU/RAM inference needs much longer read timeouts than GPU."""
    if _ollama_on_cpu():
        return min(1800.0, max(base_s * 4.0, base_s + 480.0))
    return base_s


def _composite_max_width() -> int:
    base = int(settings.handwriting_ocr_composite_max_width)
    if _ollama_on_cpu():
        return min(base, 640)
    return base


def _composite_crop_height() -> int:
    base = int(settings.handwriting_ocr_composite_crop_height)
    if _ollama_on_cpu():
        return min(base, 80)
    return base


def _ollama_inference_options(*, num_predict: int) -> dict[str, Any]:
    """Ollama options tuned for vision on consumer GPUs (e.g. 6 GB VRAM)."""
    on_cpu = _ollama_on_cpu()
    return {
        "temperature": 0,
        "num_predict": num_predict,
        # -1 = use all layers on GPU when VRAM allows
        "num_gpu": -1,
        # Smaller context on CPU/RAM — faster and uses less RAM
        "num_ctx": 1024 if on_cpu else 2048,
    }


def _encode_crop_b64(image: np.ndarray, *, jpeg: bool = True, quality: int = 88) -> str | None:
    if image.size == 0:
        return None
    img = image
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if jpeg:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    else:
        ok, buf = cv2.imencode(".png", img)
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _encode_crop_png_b64(image: np.ndarray) -> str | None:
    return _encode_crop_b64(image, jpeg=False)


def _handwriting_prompt(*, is_date: bool) -> str:
    lang = (settings.ocr_lang or "ch").strip().lower()
    lang_hint = {"ch": "Chinese", "en": "English"}.get(lang, lang)
    if is_date:
        return (
            f"You are reading handwritten {lang_hint} form fields.\n"
            "Task: Extract ONLY the handwritten date text inside the image.\n"
            "Rules:\n"
            "- Output ONLY the text, no explanation.\n"
            "- Keep separators if present (., /, -, 年, 月, 日).\n"
            "- If unreadable, output an empty string.\n"
        )
    return (
        f"You are reading handwritten {lang_hint} form fields.\n"
        "Task: Extract ONLY the handwritten text inside the image.\n"
        "Rules:\n"
        "- Output ONLY the text, no explanation.\n"
        "- Keep the original letters, numbers, and symbols.\n"
        "- Do not guess missing characters.\n"
        "- If unreadable, output an empty string.\n"
    )


def _handwriting_http_timeout(read_s: float) -> Any:
    import httpx

    return httpx.Timeout(connect=20.0, read=read_s, write=60.0, pool=20.0)


def ollama_gpu_status() -> dict[str, Any]:
    """Inspect Ollama /api/ps — is the vision model on GPU VRAM?"""
    out: dict[str, Any] = {
        "host": settings.ollama_host,
        "loaded": False,
        "on_gpu": False,
        "vram_mb": 0,
        "summary": "",
        "error": None,
    }
    try:
        import httpx

        want = settings.handwriting_ocr_model
        base = want.split(":")[0]
        with httpx.Client(timeout=4.0) as client:
            r = client.get(f"{settings.ollama_host}/api/ps")
            if r.status_code != 200:
                out["error"] = f"ps HTTP {r.status_code}"
                return out
            models = r.json().get("models", [])
            parts: list[str] = []
            for m in models:
                name = str(m.get("name", "?"))
                vram = int(m.get("size_vram") or 0)
                if want in name or name.startswith(base):
                    out["loaded"] = True
                    out["vram_mb"] = vram // (1024 * 1024)
                    out["on_gpu"] = vram > 0
                if vram > 0:
                    parts.append(f"{name} GPU {vram // (1024 * 1024)}MB")
                else:
                    parts.append(f"{name} (CPU/RAM — slow)")
            out["summary"] = "; ".join(parts)
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def _ollama_ps_summary() -> str:
    st = ollama_gpu_status()
    if st.get("summary"):
        return str(st["summary"])
    if st.get("error"):
        return str(st["error"])
    return ""


def _handwriting_ocr_ollama(
    image: np.ndarray,
    *,
    is_date: bool,
    timeout_s: float | None = None,
    prompt: str | None = None,
    num_predict: int = 128,
) -> tuple[str, float, str]:
    """
    Handwriting OCR via Ollama vision. Returns (text, confidence, error_message).
    """
    model = settings.handwriting_ocr_model
    read_timeout = _vision_read_timeout(
        timeout_s if timeout_s is not None else settings.handwriting_ocr_timeout_s
    )
    try:
        import httpx

        b64 = _encode_crop_b64(image, jpeg=True)
        if not b64:
            return "", 0.0, "empty image"
        prompt = prompt or _handwriting_prompt(is_date=is_date)
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "keep_alive": "30m",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64],
                }
            ],
            "options": _ollama_inference_options(num_predict=num_predict),
        }
        with _ollama_vision_lock:
            with httpx.Client(timeout=_handwriting_http_timeout(read_timeout)) as client:
                r = client.post(f"{settings.ollama_host}/api/chat", json=payload)
                if r.status_code >= 400:
                    detail = (r.text or "").strip().replace("\n", " ")[:180]
                    raise httpx.HTTPStatusError(
                        f"{r.status_code} {detail or r.reason_phrase}",
                        request=r.request,
                        response=r,
                    )
                data = r.json()
        msg = (data.get("message") or {}).get("content") or ""
        text = str(msg).strip()
        text = re.sub(r"^```[\w-]*\s*|\s*```$", "", text).strip()
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text).strip()
        if text:
            return text, 0.78, ""
        return "", 0.0, "empty response"
    except Exception as e:
        err = str(e).strip() or repr(e)
        if "timed out" in err.lower() or "timeout" in err.lower():
            hint = (
                "check GPU in Ollama"
                if not _ollama_on_cpu()
                else "CPU/RAM mode — allow up to 30 min per page"
            )
            err = f"{err} (vision model; allow {int(read_timeout)}s+; {hint})"
        logger.warning("Handwriting OCR (%s) failed: %s", model, err)
        return "", 0.0, err[:240]


def _ollama_models_root() -> Path:
    return settings.models_dir / "ollama"


def _ollama_model_on_disk(model: str) -> bool:
    """True when the offline seed copied manifest + blobs for this model."""
    parts = model.split(":", 1)
    name = parts[0]
    tag = parts[1] if len(parts) > 1 and parts[1] else "latest"
    manifest = (
        _ollama_models_root()
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / name
        / tag
    )
    return manifest.is_file()


def _ollama_tag_names() -> tuple[set[str], str | None]:
    """
    List model names from Ollama /api/tags.
    Returns (names, error_message). error is set only on connection failure.
    """
    import httpx

    last_err = ""
    for attempt in range(5):
        try:
            with httpx.Client(timeout=4.0) as client:
                r = client.get(f"{settings.ollama_host}/api/tags")
                if r.status_code != 200:
                    last_err = f"tags HTTP {r.status_code}"
                else:
                    tags = r.json().get("models", [])
                    return {m.get("name", "") for m in tags}, None
        except Exception as e:
            last_err = str(e).strip() or repr(e)
        if attempt < 4:
            import time

            time.sleep(0.8 * (attempt + 1))
    return set(), last_err or "Ollama not reachable"


def _model_listed_in_ollama(want: str, names: set[str]) -> bool:
    base = want.split(":")[0]
    return any(want in n or n.startswith(base) for n in names)


def invalidate_handwriting_cache() -> None:
    global _hw_ok, _hw_checked_at
    with _hw_lock:
        _hw_ok = None
        _hw_checked_at = 0.0


def _cache_handwriting_available(ok: bool) -> bool:
    import time

    global _hw_ok, _hw_checked_at
    now = time.time()
    with _hw_lock:
        _hw_ok = ok
        _hw_checked_at = now
    ttl = _HW_CACHE_OK_S if ok else _HW_CACHE_MISS_S
    return ok


def _handwriting_model_available_uncached() -> tuple[bool, str]:
    want = settings.handwriting_ocr_model
    if _ollama_model_on_disk(want):
        names, err = _ollama_tag_names()
        if err:
            # Files on disk but Ollama not up yet — still try vision OCR (real error if it fails).
            return True, ""
        if _model_listed_in_ollama(want, names):
            return True, ""
        return True, ""
    names, err = _ollama_tag_names()
    if err:
        return False, err
    if _model_listed_in_ollama(want, names):
        return True, ""
    return False, f"{want} not loaded in Ollama (start Ollama or run patch-ollama-models)"


def _handwriting_model_available() -> bool:
    import time

    global _hw_ok, _hw_checked_at
    now = time.time()
    with _hw_lock:
        if _hw_ok is not None:
            ttl = _HW_CACHE_OK_S if _hw_ok else _HW_CACHE_MISS_S
            if (now - _hw_checked_at) < ttl:
                return _hw_ok
    ok, _ = _handwriting_model_available_uncached()
    _cache_handwriting_available(ok)
    return ok


def wait_for_handwriting_model(timeout_s: float = 90.0) -> tuple[bool, str]:
    """Wait until Ollama lists the handwriting model or timeout (job start)."""
    import time

    if not settings.handwriting_ocr_enabled or not uses_qwen_only():
        return True, ""
    deadline = time.time() + timeout_s
    last_msg = ""
    while time.time() < deadline:
        invalidate_handwriting_cache()
        ok, msg = _handwriting_model_available_uncached()
        if ok:
            _cache_handwriting_available(True)
            return True, ""
        last_msg = msg
        time.sleep(1.0)
    return False, last_msg or "handwriting model not ready"


def _pin_handwriting_model() -> None:
    """Keep the vision model loaded between jobs (vision chat, not empty generate)."""
    try:
        import httpx

        warm = np.full((64, 64, 3), 255, dtype=np.uint8)
        b64 = _encode_crop_b64(warm, jpeg=True)
        if not b64:
            return
        with httpx.Client(timeout=60.0) as client:
            client.post(
                f"{settings.ollama_host}/api/chat",
                json={
                    "model": settings.handwriting_ocr_model,
                    "stream": False,
                    "keep_alive": -1,
                    "messages": [
                        {
                            "role": "user",
                            "content": " ",
                            "images": [b64],
                        }
                    ],
                    "options": _ollama_inference_options(num_predict=4),
                },
            )
    except Exception as e:
        logger.warning("Could not pin handwriting model: %s", e)


def _unload_handwriting_model() -> None:
    try:
        import httpx

        with httpx.Client(timeout=15.0) as client:
            client.post(
                f"{settings.ollama_host}/api/chat",
                json={
                    "model": settings.handwriting_ocr_model,
                    "keep_alive": 0,
                    "messages": [{"role": "user", "content": ""}],
                },
            )
    except Exception:
        pass


def warmup_handwriting_model() -> tuple[bool, str]:
    """One vision request to load qwen into GPU/RAM (called once per API lifetime)."""
    if not settings.handwriting_ocr_enabled and not uses_qwen_only():
        return True, ""
    if not _handwriting_model_available():
        return False, "handwriting model not available"

    # Composite-sized warmup (same path as batch OCR).
    warm = _build_composite_strip([("warmup", np.full((80, 200, 3), 255, dtype=np.uint8))])
    if warm.size == 0:
        warm = np.full((200, 480, 3), 255, dtype=np.uint8)
    cv2.putText(warm, "warmup", (140, warm.shape[0] // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    _, _, err = _handwriting_ocr_ollama(
        _resize_for_vision(warm, max_side=settings.handwriting_ocr_composite_max_width),
        is_date=False,
        timeout_s=settings.handwriting_ocr_warmup_timeout_s,
        num_predict=24,
    )
    if err and ("timed out" in err.lower() or "timeout" in err.lower()):
        return False, err
    _pin_handwriting_model()
    gpu = ollama_gpu_status()
    ps = _ollama_ps_summary()
    if gpu.get("on_gpu"):
        return True, ps or f"GPU {gpu.get('vram_mb', 0)}MB VRAM"
    if ps:
        logger.warning("Vision model loaded but not on GPU: %s", ps)
        return True, f"{ps} | CPU/RAM (slow on 6 GB GPU — expected)"
    return True, "warmup done"


def ensure_qwen_session_ready(*, force_rewarm: bool = False) -> tuple[bool, str]:
    """Load Qwen once (splash + first job). Returns immediately if already warm."""
    global _qwen_session_ready
    if not uses_qwen_only() and not settings.handwriting_ocr_enabled:
        return True, ""
    with _qwen_session_lock:
        if _qwen_session_ready and not force_rewarm:
            gpu = ollama_gpu_status()
            if gpu.get("on_gpu"):
                return True, f"ready (GPU {gpu.get('vram_mb', 0)}MB)"
            if gpu.get("loaded"):
                return True, "ready (CPU/RAM — slow)"
            return True, "ready"
    if force_rewarm:
        _unload_handwriting_model()
        with _qwen_session_lock:
            _qwen_session_ready = False
    ok, msg = wait_for_handwriting_model(120.0)
    if not ok:
        return False, msg
    warm_ok, warm_msg = warmup_handwriting_model()
    if not warm_ok:
        return False, warm_msg
    with _qwen_session_lock:
        _qwen_session_ready = True
    return True, warm_msg or "ready"


def _resize_for_vision(image: np.ndarray, *, max_side: int | None = None) -> np.ndarray:
    cap = max_side if max_side is not None else int(settings.handwriting_ocr_max_image_side)
    max_side_px = max(320, cap)
    h, w = image.shape[:2]
    side = max(h, w)
    if side <= max_side_px:
        return image
    scale = max_side_px / side
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _parse_json_object(text: str) -> dict[str, str]:
    import json

    text = text.strip()
    if not text:
        return {}
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k): str(v) if v is not None else "" for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        blob = match.group(0)
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return {str(k): str(v) if v is not None else "" for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    return {}


def _parse_batch_response(text: str, ordered_keys: list[str]) -> dict[str, str]:
    """Parse composite-batch model output (JSON, numbered keys, or key: value lines)."""
    if not text or not ordered_keys:
        return {}

    parsed = _parse_json_object(text)
    if parsed:
        out: dict[str, str] = {}
        for key in ordered_keys:
            if key in parsed and parsed[key].strip():
                out[key] = parsed[key].strip()
        if out:
            return out
        # Numeric keys {"1": "...", "2": "..."} matching row order
        for i, key in enumerate(ordered_keys):
            for nk in (str(i + 1), f"field_{i + 1}", f"row_{i + 1}"):
                val = (parsed.get(nk) or "").strip()
                if val:
                    out[key] = val
                    break
        if out:
            return out

    out = {}
    for key in ordered_keys:
        m = re.search(
            rf'["\']?{re.escape(key)}["\']?\s*[:：=]\s*["\']?(.+?)["\']?\s*(?:,|\n|$)',
            text,
            re.IGNORECASE,
        )
        if m:
            out[key] = m.group(1).strip().strip('"').strip("'")
    if out:
        return out

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) == len(ordered_keys):
        for key, line in zip(ordered_keys, lines):
            line = re.sub(r"^\d+[\.\):]\s*", "", line)
            line = re.sub(rf"^{re.escape(key)}\s*[:：=]\s*", "", line, flags=re.IGNORECASE)
            if line:
                out[key] = line.strip()
    return out


def _crop_field_from_page(
    image: np.ndarray,
    bbox_norm: list[float],
    *,
    pad_ratio: float = 0.12,
    template: Any = None,
) -> np.ndarray:
    from app.services.template_learn import bbox_on_processed_page, denormalize_bbox

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


def _build_composite_strip(
    crops: list[tuple[str, np.ndarray]],
) -> np.ndarray:
    """Stack field crops vertically with row numbers (not field keys — avoids OCR confusion)."""
    max_w = max(320, _composite_max_width())
    target_h = max(48, _composite_crop_height())
    rows: list[np.ndarray] = []
    for row_num, (_key, crop) in enumerate(crops, start=1):
        if crop.size == 0:
            continue
        if len(crop.shape) == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        ch, cw = crop.shape[:2]
        scale = min(target_h / max(ch, 1), (max_w - 48) / max(cw, 1))
        tw = max(32, int(cw * scale))
        th = max(32, int(ch * scale))
        resized = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)
        label_w = 36
        bar = np.full((th, label_w, 3), 245, dtype=np.uint8)
        cv2.putText(
            bar,
            str(row_num),
            (8, th // 2 + 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (30, 30, 30),
            2,
            cv2.LINE_AA,
        )
        row = np.hstack([bar, resized])
        rows.append(row)
        rows.append(np.full((4, row.shape[1], 3), 220, dtype=np.uint8))
    if not rows:
        return np.array([])
    strip_w = max(r.shape[1] for r in rows)
    padded: list[np.ndarray] = []
    for r in rows:
        if r.shape[1] < strip_w:
            r = np.hstack(
                [r, np.full((r.shape[0], strip_w - r.shape[1], 3), 255, dtype=np.uint8)]
            )
        padded.append(r)
    return np.vstack(padded)


def _results_from_parsed_json(
    parsed: dict[str, str],
    template_keys: list[str],
    *,
    hw_model: str,
    conf: float,
    err: str,
    fields: dict[str, Any] | None = None,
) -> dict[str, OcrCropResult]:
    from app.services.multiline import apply_multiline_to_result

    results: dict[str, OcrCropResult] = {}
    for key in template_keys:
        val = (parsed.get(key) or "").strip()
        field_def = fields.get(key) if fields else None
        if field_def is not None:
            val = apply_multiline_to_result(val, field_def)
        if val and not err:
            results[key] = OcrCropResult(
                text=val,
                confidence=max(conf, 0.75),
                engine=hw_model,
                qwen_text=val,
            )
        else:
            results[key] = OcrCropResult(
                text="",
                confidence=0.0,
                engine="none",
                qwen_text=val or "",
                qwen_error=err[:240] if err else ("empty" if not val else ""),
            )
    return results


def _vision_batch_for_crops(
    crops: list[tuple[str, np.ndarray]],
    *,
    all_keys: list[str],
    hint_lines: list[str],
    hw_model: str,
    on_vlm_pulse: Callable[[float], None] | None = None,
) -> tuple[dict[str, str], str]:
    """One stacked-strip vision call; returns (parsed field key -> text, error)."""
    if not crops:
        return {}, ""

    pulse_stop = threading.Event()

    def _pulse_loop() -> None:
        if not on_vlm_pulse:
            return
        t0 = time.monotonic()
        while not pulse_stop.wait(1.2):
            # Ease toward ~90% of the current chunk (resets each chunk).
            elapsed = time.monotonic() - t0
            frac = min(0.92, elapsed / (elapsed + 45.0))
            try:
                on_vlm_pulse(frac)
            except Exception:
                pass

    pulse_thread: threading.Thread | None = None
    if on_vlm_pulse:
        pulse_thread = threading.Thread(target=_pulse_loop, daemon=True)
        pulse_thread.start()

    crop_keys = [k for k, _ in crops]
    try:
        composite = _build_composite_strip(crops)
        if composite.size == 0:
            return {}, "empty composite"

        lang = (settings.ocr_lang or "ch").strip().lower()
        lang_hint = {"ch": "Chinese", "en": "English"}.get(lang, lang)
        row_map = "\n".join(
            f"  Row {i + 1} → field key \"{k}\"" for i, k in enumerate(crop_keys)
        )
        prompt = (
            f"You read handwritten {lang_hint} text on a form.\n"
            "The image shows field crops stacked top-to-bottom. Each row has a number on the left.\n"
            f"Row mapping:\n{row_map}\n"
            "Extract ONLY the handwritten/printed text in each crop (ignore row numbers).\n"
            "For MULTILINE fields, keep newline characters between lines in the JSON value.\n"
            "Use empty string if unreadable. Do not guess.\n"
        )
        chunk_hints = [ln for ln in hint_lines if any(f'"{k}"' in ln for k in crop_keys)]
        if chunk_hints:
            prompt += "Hints:\n" + "\n".join(chunk_hints) + "\n"
        example_keys = ", ".join(f'"{k}"' for k in crop_keys[:3])
        prompt += f'\nReturn ONLY JSON with these exact keys: {example_keys}, ...\n'
        prompt += 'Example: {"name": "text", "gender": "text"}\n'

        img = _resize_for_vision(composite, max_side=_composite_max_width())
        n = len(crops)
        predict_cap = 180 if _ollama_on_cpu() else 320
        text, _conf, err = _handwriting_ocr_ollama(
            img,
            is_date=False,
            timeout_s=settings.handwriting_ocr_page_timeout_s,
            prompt=prompt,
            num_predict=min(predict_cap, max(80 if _ollama_on_cpu() else 120, 36 * n)),
        )
        if err:
            logger.warning("Composite batch error (%d fields): %s", n, err[:120])
            return {}, err
        parsed = _parse_batch_response(text, crop_keys) if text else {}
        if not parsed and text:
            logger.warning("Composite batch parse failed: %s", text[:80])
            return {}, "vision response parse failed"
        return parsed, ""
    finally:
        pulse_stop.set()
        if pulse_thread is not None:
            pulse_thread.join(timeout=0.2)
        if on_vlm_pulse:
            try:
                on_vlm_pulse(0.0)
            except Exception:
                pass


def extract_fields_qwen_composite(
    image: np.ndarray,
    template: Any,
    *,
    on_chunk_done: Callable[[int, int, int], None] | None = None,
    on_vlm_pulse: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, OcrCropResult]:
    """
    Batch OCR: stack field crops + vision call(s). Large forms are split into chunks
    so progress and model output stay reliable.
    """
    from app.schemas.common import FieldType, TemplatePayload
    from app.services.field_styles import style_hint_for_ocr
    from app.services.job_cancel import JobCancelledError

    if not isinstance(template, TemplatePayload):
        template = TemplatePayload.model_validate(template)

    hw_model = settings.handwriting_ocr_model
    keys = list(template.fields.keys())
    if image.size == 0 or not keys:
        return {}

    from app.services.multiline import is_multiline_field

    styles = template.field_styles or {}
    crops: list[tuple[str, np.ndarray]] = []
    multiline_items: list[tuple[str, np.ndarray, Any]] = []
    hint_lines: list[str] = []
    for key, field in template.fields.items():
        pad = 0.28 if field.field_type == FieldType.date else 0.12
        crop = _crop_field_from_page(
            image, field.bbox_norm, pad_ratio=pad, template=template
        )
        if crop.size == 0:
            continue
        enhanced = _enhance_crop(crop)
        if is_multiline_field(field):
            multiline_items.append((key, enhanced, field))
        else:
            crops.append((key, enhanced))
        hint = style_hint_for_ocr(field, styles)
        if hint:
            hint_lines.append(f'"{key}": {hint.strip()}')

    merged: dict[str, str] = {}
    conf = 0.75
    last_batch_err = ""

    def _check_cancel() -> None:
        if should_cancel and should_cancel():
            raise JobCancelledError("Cancelled by user")

    for key, crop, field in multiline_items:
        _check_cancel()
        text, _c, err = _ocr_multiline_crop(crop, field, is_date=field.field_type == FieldType.date)
        if text:
            merged[key] = text
        elif err:
            logger.warning("Multiline OCR %s: %s", key, err[:100])

    if not crops and not merged:
        return _results_from_parsed_json(
            {}, keys, hw_model=hw_model, conf=0.0, err="no crops", fields=template.fields
        )

    crop_keys = [k for k, _ in crops]
    total_crops = len(crop_keys) + len(multiline_items)
    track_progress = on_chunk_done is not None
    chunk_size = _composite_chunk_size(len(crop_keys) or 1)
    use_chunks = len(crop_keys) > chunk_size

    def _run_batch(batch_crops: list[tuple[str, np.ndarray]]) -> dict[str, str]:
        nonlocal last_batch_err
        part, err = _vision_batch_for_crops(
            batch_crops,
            all_keys=keys,
            hint_lines=hint_lines,
            hw_model=hw_model,
            on_vlm_pulse=on_vlm_pulse if track_progress else None,
        )
        if err:
            last_batch_err = err
        return part

    if crop_keys:
        if not use_chunks:
            merged.update(_run_batch(crops))
            if on_chunk_done:
                on_chunk_done(total_crops, total_crops, total_crops)
        else:
            done_keys = len(multiline_items)
            for start in range(0, len(crop_keys), chunk_size):
                _check_cancel()
                chunk = crops[start : start + chunk_size]
                if on_chunk_done:
                    on_chunk_done(done_keys, total_crops, len(chunk))
                part = _run_batch(chunk)
                merged.update(part)
                done_keys = len(multiline_items) + min(start + len(chunk), len(crop_keys))
                if on_chunk_done:
                    on_chunk_done(done_keys, total_crops, len(chunk))

    if not merged:
        batch_err = last_batch_err or "batch empty"
        return _results_from_parsed_json(
            {}, keys, hw_model=hw_model, conf=0.0, err=batch_err, fields=template.fields
        )
    return _results_from_parsed_json(
        merged, keys, hw_model=hw_model, conf=conf, err="", fields=template.fields
    )


def extract_fields_qwen_page(
    image: np.ndarray, template: Any
) -> dict[str, OcrCropResult]:
    """
    Legacy full-page bbox batch (slow on CPU / large pages). Prefer composite batch.
    """
    from app.schemas.common import TemplatePayload

    if not isinstance(template, TemplatePayload):
        template = TemplatePayload.model_validate(template)

    hw_model = settings.handwriting_ocr_model
    empty: dict[str, OcrCropResult] = {}
    if image.size == 0 or not template.fields:
        return empty

    page_cap = max(320, int(settings.handwriting_ocr_page_max_image_side))
    img = _resize_for_vision(image, max_side=page_cap)
    from app.services.field_styles import style_hint_for_ocr

    styles = template.field_styles or {}
    field_lines: list[str] = []
    for key, field in template.fields.items():
        x, y, bw, bh = field.bbox_norm
        label = (field.label or key).replace('"', "'")
        style_part = ""
        if field.style_key:
            style_part = f", style={field.style_key}"
        hint = style_hint_for_ocr(field, styles)
        field_lines.append(
            f'- "{key}" (type={field.field_type.value}, label="{label}"{style_part}): '
            f"bbox x={x:.4f} y={y:.4f} w={bw:.4f} h={bh:.4f}.{hint}"
        )

    lang = (settings.ocr_lang or "ch").strip().lower()
    lang_hint = {"ch": "Chinese", "en": "English"}.get(lang, lang)
    prompt = (
        f"You read handwritten {lang_hint} text on a form image.\n"
        "Each field has a normalized bounding box (x,y = top-left, w,h = size, 0–1).\n"
        "Extract ONLY the handwritten/printed content inside each box.\n"
        "Do not guess. Use empty string if unreadable.\n\n"
        "Fields:\n"
        + "\n".join(field_lines)
        + '\n\nReturn ONLY a JSON object: {"field_key": "extracted text", ...}'
    )

    text, conf, err = _handwriting_ocr_ollama(
        img,
        is_date=False,
        timeout_s=settings.handwriting_ocr_page_timeout_s,
        prompt=prompt,
        num_predict=min(384, max(160, 40 * len(template.fields))),
    )
    parsed = _parse_json_object(text) if text else {}

    results: dict[str, OcrCropResult] = {}
    for key in template.fields:
        val = (parsed.get(key) or "").strip()
        if val and not err:
            results[key] = OcrCropResult(
                text=val,
                confidence=max(conf, 0.75),
                engine=hw_model,
                qwen_text=val,
            )
        else:
            results[key] = OcrCropResult(
                text="",
                confidence=0.0,
                engine="none",
                qwen_text=val or "",
                qwen_error=err[:240] if err else ("empty" if not val else ""),
            )
    return results


def _run_ocr(
    ocr: Any,
    prepared: np.ndarray,
    *,
    det: bool,
    rec: bool,
    sort_boxes: bool = False,
) -> tuple[str, float]:
    with _ocr_infer_lock:
        result = ocr.ocr(prepared, det=det, rec=rec, cls=False)
    return _parse_ocr_result(result, sort_boxes=sort_boxes)


def _is_useful_ocr_text(text: str) -> bool:
    return bool(text) and not re.match(r"^[#\s\W]+$", text)


def prepare_date_crop(crop: np.ndarray) -> np.ndarray:
    """Skip 出生 label on the left of Chinese ID date rows when the box is wide."""
    if crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    if w >= 120 and (settings.ocr_lang or "ch").strip().lower() in ("ch",):
        cut = int(w * 0.26)
        crop = crop[:, cut:]
    return _enhance_crop(crop)


def _paddle_ocr_crop(ocr: Any, prepared: np.ndarray, *, is_date: bool) -> tuple[str, float]:
    use_cjk_date = (settings.ocr_lang or "ch").strip().lower() in ("ch",)
    if is_date and use_cjk_date:
        text, conf = _run_ocr(ocr, prepared, det=True, rec=True, sort_boxes=True)
        if _is_useful_ocr_text(text):
            return text, conf
    text, conf = _run_ocr(ocr, prepared, det=False, rec=True)
    if _is_useful_ocr_text(text):
        return text, conf
    text, conf = _run_ocr(ocr, prepared, det=True, rec=True, sort_boxes=is_date)
    if _is_useful_ocr_text(text):
        return text, conf
    return "", 0.0


def _ocr_multiline_crop(
    image: np.ndarray,
    field: Any = None,
    *,
    is_date: bool = False,
    line_count: int | None = None,
) -> tuple[str, float, str]:
    from app.schemas.common import TemplateField
    from app.services.multiline import (
        draw_line_guides,
        effective_line_count,
        multiline_crop_min_height,
        multiline_ocr_prompt,
        normalize_multiline_text,
    )

    n = line_count if line_count and line_count >= 2 else None
    if not n and field is not None:
        if not isinstance(field, TemplateField):
            try:
                field = TemplateField.model_validate(field)
            except Exception:
                field = None
        n = effective_line_count(field)
    if not n:
        return "", 0.0, "not multiline"

    lang = (settings.ocr_lang or "ch").strip().lower()
    guided = draw_line_guides(image, n)
    min_h = multiline_crop_min_height(n)
    prepared = prepare_crop_for_ocr(
        guided,
        pad_ratio=0.22,
        min_h=min_h,
        min_w=300,
    )
    prompt = multiline_ocr_prompt(line_count=n, lang=lang, is_date=is_date)
    predict_cap = 180 if _ollama_on_cpu() else 360
    text, conf, err = _handwriting_ocr_ollama(
        prepared,
        is_date=is_date,
        prompt=prompt,
        num_predict=min(predict_cap, max(96, 28 * n)),
    )
    if text:
        text = normalize_multiline_text(text, n)
    return text, conf, err


def ocr_crop(
    image: np.ndarray,
    *,
    is_date: bool = False,
    line_count: int | None = None,
    field: Any = None,
) -> OcrCropResult:
    empty = OcrCropResult(text="", confidence=0.0, engine="none")
    if image.size == 0:
        return empty

    from app.services.multiline import effective_line_count

    multiline_n = line_count if line_count and line_count >= 2 else None
    if field is not None and multiline_n is None:
        if not hasattr(field, "line_count"):
            from app.schemas.common import TemplateField

            field = TemplateField.model_validate(field)
        multiline_n = effective_line_count(field)

    if multiline_n:
        if is_date:
            image = prepare_date_crop(image)
        if uses_qwen_only() or settings.handwriting_ocr_enabled:
            if _handwriting_model_available():
                qwen_text, qwen_conf, qwen_error = _ocr_multiline_crop(
                    image,
                    field=field,
                    is_date=is_date,
                    line_count=multiline_n,
                )
                if qwen_text:
                    return OcrCropResult(
                        text=qwen_text,
                        confidence=max(qwen_conf, 0.75),
                        engine=settings.handwriting_ocr_model,
                        qwen_text=qwen_text,
                        qwen_error=qwen_error,
                    )
        # Fall through to standard path if multiline vision failed

    if is_date:
        image = prepare_date_crop(image)
    # Vision models need enough pixels; tiny template boxes are upscaled (not downscaled).
    prepared = prepare_crop_for_ocr(
        image,
        pad_ratio=0.55 if is_date else 0.35,
        min_h=200 if is_date else 160,
        min_w=400 if is_date else 280,
    )

    lang_key = (settings.ocr_lang or "ch").strip().lower()
    hw_model = settings.handwriting_ocr_model
    qwen_text = ""
    qwen_conf = 0.0
    qwen_error = ""
    paddle_text = ""
    paddle_conf = 0.0
    tess_text = ""
    tess_conf = 0.0

    use_qwen = uses_qwen_only()

    # Qwen / vision path
    if use_qwen:
        if _handwriting_model_available():
            qwen_text, qwen_conf, qwen_error = _handwriting_ocr_ollama(
                prepared, is_date=is_date
            )
        else:
            _, msg = _handwriting_model_available_uncached()
            qwen_error = msg if msg else f"{hw_model} not loaded in Ollama"

    # Paddle / Tesseract only in hybrid mode
    if not uses_qwen_only():
        try:
            ocr = get_ocr()
            paddle_text, paddle_conf = _paddle_ocr_crop(ocr, prepared, is_date=is_date)
        except Exception as e:
            logger.warning("Paddle OCR crop error: %s", e)
            paddle_text, paddle_conf = "", 0.0

        if not qwen_text and not paddle_text:
            tess_text, tess_conf = _fallback_ocr(prepared)
        else:
            tess_text, tess_conf = "", 0.0

    # Choose primary result
    if (
        qwen_text
        and (not qwen_error)
        and qwen_conf >= settings.handwriting_ocr_min_confidence
    ):
        return OcrCropResult(
            text=qwen_text,
            confidence=qwen_conf,
            engine=hw_model,
            qwen_text=qwen_text,
            paddle_text=paddle_text,
            tesseract_text=tess_text,
            qwen_error=qwen_error,
        )
    if paddle_text:
        return OcrCropResult(
            text=paddle_text,
            confidence=paddle_conf,
            engine="paddle",
            qwen_text=qwen_text,
            paddle_text=paddle_text,
            tesseract_text=tess_text,
            qwen_error=qwen_error,
        )
    if tess_text:
        return OcrCropResult(
            text=tess_text,
            confidence=tess_conf,
            engine="tesseract",
            qwen_text=qwen_text,
            paddle_text=paddle_text,
            tesseract_text=tess_text,
            qwen_error=qwen_error,
        )
    if qwen_text:
        return OcrCropResult(
            text=qwen_text,
            confidence=qwen_conf,
            engine=hw_model,
            qwen_text=qwen_text,
            paddle_text=paddle_text,
            tesseract_text=tess_text,
            qwen_error=qwen_error,
        )
    return OcrCropResult(
        text="",
        confidence=0.0,
        engine="none",
        qwen_text=qwen_text,
        paddle_text=paddle_text,
        tesseract_text=tess_text,
        qwen_error=qwen_error,
    )
