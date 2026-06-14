from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class FormType(Base):
    __tablename__ = "form_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    anchor_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_styles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    samples: Mapped[list["TemplateSample"]] = relationship(back_populates="form_type")
    templates: Mapped[list["Template"]] = relationship(back_populates="form_type")
    forms: Mapped[list["Form"]] = relationship(back_populates="form_type")


class TemplateSample(Base):
    __tablename__ = "template_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("form_types.id"), nullable=False)
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    processed_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    annotation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_index: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    form_type: Mapped["FormType"] = relationship(back_populates="samples")


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("form_types.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    form_type: Mapped["FormType"] = relationship(back_populates="templates")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    form_type_id: Mapped[int | None] = mapped_column(ForeignKey("form_types.id"), nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    forms: Mapped[list["Form"]] = relationship(back_populates="job")


class Form(Base):
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_type_id: Mapped[int | None] = mapped_column(ForeignKey("form_types.id"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("processing_jobs.id"), nullable=True)
    raw_image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    processed_image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    detection_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    form_type: Mapped["FormType | None"] = relationship(back_populates="forms")
    job: Mapped["ProcessingJob | None"] = relationship(back_populates="forms")
    corrections: Mapped[list["Correction"]] = relationship(back_populates="form")


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_action: Mapped[str] = mapped_column(String(32), default="edit")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    form: Mapped["Form"] = relationship(back_populates="corrections")


class AppSettings(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
