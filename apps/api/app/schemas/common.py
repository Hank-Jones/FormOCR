from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.field_types import FieldType


class ReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AnnotationField(BaseModel):
    key: str
    label: str
    field_type: FieldType = FieldType.custom
    bbox_norm: list[float] = Field(..., min_length=4, max_length=4)
    style_key: str | None = None
    allowed_values: list[str] | None = None
    line_count: int | None = Field(default=None, ge=1, le=20)


class AnnotationsPayload(BaseModel):
    fields: list[AnnotationField]


class TemplateField(BaseModel):
    bbox_norm: list[float]
    field_type: FieldType
    tolerance: float = 0.02
    label: str | None = None
    style_key: str | None = None
    allowed_values: list[str] | None = None
    line_count: int | None = Field(default=None, ge=1, le=20)


class TemplatePayload(BaseModel):
    form_type: str
    version: int
    fields: dict[str, TemplateField]
    anchors: list[str] = []
    field_styles: dict[str, list[str]] = Field(default_factory=dict)
    # Processed sample page size (width, height) that field bboxes are relative to.
    reference_size: list[int] | None = Field(default=None, min_length=2, max_length=2)


class FieldExtraction(BaseModel):
    text: str = ""
    confidence: float = 0.0
    engine: str = "unknown"
    qwen_text: str | None = None
    paddle_text: str | None = None
    tesseract_text: str | None = None
    phi3_text: str | None = None


class ProcessingResult(BaseModel):
    fields: dict[str, FieldExtraction]
    validated: dict[str, Any] | None = None
    corrected: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    api: bool
    ocr_ready: bool
    ocr_warming: bool | None = None
    ollama_ready: bool
    ollama_model_present: bool
    handwriting_ocr_enabled: bool | None = None
    handwriting_model_present: bool | None = None
    handwriting_ollama_model: str | None = None
    data_dir: str
    paddle_models_dir: str | None = None
    ocr_error: str | None = None
    ollama_model: str | None = None
    ocr_lang: str | None = None
    api_build: str | None = None
    ollama_host: str | None = None
    ollama_on_gpu: bool | None = None
    ollama_vram_mb: int | None = None
    ollama_gpu_summary: str | None = None


class FormTypeCreate(BaseModel):
    name: str


class FormTypeUpdate(BaseModel):
    name: str | None = None


class FormTypeOut(BaseModel):
    id: int
    name: str
    version: int
    status: str
    anchor_keywords: list[str] | None = None
    field_styles: dict[str, list[str]] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TemplateSampleOut(BaseModel):
    id: int
    form_type_id: int
    image_path: str
    page_index: int
    width: int | None
    height: int | None
    annotations: list[AnnotationField] | None = None

    model_config = {"from_attributes": True}


class FormFieldMeta(BaseModel):
    key: str
    label: str
    field_type: str
    line_count: int | None = None
    bbox_norm: list[float] | None = Field(default=None, min_length=4, max_length=4)


class FormOut(BaseModel):
    id: int
    form_type_id: int | None
    job_id: int | None
    raw_image_path: str
    processed_image_path: str | None
    extracted: dict[str, Any] | None = None
    validated: dict[str, Any] | None = None
    corrected: dict[str, Any] | None = None
    confidence: dict[str, float] | None = None
    review_status: str
    detection_score: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    status: str
    form_type_id: int | None
    total_count: int
    processed_count: int
    created_at: datetime
    completed_at: datetime | None = None
    phase: str | None = None
    message: str | None = None
    fields_total: int | None = None
    fields_done: int | None = None
    progress_percent: int | None = None
    ocr_lang: str | None = None
    handwriting_model: str | None = None
    ai_model: str | None = None
    ocr_engine_counts: dict[str, int] | None = None
    ai_error: str | None = None
    steps: list[str] | None = None
    last_field_key: str | None = None
    last_field_engine: str | None = None
    form_ids: list[int] | None = None
    current_form_id: int | None = None
    preview_raw_path: str | None = None
    preview_processed_path: str | None = None
    pipeline: dict[str, str] | None = None

    model_config = {"from_attributes": True}


class ReviewPayload(BaseModel):
    corrected: dict[str, Any]
    status: ReviewStatus
    corrections: list[dict[str, str]] | None = None


class ProcessOptions(BaseModel):
    form_type_id: int | None = None
    use_ai: bool | None = None
    auto_detect: bool = False
    field_overrides: list[AnnotationField] | None = None


class DetectionResult(BaseModel):
    form_type_id: int | None
    form_type_name: str | None
    score: float
    method: str
