import { useEffect, useState, type ReactNode } from "react";

import ImageLightbox from "./ImageLightbox";

import {
  apiImageBlobUrl,
  jobPreviewImageUrl,
  type FormRecord,
  type Job,
} from "../api/client";
import { useI18n } from "../i18n/context";

import FieldCropsGrid from "./FieldCropsGrid";

function PreviewPane({
  title,
  url,
  empty,
  children,
  onImageClick,
}: {
  title: string;
  url: string | null;
  empty: string;
  children?: ReactNode;
  onImageClick?: () => void;
}) {
  return (
    <div className="process-preview-pane">
      <h4 className="process-preview-title">{title}</h4>
      {url ? (
        <button
          type="button"
          className="process-preview-img-btn"
          onClick={onImageClick}
          title={title}
          aria-label={title}
        >
          <img src={url} alt={title} className="process-preview-img" />
        </button>
      ) : empty ? (
        <div className="process-preview-placeholder">{empty}</div>
      ) : null}
      {children}
    </div>
  );
}

export default function ProcessingPreview({
  job,
  form,
}: {
  job: Job;
  form: FormRecord | null;
}) {
  const { t } = useI18n();
  const [rawUrl, setRawUrl] = useState<string | null>(null);
  const [processedUrl, setProcessedUrl] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<{ src: string; title: string } | null>(
    null
  );

  const formId = job.current_form_id ?? form?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    const blobs: string[] = [];

    const load = async () => {
      try {
        if (formId) {
          const [raw, proc] = await Promise.all([
            apiImageBlobUrl(`/forms/${formId}/image?processed=false`),
            apiImageBlobUrl(`/forms/${formId}/image?processed=true`),
          ]);
          if (cancelled) {
            URL.revokeObjectURL(raw);
            URL.revokeObjectURL(proc);
            return;
          }
          blobs.push(raw, proc);
          setRawUrl(raw);
          setProcessedUrl(proc);
          return;
        }
        if (!job.preview_raw_path && !job.preview_processed_path) {
          setRawUrl(null);
          setProcessedUrl(null);
          return;
        }
        const [raw, proc] = await Promise.all([
          job.preview_raw_path
            ? jobPreviewImageUrl(job.id, "raw")
            : Promise.resolve(null),
          job.preview_processed_path
            ? jobPreviewImageUrl(job.id, "processed")
            : Promise.resolve(null),
        ]);
        if (cancelled) {
          if (raw) URL.revokeObjectURL(raw);
          if (proc) URL.revokeObjectURL(proc);
          return;
        }
        if (raw) blobs.push(raw);
        if (proc) blobs.push(proc);
        setRawUrl(raw);
        setProcessedUrl(proc);
      } catch {
        if (!cancelled) {
          setRawUrl(null);
          setProcessedUrl(null);
        }
      }
    };

    load();
    return () => {
      cancelled = true;
      blobs.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [
    formId,
    job.id,
    job.preview_raw_path,
    job.preview_processed_path,
    form?.extracted,
    form?.corrected,
    form?.validated,
  ]);

  const phaseHint =
    job.phase === "preprocess"
      ? t("preview.phase.preprocess")
      : job.phase === "ocr"
        ? t("preview.phase.ocr")
        : job.phase === "save"
          ? t("preview.phase.save")
          : job.message || t("preview.phase.default");

  return (
    <>
      <div className="process-preview-grid">
        <PreviewPane
          title={t("preview.pane.input")}
          url={rawUrl}
          empty={t("preview.waitingUpload")}
          onImageClick={
            rawUrl
              ? () =>
                  setLightbox({ src: rawUrl, title: t("preview.pane.input") })
              : undefined
          }
        />
        <PreviewPane
          title={t("preview.pane.preprocessed")}
          url={processedUrl}
          empty={
            job.phase === "preprocess"
              ? t("preview.preprocessing")
              : t("preview.waiting")
          }
          onImageClick={
            processedUrl
              ? () =>
                  setLightbox({
                    src: processedUrl,
                    title: t("preview.pane.preprocessed"),
                  })
              : undefined
          }
        />
      <PreviewPane title={t("preview.pane.result")} url={null} empty="">
        {formId ? (
          <FieldCropsGrid
            formId={formId}
            form={form}
            emptyHint={
              form?.review_status === "processing"
                ? phaseHint
                : form?.review_status && form.review_status !== "pending"
                  ? `${t("common.status")}: ${form.review_status}`
                  : phaseHint
            }
          />
        ) : (
          <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
            {phaseHint}
          </p>
        )}
      </PreviewPane>
      </div>
      {lightbox && (
        <ImageLightbox
          src={lightbox.src}
          title={lightbox.title}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}
