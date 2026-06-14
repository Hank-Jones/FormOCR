import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import {
  apiFetch,
  apiUpload,
  templateSampleImageUrl,
  type AnnotationField,
  FIELD_TYPE_OPTIONS,
  type FormType,
  type TemplateSample,
} from "../api/client";
import FieldCanvas from "../components/FieldCanvas";
import PageHeader from "../components/PageHeader";
import { useI18n } from "../i18n/context";

function prepareFieldsForSave(
  fields: AnnotationField[],
  fieldStyles: Record<string, string[]>,
  t: (key: string) => string
): AnnotationField[] {
  const keys = new Set<string>();
  const out: AnnotationField[] = [];
  for (const f of fields) {
    const key = f.key.trim();
    if (!key) throw new Error(t("template.emptyKey"));
    if (keys.has(key)) throw new Error(t("template.duplicateKey"));
    keys.add(key);
    const allowed =
      f.style_key && fieldStyles[f.style_key]
        ? [...fieldStyles[f.style_key]]
        : f.allowed_values;
    out.push({
      ...f,
      key,
      label: (f.label || "").trim() || key,
      allowed_values: allowed?.length ? allowed : null,
    });
  }
  return out;
}

function SampleCanvas({
  sampleId,
  fields,
  selectedKey,
  onSelect,
  onChange,
  onAddField,
}: {
  sampleId: number;
  fields: AnnotationField[];
  selectedKey: string | null;
  onSelect: (k: string | null) => void;
  onChange: (f: AnnotationField[]) => void;
  onAddField: (f: AnnotationField) => void;
}) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let blobUrl: string | null = null;
    let cancelled = false;
    setUrl("");
    setError("");
    templateSampleImageUrl(sampleId)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        blobUrl = u;
        setUrl(u);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [sampleId]);

  if (error) {
    return (
      <div className="card alert alert-error">
        {t("template.couldNotLoadImage")}: {error}
      </div>
    );
  }
  if (!url) return <div className="card">{t("template.loadingImage")}</div>;

  return (
    <FieldCanvas
      imageUrl={url}
      fields={fields}
      selectedKey={selectedKey}
      onSelect={onSelect}
      onChange={onChange}
      onAddField={onAddField}
    />
  );
}

export default function TemplateBuilder() {
  const { t } = useI18n();
  const location = useLocation();
  const { formTypeId: paramId } = useParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [formTypes, setFormTypes] = useState<FormType[]>([]);
  const [selectedTypeId, setSelectedTypeId] = useState<number | null>(
    paramId ? parseInt(paramId, 10) : null
  );
  const [samples, setSamples] = useState<TemplateSample[]>([]);
  const [activeSampleId, setActiveSampleId] = useState<number | null>(null);
  const [fields, setFields] = useState<AnnotationField[]>([]);
  /** Stable index — do not use field key (key changes while typing). */
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [publishResult, setPublishResult] = useState<object | null>(null);
  const [fieldStyles, setFieldStyles] = useState<Record<string, string[]>>({});
  const [newStyleName, setNewStyleName] = useState("");
  const [newStyleValues, setNewStyleValues] = useState("");
  const [publishing, setPublishing] = useState(false);

  const fieldTypeOptions = FIELD_TYPE_OPTIONS.map((opt) => ({
    ...opt,
    label: t(`fieldType.${opt.value}`),
  }));

  const loadFieldStyles = useCallback(async (id: number) => {
    const res = await apiFetch<{ field_styles: Record<string, string[]> }>(
      `/form-types/${id}/field-styles`
    );
    setFieldStyles(res.field_styles || {});
  }, []);

  const loadFormTypes = useCallback(async (): Promise<boolean> => {
    try {
      const list = await apiFetch<FormType[]>("/form-types");
      setFormTypes(list);
      if (paramId) {
        const id = parseInt(paramId, 10);
        if (!Number.isNaN(id)) {
          setSelectedTypeId(id);
        }
      }
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    }
  }, [paramId]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = async () => {
      const ok = await loadFormTypes();
      if (!stopped && !ok) {
        timer = setTimeout(run, 2000);
      }
    };
    run();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [loadFormTypes, location.pathname]);

  const loadSamples = useCallback(async (id: number) => {
    const list = await apiFetch<TemplateSample[]>(
      `/templates/form-type/${id}/samples`
    );
    setSamples(list);
    if (list.length) {
      setActiveSampleId((prev) =>
        prev && list.some((s) => s.id === prev) ? prev : list[0].id
      );
    } else {
      setActiveSampleId(null);
    }
  }, []);

  useEffect(() => {
    if (selectedTypeId) {
      loadSamples(selectedTypeId).catch((e) => setError(String(e)));
      loadFieldStyles(selectedTypeId).catch((e) => setError(String(e)));
    } else {
      setFieldStyles({});
    }
  }, [selectedTypeId, loadSamples, loadFieldStyles]);

  const saveFieldStyles = async (styles: Record<string, string[]>) => {
    if (!selectedTypeId) return;
    await apiFetch(`/form-types/${selectedTypeId}/field-styles`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field_styles: styles }),
    });
    setFieldStyles(styles);
    await loadFormTypes();
  };

  const addFieldStyle = () => {
    const name = newStyleName.trim();
    if (!name) return;
    const vals = newStyleValues
      .split(/[,;\n]+/)
      .map((v) => v.trim())
      .filter(Boolean);
    if (!vals.length) return;
    const next = { ...fieldStyles, [name]: vals };
    setNewStyleName("");
    setNewStyleValues("");
    saveFieldStyles(next).catch((e) => setError(String(e)));
  };

  const removeFieldStyle = (name: string) => {
    const next = { ...fieldStyles };
    delete next[name];
    saveFieldStyles(next).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    const s = samples.find((x) => x.id === activeSampleId);
    if (s) setFields(s.annotations || []);
    setSelectedIndex(null);
  }, [activeSampleId, samples]);

  const uploadSample = async (file: File) => {
    setError("");
    if (!selectedTypeId) {
      setError(t("template.selectFormTypeFirst"));
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("form_type_id", String(selectedTypeId));
      fd.append("file", file);
      fd.append("page_index", "0");
      const sample = await apiUpload<TemplateSample>("/templates/samples", fd);
      await loadSamples(selectedTypeId);
      setActiveSampleId(sample.id);
      setFields([]);
      setSelectedIndex(null);
      setMessage(t("template.sampleUploaded", { name: file.name }));
    } catch (e) {
      setError(String(e));
      setMessage("");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const saveAndPublish = async () => {
    if (!selectedTypeId) return;
    if (!activeSampleId) {
      setError(t("template.needSample"));
      return;
    }
    setError("");
    setPublishing(true);
    try {
      const prepared = prepareFieldsForSave(fields, fieldStyles, t);
      if (prepared.length === 0) {
        setError(t("template.noFields"));
        return;
      }
      await apiFetch(`/templates/samples/${activeSampleId}/annotations`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: prepared }),
      });
      await loadSamples(selectedTypeId);
      const result = await apiFetch<object>(
        `/templates/${selectedTypeId}/publish`,
        { method: "POST" }
      );
      setPublishResult(result);
      setMessage(t("template.published"));
      sessionStorage.setItem("formocr_select_form_type", String(selectedTypeId));
      await loadFormTypes();
    } catch (e) {
      setError(String(e));
    } finally {
      setPublishing(false);
    }
  };

  const deleteSelectedField = useCallback(() => {
    if (selectedIndex == null) return;
    setFields((prev) => prev.filter((_, i) => i !== selectedIndex));
    setSelectedIndex(null);
  }, [selectedIndex]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      e.preventDefault();
      deleteSelectedField();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteSelectedField]);

  const selectedField =
    selectedIndex != null && selectedIndex >= 0 && selectedIndex < fields.length
      ? fields[selectedIndex]
      : undefined;

  const canvasSelectedKey =
    selectedIndex != null && fields[selectedIndex]
      ? fields[selectedIndex].key
      : null;

  const selectFieldByKey = (key: string | null) => {
    if (key == null) {
      setSelectedIndex(null);
      return;
    }
    const idx = fields.findIndex((f) => f.key === key);
    setSelectedIndex(idx >= 0 ? idx : null);
  };

  const updateSelectedField = (patch: Partial<AnnotationField>) => {
    if (selectedIndex == null) return;
    setFields(
      fields.map((f, i) => (i === selectedIndex ? { ...f, ...patch } : f))
    );
  };

  return (
    <div className="page page--pro">
      <PageHeader
        title={t("page.templates")}
        backTo="/form-types"
        backLabel={t("nav.formTypes")}
      />
      <div className="card card--compact template-toolbar">
        <div className="template-toolbar__field">
          <label htmlFor="template-form-type">{t("common.formType")}</label>
          <select
            id="template-form-type"
            value={selectedTypeId ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              if (!v) {
                setSelectedTypeId(null);
                setActiveSampleId(null);
                setSamples([]);
                return;
              }
              const id = parseInt(v, 10);
              setSelectedTypeId(id);
              setActiveSampleId(null);
              setSamples([]);
              setMessage("");
            }}
          >
            <option value="">{t("template.selectType")}</option>
            {formTypes.map((ft) => (
              <option key={ft.id} value={ft.id}>
                {ft.name}
              </option>
            ))}
          </select>
        </div>
        <div className="template-toolbar__actions">
          <label
            className={`btn btn-secondary${!selectedTypeId || uploading ? " btn-disabled" : ""}`}
          >
            {uploading ? t("template.uploading") : t("template.uploadSample")}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/jpg,image/tiff,image/bmp,.pdf"
              hidden
              disabled={!selectedTypeId || uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadSample(f);
                e.target.value = "";
              }}
            />
          </label>
          <button
            type="button"
            className="btn"
            onClick={saveAndPublish}
            disabled={!selectedTypeId || !activeSampleId || publishing}
          >
            {publishing ? t("common.loading") : t("template.savePublish")}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-info">{message}</div>}

      {selectedTypeId && samples.length > 0 && (
        <div className="toolbar">
          {samples.map((s, i) => (
            <button
              key={s.id}
              className={`btn ${activeSampleId === s.id ? "" : "btn-secondary"}`}
              onClick={() => setActiveSampleId(s.id)}
            >
              Sample {i + 1}
            </button>
          ))}
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: "1rem" }}>
        {activeSampleId ? (
          <SampleCanvas
            sampleId={activeSampleId}
            fields={fields}
            selectedKey={canvasSelectedKey}
            onSelect={selectFieldByKey}
            onChange={setFields}
            onAddField={(f) => {
              setFields([...fields, f]);
              setSelectedIndex(fields.length);
            }}
          />
        ) : (
          <div className="card" style={{ minHeight: 320, color: "var(--muted)" }}>
            {t("template.samplePlaceholder")}
          </div>
        )}
        <div
          className="card"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <h3>{t("template.fieldProperties")}</h3>
          {selectedField ? (
            <>
              <div className="form-group">
                <label>{t("template.fieldKey")}</label>
                <input
                  value={selectedField.key}
                  onChange={(e) => updateSelectedField({ key: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label>{t("template.fieldLabel")}</label>
                <input
                  value={selectedField.label}
                  onChange={(e) => updateSelectedField({ label: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label>{t("template.fieldType")}</label>
                <select
                  value={selectedField.field_type}
                  onChange={(e) =>
                    updateSelectedField({
                      field_type: e.target.value as AnnotationField["field_type"],
                    })
                  }
                >
                  {fieldTypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>{t("template.lineCount")}</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={selectedField.line_count ?? ""}
                  placeholder="1"
                  onChange={(e) => {
                    const raw = e.target.value.trim();
                    const n = raw === "" ? null : parseInt(raw, 10);
                    updateSelectedField({
                      line_count:
                        n !== null && !Number.isNaN(n) && n >= 2 ? n : null,
                    });
                  }}
                />
              </div>
              <div className="form-group">
                <label>{t("template.valueStyle")}</label>
                <select
                  value={selectedField.style_key || ""}
                  onChange={(e) =>
                    updateSelectedField({
                      style_key: e.target.value || null,
                      allowed_values: e.target.value
                        ? fieldStyles[e.target.value] || null
                        : null,
                    })
                  }
                >
                  <option value="">{t("template.valueStyleNone")}</option>
                  {Object.keys(fieldStyles).map((sk) => (
                    <option key={sk} value={sk}>
                      {sk} ({fieldStyles[sk].join(", ")})
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn btn-danger" onClick={deleteSelectedField}>
                {t("template.deleteField")}
              </button>
            </>
          ) : (
            <p style={{ color: "var(--muted)" }}>{t("template.drawHint")}</p>
          )}

          {selectedTypeId && (
            <div className="field-styles-editor">
              <h3>{t("template.customStyles")}</h3>
              {Object.entries(fieldStyles).map(([name, vals]) => (
                <div key={name} className="field-style-row">
                  <strong>{name}</strong>
                  <span className="style-values-input">{vals.join(", ")}</span>
                  <button
                    type="button"
                    className="btn btn-danger"
                    style={{ padding: "0.15rem 0.4rem", fontSize: "0.75rem" }}
                    onClick={() => removeFieldStyle(name)}
                  >
                    ×
                  </button>
                </div>
              ))}
              <div className="form-group" style={{ marginTop: "0.75rem" }}>
                <label>{t("template.newStyleName")}</label>
                <input
                  value={newStyleName}
                  onChange={(e) => setNewStyleName(e.target.value)}
                  placeholder="e.g. TypeA"
                />
              </div>
              <div className="form-group">
                <label>{t("template.allowedValues")}</label>
                <input
                  className="style-values-input"
                  value={newStyleValues}
                  onChange={(e) => setNewStyleValues(e.target.value)}
                  placeholder="AA, BB, CC"
                />
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={addFieldStyle}
                disabled={!newStyleName.trim() || !newStyleValues.trim()}
              >
                {t("template.addStyle")}
              </button>
            </div>
          )}
        </div>
      </div>
      {publishResult && (
        <div className="card">
          <h3>{t("template.publishedPreview")}</h3>
          <pre style={{ fontSize: 12, overflow: "auto" }}>
            {JSON.stringify(publishResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
