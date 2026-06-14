import { useCallback, useRef, useState } from "react";
import type { AnnotationField, FieldType } from "../api/client";

interface Props {
  imageUrl: string;
  fields: AnnotationField[];
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  onChange: (fields: AnnotationField[]) => void;
  onAddField: (field: AnnotationField) => void;
}

export default function FieldCanvas({
  imageUrl,
  fields,
  selectedKey,
  onSelect,
  onChange,
  onAddField,
}: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [drawing, setDrawing] = useState<{
    startX: number;
    startY: number;
    curX: number;
    curY: number;
  } | null>(null);
  const [imgError, setImgError] = useState(false);
  const [drag, setDrag] = useState<{
    key: string;
    mode: "move" | "resize";
    ox: number;
    oy: number;
    ob: number[];
  } | null>(null);

  const imageRect = useCallback(() => {
    return imgRef.current?.getBoundingClientRect() ?? null;
  }, []);

  const toNorm = useCallback(
    (px: number, py: number, pw: number, ph: number): [number, number, number, number] => {
      const rect = imageRect();
      if (!rect || rect.width < 1 || rect.height < 1) return [0, 0, 0, 0];
      const x = px / rect.width;
      const y = py / rect.height;
      const w = pw / rect.width;
      const h = ph / rect.height;
      return [
        Math.max(0, Math.min(1, x)),
        Math.max(0, Math.min(1, y)),
        Math.max(0.01, Math.min(1 - x, w)),
        Math.max(0.01, Math.min(1 - y, h)),
      ];
    },
    [imageRect]
  );

  const pointerOnImage = (clientX: number, clientY: number) => {
    const rect = imageRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: clientX - rect.left, y: clientY - rect.top };
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).classList.contains("field-rect")) return;
    const { x, y } = pointerOnImage(e.clientX, e.clientY);
    setDrawing({ startX: x, startY: y, curX: x, curY: y });
    onSelect(null);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = imageRect();
    if (!rect) return;
    const { x, y } = pointerOnImage(e.clientX, e.clientY);
    if (drawing) {
      setDrawing({ ...drawing, curX: x, curY: y });
    }
    if (drag) {
      const f = fields.find((ff) => ff.key === drag.key);
      if (!f) return;
      const dx = (x - drag.ox) / rect.width;
      const dy = (y - drag.oy) / rect.height;
      let [nx, ny, nw, nh] = [...f.bbox_norm] as [number, number, number, number];
      if (drag.mode === "move") {
        nx = Math.max(0, Math.min(1 - nw, drag.ob[0] + dx));
        ny = Math.max(0, Math.min(1 - nh, drag.ob[1] + dy));
      } else {
        nw = Math.max(0.02, drag.ob[2] + dx);
        nh = Math.max(0.02, drag.ob[3] + dy);
      }
      onChange(
        fields.map((ff) =>
          ff.key === drag.key ? { ...ff, bbox_norm: [nx, ny, nw, nh] } : ff
        )
      );
    }
  };

  const handleMouseUp = () => {
    if (drawing) {
      const x1 = Math.min(drawing.startX, drawing.curX);
      const y1 = Math.min(drawing.startY, drawing.curY);
      const w = Math.abs(drawing.curX - drawing.startX);
      const h = Math.abs(drawing.curY - drawing.startY);
      if (w > 8 && h > 8) {
        const bbox = toNorm(x1, y1, w, h);
        const key = `field_${fields.length + 1}`;
        onAddField({
          key,
          label: key,
          field_type: "custom" as FieldType,
          bbox_norm: bbox,
        });
        onSelect(key);
      }
      setDrawing(null);
    }
    setDrag(null);
  };

  const previewRect = drawing
    ? {
        left: Math.min(drawing.startX, drawing.curX),
        top: Math.min(drawing.startY, drawing.curY),
        width: Math.abs(drawing.curX - drawing.startX),
        height: Math.abs(drawing.curY - drawing.startY),
      }
    : null;

  return (
    <div
      className="field-canvas-wrap"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div className="field-canvas-inner">
        <img
          ref={imgRef}
          src={imageUrl}
          alt="Form sample"
          draggable={false}
          onLoad={() => setImgError(false)}
          onError={() => setImgError(true)}
        />
        {imgError && (
          <div className="field-canvas-img-error">
            Image failed to display. Check that the API is running.
          </div>
        )}
        {fields.map((f, index) => {
          const [x, y, w, h] = f.bbox_norm;
          return (
            <div
              key={`${index}-${f.key}`}
              className={`field-rect ${selectedKey === f.key ? "selected" : ""}`}
              style={{
                left: `${x * 100}%`,
                top: `${y * 100}%`,
                width: `${w * 100}%`,
                height: `${h * 100}%`,
              }}
              onMouseDown={(e) => {
                e.stopPropagation();
                onSelect(f.key);
                const pt = pointerOnImage(e.clientX, e.clientY);
                setDrag({
                  key: f.key,
                  mode: e.shiftKey ? "resize" : "move",
                  ox: pt.x,
                  oy: pt.y,
                  ob: [...f.bbox_norm],
                });
              }}
            >
              <span className="field-rect-label">{f.label}</span>
            </div>
          );
        })}
        {previewRect && (
          <div
            className="field-rect field-rect-preview"
            style={{
              left: previewRect.left,
              top: previewRect.top,
              width: previewRect.width,
              height: previewRect.height,
            }}
          />
        )}
      </div>
    </div>
  );
}
