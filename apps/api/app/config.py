import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORMOCR_")

    data_dir: Path = Path.home() / "AppData" / "Local" / "FormOCR"
    host: str = "127.0.0.1"
    port: int = 8765
    ollama_host: str = "http://127.0.0.1:11434"
    # Text LLM for optional AI correction (not used in offline / qwen-only builds)
    ollama_model: str = "phi3:mini"
    # qwen = vision-only OCR (recommended). hybrid = Paddle + optional Qwen per field.
    ocr_engine: str = "qwen"
    ai_correction_enabled: bool = True
    handwriting_ocr_enabled: bool = True
    handwriting_ocr_model: str = "qwen2.5vl:3b"
    handwriting_ocr_timeout_s: float = 120.0
    handwriting_ocr_page_timeout_s: float = 360.0
    handwriting_ocr_warmup_timeout_s: float = 300.0
    handwriting_ocr_min_confidence: float = 0.55
    handwriting_ocr_max_image_side: int = 1280
    # Full-page batch uses a smaller cap — faster and less likely to hit read timeout.
    handwriting_ocr_page_max_image_side: int = 1024
    # Stacked field crops — one vision call, much faster than full-page bbox OCR.
    handwriting_ocr_composite_max_width: int = 880
    handwriting_ocr_composite_crop_height: int = 100
    # At or below this count, all fields go in one composite vision call (even during batch jobs).
    handwriting_ocr_composite_single_call_max_fields: int = 40
    # Above single-call limit, split into chunks of this many fields per vision call.
    handwriting_ocr_composite_chunk_fields: int = 20
    # PaddleOCR UI code: ch | en | ko (mapped to paddle lang in ocr.paddle_lang)
    ocr_lang: str = "ko"
    max_upload_mb: int = 50
    preprocess_auto_orient: bool = True
    # Heuristic orientation (without OSD) can rotate pages incorrectly.
    # Keep off by default; only OSD-based orientation is always trusted.
    preprocess_auto_orient_heuristic: bool = False
    preprocess_deskew: bool = True
    # Preserve the original page canvas; content cropping can cut margins/layout cues.
    preprocess_align: bool = False
    preprocess_denoise: bool = True
    preprocess_sharpen: bool = True
    preprocess_contrast: bool = True
    preprocess_high_resolution: bool = True
    cors_origins: list[str] = [
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "formocr.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def paddle_home(self) -> Path:
        return self.models_dir / "paddle"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.images_dir, self.models_dir, self.paddle_home, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        home = str(self.paddle_home)
        os.environ.setdefault("PADDLEOCR_HOME", home)
        os.environ.setdefault("PADDLE_OCR_BASE_DIR", home)


settings = Settings()
# Set before any PaddleOCR import so models stay under FormOCR data dir
settings.ensure_dirs()
