import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useI18n } from "../i18n/useI18n";

type ResizableSplitProps = {
  left: ReactNode;
  right: ReactNode;
  /** Percent width of the left pane (0–100). */
  defaultLeftPct?: number;
  minLeftPct?: number;
  maxLeftPct?: number;
  storageKey?: string;
  className?: string;
};

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

export default function ResizableSplit({
  left,
  right,
  defaultLeftPct = 58,
  minLeftPct = 30,
  maxLeftPct = 82,
  storageKey,
  className = "",
}: ResizableSplitProps) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const readStored = () => {
    if (!storageKey) return defaultLeftPct;
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return defaultLeftPct;
    const n = parseFloat(raw);
    return Number.isFinite(n) ? clamp(n, minLeftPct, maxLeftPct) : defaultLeftPct;
  };

  const [leftPct, setLeftPct] = useState(readStored);

  useEffect(() => {
    if (!storageKey) return;
    sessionStorage.setItem(storageKey, String(leftPct));
  }, [leftPct, storageKey]);

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!dragging.current || !rootRef.current) return;
      const rect = rootRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const pct = (x / rect.width) * 100;
      setLeftPct(clamp(pct, minLeftPct, maxLeftPct));
    },
    [minLeftPct, maxLeftPct]
  );

  const endDrag = useCallback(() => {
    dragging.current = false;
    document.body.classList.remove("resize-split-dragging");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", endDrag);
    window.removeEventListener("pointercancel", endDrag);
  }, [onPointerMove]);

  const startDrag = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging.current = true;
    document.body.classList.add("resize-split-dragging");
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 5 : 2;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setLeftPct((p) => clamp(p - step, minLeftPct, maxLeftPct));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      setLeftPct((p) => clamp(p + step, minLeftPct, maxLeftPct));
    } else if (e.key === "Home") {
      e.preventDefault();
      setLeftPct(minLeftPct);
    } else if (e.key === "End") {
      e.preventDefault();
      setLeftPct(maxLeftPct);
    }
  };

  return (
    <div
      ref={rootRef}
      className={`resize-split ${className}`.trim()}
      style={{ ["--split-left" as string]: `${leftPct}%` }}
    >
      <div className="resize-split-pane resize-split-pane--left">{left}</div>
      <div
        className="resize-split-handle"
        role="separator"
        aria-orientation="vertical"
        aria-valuenow={Math.round(leftPct)}
        aria-valuemin={minLeftPct}
        aria-valuemax={maxLeftPct}
        aria-label={t("review.resizeHandle")}
        tabIndex={0}
        onPointerDown={startDrag}
        onKeyDown={onKeyDown}
      />
      <div className="resize-split-pane resize-split-pane--right">{right}</div>
    </div>
  );
}
