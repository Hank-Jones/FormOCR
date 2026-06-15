import { useEffect } from "react";
import { createPortal } from "react-dom";

import ReviewImageViewer from "./ReviewImageViewer";
import { useI18n } from "../i18n/useI18n";

type Props = {
  src: string | null;
  title: string;
  onClose: () => void;
};

export default function ImageLightbox({ src, title, onClose }: Props) {
  const { t } = useI18n();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!src) return null;

  const content = (
    <div
      className="image-lightbox-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="image-lightbox-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="image-lightbox-head">
          <h3 className="image-lightbox-title">{title}</h3>
          <button
            type="button"
            className="btn btn-sm btn-secondary image-lightbox-close"
            onClick={onClose}
            aria-label={t("preview.closeLightbox")}
          >
            ×
          </button>
        </div>
        <ReviewImageViewer
          src={src}
          alt={title}
          wheelZoomWithoutModifier
        />
      </div>
    </div>
  );
  return createPortal(content, document.body);
}
