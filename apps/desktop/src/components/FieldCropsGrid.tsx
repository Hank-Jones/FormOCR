import { useEffect, useState } from "react";

import {
  apiFetch,
  formFieldCropUrl,
  type FormFieldMeta,
  type FormRecord,
} from "../api/client";

import ImageLightbox from "./ImageLightbox";
import { useI18n } from "../i18n/useI18n";
import { displayFields } from "../utils/formFields";

type CropTile = {
  key: string;
  label: string;
  url: string | null;
  value: string;
};

export default function FieldCropsGrid({
  formId,
  form,
  emptyHint,
}: {
  formId: number;
  form: FormRecord | null;
  emptyHint: string;
}) {
  const { t } = useI18n();
  const [tiles, setTiles] = useState<CropTile[]>([]);
  const [loading, setLoading] = useState(false);
  const [lightbox, setLightbox] = useState<{ src: string; title: string } | null>(
    null
  );

  const values = form ? displayFields(form) : {};

  useEffect(() => {
    setTiles((prev) =>
      prev.map((t) => ({
        ...t,
        value: values[t.key] ?? "",
      }))
    );
  }, [form?.extracted, form?.corrected, form?.validated]);

  useEffect(() => {
    let cancelled = false;
    const blobUrls: string[] = [];

    const load = async () => {
      if (!formId || !form?.form_type_id) {
        setTiles([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const fields = await apiFetch<FormFieldMeta[]>(`/forms/${formId}/fields`);
        if (cancelled) return;
        const loaded: CropTile[] = [];
        for (const f of fields) {
          let url: string | null = null;
          try {
            url = await formFieldCropUrl(formId, f.key);
            blobUrls.push(url);
          } catch {
            url = null;
          }
          if (cancelled) {
            if (url) URL.revokeObjectURL(url);
            return;
          }
          loaded.push({
            key: f.key,
            label: f.label,
            url,
            value: values[f.key] ?? "",
          });
        }
        if (!cancelled) setTiles(loaded);
      } catch {
        if (!cancelled) setTiles([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
      blobUrls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [formId, form?.form_type_id]);

  if (!form?.form_type_id) {
    return (
      <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
        {emptyHint}
      </p>
    );
  }

  if (loading && tiles.length === 0) {
    return (
      <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
        {t("fieldCrop.loading")}
      </p>
    );
  }

  if (tiles.length === 0) {
    return (
      <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
        No template fields for this form.
      </p>
    );
  }

  return (
    <>
      <div className="field-crops-grid">
        {tiles.map((tile) => (
          <div key={tile.key} className="field-crop-tile">
            {tile.url ? (
              <button
                type="button"
                className="field-crop-img-btn"
                onClick={() =>
                  setLightbox({
                    src: tile.url!,
                    title: tile.label || tile.key,
                  })
                }
              >
                <img src={tile.url} alt={tile.label} className="field-crop-img" />
              </button>
            ) : (
              <div className="field-crop-img-missing">{t("fieldCrop.noCrop")}</div>
            )}
          <div className="field-crop-meta">
            <strong>{tile.key}</strong>
            {tile.label !== tile.key && (
              <span className="muted" style={{ marginLeft: "0.35rem" }}>
                {tile.label}
              </span>
            )}
          </div>
          <div className="field-crop-value">{tile.value || "—"}</div>
          </div>
        ))}
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
