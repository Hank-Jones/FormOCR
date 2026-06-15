import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n/useI18n";

const ZOOM_MIN = 0.35;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 0.15;
const STORAGE_KEY = "formocr-review-zoom";

type ReviewImageViewerProps = {
  src: string;
  alt?: string;
  wheelZoomWithoutModifier?: boolean;
  boxes?: Array<{
    key: string;
    bbox_norm: [number, number, number, number];
    active?: boolean;
  }>;
  onSelectBox?: (key: string) => void;
};

export default function ReviewImageViewer({
  src,
  alt = "Form scan",
  wheelZoomWithoutModifier = false,
  boxes = [],
  onSelectBox,
}: ReviewImageViewerProps) {
  const { t } = useI18n();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(() => {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return 1;
    const n = parseFloat(raw);
    return Number.isFinite(n) ? Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, n)) : 1;
  });
  const [fitWidth, setFitWidth] = useState(() => !sessionStorage.getItem(STORAGE_KEY));

  useEffect(() => {
    if (!fitWidth) {
      sessionStorage.setItem(STORAGE_KEY, String(zoom));
    }
  }, [zoom, fitWidth]);

  const applyZoom = useCallback((next: number) => {
    setFitWidth(false);
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)));
  }, []);

  const zoomIn = () => applyZoom(zoom + ZOOM_STEP);
  const zoomOut = () => applyZoom(zoom - ZOOM_STEP);
  const zoomReset = () => {
    setFitWidth(true);
    sessionStorage.removeItem(STORAGE_KEY);
  };
  const zoomActual = () => applyZoom(1);

  const onWheel = (e: React.WheelEvent) => {
    if (!wheelZoomWithoutModifier && !e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
    applyZoom(zoom + delta);
  };

  return (
    <div className="review-image-viewer">
      <div className="review-image-toolbar" role="toolbar" aria-label={t("review.imageToolbar")}>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={zoomOut}
          disabled={!src || (!fitWidth && zoom <= ZOOM_MIN)}
          title={t("review.zoomOut")}
        >
          −
        </button>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={zoomReset}
          disabled={!src}
          title={t("review.fitWidth")}
        >
          {t("review.fitWidth")}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={zoomActual}
          disabled={!src}
          title={t("review.actualSize")}
        >
          100%
        </button>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={zoomIn}
          disabled={!src || (!fitWidth && zoom >= ZOOM_MAX)}
          title={t("review.zoomIn")}
        >
          +
        </button>
        <span className="review-image-zoom-label" aria-live="polite">
          {fitWidth ? t("review.zoomFit") : `${Math.round(zoom * 100)}%`}
        </span>
      </div>
      <div
        ref={viewportRef}
        className="review-image-viewport"
        onWheel={onWheel}
      >
        {src ? (
          <div
            className={`review-image-stage${fitWidth ? " review-image-stage--fit" : ""}`}
          >
            <img
              src={src}
              alt={alt}
              className={`review-image-img${fitWidth ? " review-image-img--fit" : ""}`}
              style={fitWidth ? undefined : { width: `${zoom * 100}%` }}
              draggable={false}
            />
            <div className="review-image-overlay" aria-hidden>
              {boxes.map((box) => {
                const [x, y, w, h] = box.bbox_norm;
                return (
                  <button
                    key={box.key}
                    type="button"
                    className={`review-image-box${box.active ? " review-image-box--active" : ""}`}
                    style={{
                      left: `${x * 100}%`,
                      top: `${y * 100}%`,
                      width: `${w * 100}%`,
                      height: `${h * 100}%`,
                    }}
                    onClick={() => onSelectBox?.(box.key)}
                    title={box.key}
                    aria-label={box.key}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <div className="review-image-empty muted">{t("review.noImage")}</div>
        )}
      </div>
    </div>
  );
}
