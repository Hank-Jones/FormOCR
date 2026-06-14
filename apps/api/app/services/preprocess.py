import logging

from pathlib import Path



import cv2

import numpy as np

from PIL import Image, ImageOps



from app.config import settings
from app.services.preprocess_transform import PreprocessTransform



logger = logging.getLogger("formocr.preprocess")





def load_image(path: str | Path) -> np.ndarray:

    with Image.open(path) as pil:

        pil = ImageOps.exif_transpose(pil)

        if pil.mode != "RGB":

            pil = pil.convert("RGB")

        rgb = np.asarray(pil)

    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)





def save_image(path: str | Path, image: np.ndarray) -> None:

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(path), image)





def _rotate_right_angle(image: np.ndarray, degrees: int) -> np.ndarray:

    if degrees == 0:

        return image

    if degrees == 90:

        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    if degrees == 180:

        return cv2.rotate(image, cv2.ROTATE_180)

    if degrees == 270:

        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    raise ValueError(f"Unsupported rotation: {degrees}")





def _top_bottom_asymmetry_score(gray: np.ndarray) -> float:

    """Higher when ink density is heavier toward the top (typical form headers)."""

    _, binary = cv2.threshold(

        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU

    )

    h = binary.shape[0]

    if h < 30:

        return 0.0

    top = float(np.mean(binary[: h // 3] > 0))

    bottom = float(np.mean(binary[(2 * h) // 3 :] > 0))

    total = top + bottom

    if total < 1e-6:

        return 0.0

    return (top - bottom) / total





def _text_orientation_score(gray: np.ndarray) -> float:

    """Higher when horizontal text-line structure dominates (page upright)."""

    h, w = gray.shape[:2]

    max_side = max(h, w)

    if max_side > 900:

        scale = 900 / max_side

        gray = cv2.resize(

            gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA

        )



    _, binary = cv2.threshold(

        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU

    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))

    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)



    row_proj = np.sum(binary, axis=1, dtype=np.float64)

    col_proj = np.sum(binary, axis=0, dtype=np.float64)

    row_var = float(np.var(row_proj))

    col_var = float(np.var(col_proj))

    if col_var < 1e-6:

        return row_var

    return row_var / col_var





def _detect_orientation_osd(gray: np.ndarray) -> int | None:

    try:

        import pytesseract

        from pytesseract import Output



        osd = pytesseract.image_to_osd(gray, output_type=Output.DICT)

        angle = int(osd.get("rotate", 0) or 0)

        conf = float(osd.get("orientation_conf", 0) or 0)

        if angle in (0, 90, 180, 270) and conf >= 5.0:

            return angle

    except Exception:

        return None

    return None





def _orientation_combined_score(gray: np.ndarray) -> float:

    """Blend line-structure and top-heavy layout cues for upright detection."""

    proj = _text_orientation_score(gray)

    asym = _top_bottom_asymmetry_score(gray)

    return proj + 40.0 * asym





def _prefer_portrait_angle(h: int, w: int, angle: int) -> int:

    """When 90° and 270° are ambiguous, prefer the rotation that yields portrait."""

    if angle not in (90, 270):

        return angle

    if h >= w:

        return angle

    return 270 if angle == 90 else 90





def detect_orientation_angle(image: np.ndarray) -> int:

    """Return clockwise correction angle in {0, 90, 180, 270}."""

    gray = (

        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        if len(image.shape) == 3

        else image.copy()

    )



    osd_angle = _detect_orientation_osd(gray)

    if osd_angle is not None:

        return osd_angle

    if not settings.preprocess_auto_orient_heuristic:

        return 0



    scores: dict[int, float] = {}

    # Heuristic orientation is reliable for sideways scans (90/270) but
    # frequently ambiguous for 0 vs 180. Only OSD is allowed to force 180.
    for angle in (0, 90, 270):

        rotated = _rotate_right_angle(gray, angle)

        scores[angle] = _orientation_combined_score(rotated)



    best_angle = max(scores, key=scores.get)

    upright_score = scores[0]



    if best_angle == 0:

        return 0



    best_score = scores[best_angle]

    margin = best_score - upright_score

    if margin < 1.5 and best_score < upright_score * 1.03:

        return 0



    if best_angle in (90, 270):

        alt = 270 if best_angle == 90 else 90

        if abs(scores[best_angle] - scores[alt]) < 2.0:

            asym_best = _top_bottom_asymmetry_score(_rotate_right_angle(gray, best_angle))

            asym_alt = _top_bottom_asymmetry_score(_rotate_right_angle(gray, alt))

            if asym_alt > asym_best + 0.02:

                best_angle = alt

            else:

                best_angle = _prefer_portrait_angle(*gray.shape[:2], best_angle)



    return best_angle





def _correct_orientation(image: np.ndarray) -> tuple[np.ndarray, int]:

    angle = detect_orientation_angle(image)

    if angle != 0:

        logger.debug("Auto-orient: rotate %s° clockwise", angle)

    return _rotate_right_angle(image, angle), angle





def _deskew(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:

    coords = np.column_stack(np.where(gray < 200))

    if len(coords) < 100:

        return gray, None

    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]

    if angle < -45:

        angle = 90 + angle

    elif angle > 45:

        angle = angle - 90

    if abs(angle) < 0.5:

        return gray, None

    h, w = gray.shape[:2]

    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)

    out = cv2.warpAffine(

        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE

    )

    return out, matrix





def _align_to_content(

    image: np.ndarray, *, padding_ratio: float = 0.02, min_margin_px: int = 8

) -> tuple[np.ndarray, tuple[int, int] | None]:

    """

    Crop to ink bounding box with padding — removes horizontal/vertical scan offset.

    Returns (cropped image, (dx, dy) translation applied to coordinates).

    """

    if image.size == 0:

        return image, None

    if len(image.shape) == 3:

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    else:

        gray = image

    mask = gray < 200

    coords = np.column_stack(np.where(mask))

    if len(coords) < 100:

        return image, None



    y_min, x_min = coords.min(axis=0)

    y_max, x_max = coords.max(axis=0)

    h, w = gray.shape[:2]

    pad_x = max(min_margin_px, int((x_max - x_min) * padding_ratio))

    pad_y = max(min_margin_px, int((y_max - y_min) * padding_ratio))



    x1 = max(0, int(x_min) - pad_x)

    y1 = max(0, int(y_min) - pad_y)

    x2 = min(w, int(x_max) + pad_x + 1)

    y2 = min(h, int(y_max) + pad_y + 1)

    if x2 - x1 < w * 0.35 or y2 - y1 < h * 0.35:

        return image, None



    cropped = image[y1:y2, x1:x2]

    return cropped, (x1, y1)





def preprocess_page(

    image: np.ndarray,

    *,

    auto_orient: bool = True,

    deskew: bool = True,

    align: bool = True,

    denoise: bool = True,

    sharpen: bool = True,

    contrast: bool = True,

    transform: PreprocessTransform | None = None,

) -> tuple[np.ndarray, PreprocessTransform]:

    h0, w0 = image.shape[:2]

    if transform is None:

        transform = PreprocessTransform.identity(w0, h0)



    if auto_orient:

        image, orient = _correct_orientation(image)

        if orient:

            transform.append_rotate_cw(orient)



    if len(image.shape) == 3:

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    else:

        gray = image.copy()



    if denoise:

        gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)



    if contrast:

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        gray = clahe.apply(gray)



    if deskew:

        gray, deskew_m = _deskew(gray)

        if deskew_m is not None:

            h, w = gray.shape[:2]

            transform.append_affine(deskew_m, new_w=w, new_h=h)



    if align:

        aligned, offset = _align_to_content(gray)

        if offset is not None:

            dx, dy = offset

            transform.append_translate(-float(dx), -float(dy))

            gray = aligned



    if sharpen:

        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])

        gray = cv2.filter2D(gray, -1, kernel)



    out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    transform.dst_w = out.shape[1]

    transform.dst_h = out.shape[0]

    return out, transform





def preprocess_file(

    source: Path, dest: Path, **kwargs

) -> tuple[int, int, PreprocessTransform]:

    img = load_image(source)

    processed, transform = preprocess_page(img, **kwargs)

    save_image(dest, processed)

    return processed.shape[1], processed.shape[0], transform


