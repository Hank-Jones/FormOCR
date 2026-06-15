import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import ResizableSplit from "../components/ResizableSplit";
import ReviewImageViewer from "../components/ReviewImageViewer";
import {
  apiFetch,
  apiImageBlobUrl,
  type FormFieldMeta,
  type FormRecord,
} from "../api/client";
import { usePendingReview } from "../context/PendingReviewContext";
import { useI18n } from "../i18n/useI18n";

function confClass(c: number | undefined): string {
  if (c === undefined) return "";
  if (c >= 0.9) return "conf-high";
  if (c >= 0.7) return "conf-mid";
  return "conf-low";
}

const TWO_COLUMN_MIN_FIELDS = 6;

export default function ReviewPage() {
  const { t } = useI18n();
  const { refresh: refreshPendingCount } = usePendingReview();
  const { formId: paramId } = useParams();
  const navigate = useNavigate();
  const [queue, setQueue] = useState<FormRecord[]>([]);
  const [form, setForm] = useState<FormRecord | null>(null);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [imgSrc, setImgSrc] = useState("");
  const [saving, setSaving] = useState(false);
  const [fieldMeta, setFieldMeta] = useState<Record<string, FormFieldMeta>>({});
  const [selectedFieldKey, setSelectedFieldKey] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<FormRecord[]>("/forms?review_status=pending&limit=50").then(
      setQueue
    );
  }, []);

  useEffect(() => {
    const id = paramId ? parseInt(paramId, 10) : queue[0]?.id;
    if (!id) return;
    let blobUrl: string | null = null;
    apiFetch<FormRecord>(`/forms/${id}`).then(async (f) => {
      setForm(f);
      try {
        const meta = await apiFetch<FormFieldMeta[]>(`/forms/${f.id}/fields`);
        const map: Record<string, FormFieldMeta> = {};
        for (const m of meta) map[m.key] = m;
        setFieldMeta(map);
        const first = meta.find((m) => m.bbox_norm)?.key ?? null;
        setSelectedFieldKey(first);
      } catch {
        setFieldMeta({});
        setSelectedFieldKey(null);
      }
      const flat: Record<string, string> = {};
      const extracted = f.extracted || {};
      const validated = f.validated || {};
      const corrected = f.corrected || {};
      const keys = new Set([
        ...Object.keys(extracted),
        ...Object.keys(validated),
        ...Object.keys(corrected),
      ]);
      for (const k of keys) {
        const fromCorrected = corrected[k];
        const fromValidated = validated[k];
        const fromExtracted = extracted[k];
        if (fromCorrected != null && fromCorrected !== "") {
          flat[k] =
            typeof fromCorrected === "object" && "text" in (fromCorrected as object)
              ? String((fromCorrected as { text: string }).text)
              : String(fromCorrected);
        } else if (fromValidated != null && fromValidated !== "") {
          flat[k] = String(fromValidated);
        } else if (
          fromExtracted &&
          typeof fromExtracted === "object" &&
          "text" in fromExtracted
        ) {
          flat[k] = String((fromExtracted as { text: string }).text);
        } else {
          flat[k] = "";
        }
      }
      setEdited(flat);
      apiImageBlobUrl(`/forms/${f.id}/image?processed=false`)
        .then((u) => {
          blobUrl = u;
          setImgSrc(u);
        })
        .catch(console.error);
    });
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [paramId, queue]);

  const submit = async (status: "approved" | "rejected") => {
    if (!form) return;
    setSaving(true);
    try {
      await apiFetch(`/forms/${form.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrected: edited, status }),
      });
      const next = queue.find((q) => q.id !== form.id);
      if (next) navigate(`/review/${next.id}`);
      else navigate("/review");
      setQueue((q) => q.filter((x) => x.id !== form.id));
      setForm(null);
      refreshPendingCount();
    } finally {
      setSaving(false);
    }
  };

  const keys = useMemo(() => Object.keys(edited).sort(), [edited]);
  const multiColumn = keys.length >= TWO_COLUMN_MIN_FIELDS;
  const queueIndex = form ? queue.findIndex((q) => q.id === form.id) : -1;

  if (!form) {
    return (
      <div className="page page--pro page--review">
        <PageHeader title={t("page.review")} />
        <p className="empty-state">{t("review.noPending")}</p>
        <ul>
          {queue.map((f) => (
            <li key={f.id}>
              <Link to={`/review/${f.id}`}>{t("process.form", { id: f.id })}</Link>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="page page--pro page--review">
      <PageHeader
        title={t("page.reviewForm", { id: form.id })}
        actions={
          queue.length > 1 ? (
            <div className="review-queue-nav">
              {queueIndex > 0 && (
                <Link
                  to={`/review/${queue[queueIndex - 1].id}`}
                  className="btn btn-sm btn-secondary"
                >
                  {t("review.prevForm")}
                </Link>
              )}
              {queueIndex >= 0 && queueIndex < queue.length - 1 && (
                <Link
                  to={`/review/${queue[queueIndex + 1].id}`}
                  className="btn btn-sm btn-secondary"
                >
                  {t("review.nextForm")}
                </Link>
              )}
            </div>
          ) : undefined
        }
      />

      <ResizableSplit
        className="review-split"
        storageKey="formocr-review-split"
        defaultLeftPct={60}
        minLeftPct={32}
        maxLeftPct={85}
        left={
          <section className="review-pane review-pane--image" aria-label={t("review.imagePane")}>
            <ReviewImageViewer
              src={imgSrc}
              boxes={Object.values(fieldMeta)
                .filter((m): m is FormFieldMeta & { bbox_norm: [number, number, number, number] } =>
                  Array.isArray(m.bbox_norm) && m.bbox_norm.length === 4
                )
                .map((m) => ({
                  key: m.key,
                  bbox_norm: m.bbox_norm,
                  active: m.key === selectedFieldKey,
                }))}
              onSelectBox={(key) => setSelectedFieldKey(key)}
            />
          </section>
        }
        right={
          <section className="review-pane review-pane--fields" aria-label={t("review.fieldsPane")}>
            <div className="review-fields-scroll">
              <div
                className={`review-fields-grid${multiColumn ? " review-fields-grid--two" : ""}`}
              >
                {keys.map((key) => {
                  const lines = fieldMeta[key]?.line_count ?? 0;
                  const multiline = lines >= 2;
                  return (
                    <div
                      key={key}
                      className={`form-group review-field-item${
                        selectedFieldKey === key ? " review-field-item--active" : ""
                      }`}
                      onClick={() => setSelectedFieldKey(key)}
                    >
                      <label htmlFor={`review-field-${key}`}>
                        {key}
                        {multiline ? ` (${t("review.multiline", { count: lines })})` : ""}
                      </label>
                      {multiline ? (
                        <textarea
                          id={`review-field-${key}`}
                          className={confClass(form.confidence?.[key])}
                          rows={lines}
                          value={edited[key] ?? ""}
                          onChange={(e) =>
                            setEdited({ ...edited, [key]: e.target.value })
                          }
                        />
                      ) : (
                        <input
                          id={`review-field-${key}`}
                          className={confClass(form.confidence?.[key])}
                          value={edited[key] ?? ""}
                          onChange={(e) =>
                            setEdited({ ...edited, [key]: e.target.value })
                          }
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="review-actions toolbar">
              <button
                type="button"
                className="btn"
                disabled={saving}
                onClick={() => submit("approved")}
              >
                {t("common.approve")}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={saving}
                onClick={() => submit("rejected")}
              >
                {t("common.reject")}
              </button>
            </div>
          </section>
        }
      />
    </div>
  );
}
