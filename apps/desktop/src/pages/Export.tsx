import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch, type FormRecord, type FormType } from "../api/client";
import { useI18n } from "../i18n/context";
import { saveExport, type ExportFormat } from "../utils/exportDownload";
import { displayFields } from "../utils/formFields";

const META_COLS = ["form_id", "form_type", "status", "created"] as const;

type ExportRow = Record<string, string>;
type ExportTab = "preview" | "result" | "edit";
type ExportEdits = Record<number, Record<string, string>>;

function buildRows(forms: FormRecord[], typeName: (id: number | null) => string): ExportRow[] {
  return forms.map((f) => {
    const fields = displayFields(f);
    const row: ExportRow = {
      form_id: String(f.id),
      form_type: typeName(f.form_type_id),
      status: f.review_status,
      created: f.created_at ? new Date(f.created_at).toLocaleDateString() : "—",
    };
    for (const [k, v] of Object.entries(fields)) {
      row[k] = v || "—";
    }
    return row;
  });
}

function fieldColumns(rows: ExportRow[]): string[] {
  const keys = new Set<string>();
  for (const r of rows) {
    for (const k of Object.keys(r)) {
      if (!META_COLS.includes(k as (typeof META_COLS)[number])) {
        keys.add(k);
      }
    }
  }
  return Array.from(keys).sort();
}

const FORMATS: ExportFormat[] = ["csv", "xlsx", "json"];

function ExportResultList({
  forms,
  typeName,
}: {
  forms: FormRecord[];
  typeName: (id: number | null) => string;
}) {
  const { t } = useI18n();

  return (
    <div className="export-result-grid">
      {forms.map((form) => {
        const fields = displayFields(form);
        const entries = Object.entries(fields);
        return (
          <section key={form.id} className="process-preview-pane export-result-pane">
            <h4 className="process-preview-title export-result-title">
              <span>{t("process.form", { id: form.id })}</span>
              <span className={`status-badge status-${form.review_status}`}>
                {form.review_status}
              </span>
            </h4>
            <div className="export-result-meta">
              <span>{typeName(form.form_type_id)}</span>
              <span>{form.created_at ? new Date(form.created_at).toLocaleDateString() : "—"}</span>
            </div>
            {entries.length > 0 ? (
              <div className="field-crops-grid export-result-fields">
                {entries.map(([key, value]) => (
                  <div key={key} className="field-crop-tile">
                    <div className="field-crop-meta">
                      <strong>{key}</strong>
                    </div>
                    <div className="field-crop-value">{value || "—"}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted export-result-empty">{t("process.noFields")}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

function editableFields(form: FormRecord): Record<string, string> {
  return displayFields(form);
}

function hasChangedEdits(form: FormRecord, edits: Record<string, string> | undefined): boolean {
  if (!edits) return false;
  const current = editableFields(form);
  const keys = new Set([...Object.keys(current), ...Object.keys(edits)]);
  for (const key of keys) {
    if ((current[key] ?? "") !== (edits[key] ?? "")) {
      return true;
    }
  }
  return false;
}

function buildEditedRows(
  forms: FormRecord[],
  edits: ExportEdits,
  typeName: (id: number | null) => string
): ExportRow[] {
  return forms.map((form) => {
    const row: ExportRow = {
      form_id: String(form.id),
      form_type: typeName(form.form_type_id),
      status: form.review_status,
      created: form.created_at ? new Date(form.created_at).toLocaleDateString() : "—",
    };
    for (const [key, value] of Object.entries(edits[form.id] ?? editableFields(form))) {
      row[key] = value;
    }
    return row;
  });
}

function ExportEditTable({
  rows,
  fieldCols,
  allCols,
  colLabel,
  edits,
  saving,
  draggedColumn,
  onChange,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  rows: ExportRow[];
  fieldCols: string[];
  allCols: readonly string[];
  colLabel: (col: string) => string;
  edits: ExportEdits;
  saving: boolean;
  draggedColumn: string | null;
  onChange: (formId: number, key: string, value: string) => void;
  onDragStart: (col: string) => void;
  onDragOver: (event: DragEvent<HTMLTableCellElement>) => void;
  onDrop: (col: string) => void;
  onDragEnd: () => void;
}) {
  return (
    <div className="table-wrap table-wrap--dense">
      <table className="table--dense export-edit-table">
        <thead>
          <tr>
            {allCols.map((col) => {
              const editable = fieldCols.includes(col);
              return (
                <th
                  key={col}
                  className={[
                    editable ? "export-edit-draggable-col" : "",
                    draggedColumn === col ? "export-edit-draggable-col--dragging" : "",
                  ].filter(Boolean).join(" ")}
                  draggable={editable}
                  onDragStart={editable ? () => onDragStart(col) : undefined}
                  onDragOver={editable ? onDragOver : undefined}
                  onDrop={editable ? () => onDrop(col) : undefined}
                  onDragEnd={editable ? onDragEnd : undefined}
                  title={editable ? "Drag to reorder export columns" : undefined}
                >
                  {editable && <span className="export-edit-drag-handle">||</span>}
                  {colLabel(col)}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const formId = Number(row.form_id);
            return (
              <tr key={row.form_id}>
                {allCols.map((col) => (
                  <td key={col} className={fieldCols.includes(col) ? "td-field" : undefined}>
                    {col === "status" ? (
                      <span className={`status-badge status-${row.status}`}>{row.status}</span>
                    ) : fieldCols.includes(col) ? (
                      <input
                        className="export-edit-cell-input"
                        value={edits[formId]?.[col] ?? ""}
                        disabled={saving}
                        aria-label={`${colLabel(col)} ${row.form_id}`}
                        onChange={(e) => onChange(formId, col, e.target.value)}
                      />
                    ) : (
                      row[col] ?? "—"
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ExportPage() {
  const { t } = useI18n();
  const [formTypes, setFormTypes] = useState<FormType[]>([]);
  const [formTypeId, setFormTypeId] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [forms, setForms] = useState<FormRecord[]>([]);
  const [edits, setEdits] = useState<ExportEdits>({});
  const [orderedFieldCols, setOrderedFieldCols] = useState<string[]>([]);
  const [draggedColumn, setDraggedColumn] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [savingEdits, setSavingEdits] = useState(false);
  const [activeTab, setActiveTab] = useState<ExportTab>("preview");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const typeName = useCallback(
    (id: number | null) => {
      if (!id) return "—";
      return formTypes.find((ft) => ft.id === id)?.name ?? `#${id}`;
    },
    [formTypes]
  );

  const colLabel = useCallback(
    (col: string) => {
      if (col === "form_id") return t("export.col.id");
      if (col === "form_type") return t("export.col.formType");
      if (col === "status") return t("export.col.status");
      if (col === "created") return t("export.col.created");
      return col.replace(/_/g, " ");
    },
    [t]
  );

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "500" });
      if (formTypeId) params.set("form_type_id", formTypeId);
      if (reviewStatus) params.set("review_status", reviewStatus);
      const list = await apiFetch<FormRecord[]>(`/forms?${params}`);
      setForms(list);
    } catch (e) {
      setError(String(e));
      setForms([]);
    } finally {
      setLoading(false);
    }
  }, [formTypeId, reviewStatus]);

  useEffect(() => {
    apiFetch<FormType[]>("/form-types").then(setFormTypes).catch(() => {});
  }, []);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  useEffect(() => {
    const next: ExportEdits = {};
    for (const form of forms) {
      next[form.id] = editableFields(form);
    }
    setEdits(next);
  }, [forms]);

  const rows = useMemo(() => buildRows(forms, typeName), [forms, typeName]);
  const fieldCols = useMemo(() => fieldColumns(rows), [rows]);
  const effectiveFieldCols = orderedFieldCols.length > 0 ? orderedFieldCols : fieldCols;
  const allCols = useMemo(() => [...META_COLS, ...effectiveFieldCols], [effectiveFieldCols]);
  const editRows = useMemo(
    () => buildEditedRows(forms, edits, typeName),
    [forms, edits, typeName]
  );

  useEffect(() => {
    setOrderedFieldCols((current) => {
      const next = current.filter((col) => fieldCols.includes(col));
      for (const col of fieldCols) {
        if (!next.includes(col)) next.push(col);
      }
      return next;
    });
  }, [fieldCols]);

  const buildExportParams = () => {
    const params = new URLSearchParams();
    if (formTypeId) params.set("form_type_id", formTypeId);
    if (reviewStatus) params.set("review_status", reviewStatus);
    params.set("columns", allCols.join(","));
    return params;
  };

  const moveFieldColumn = (from: string, to: string) => {
    if (from === to) return;
    setOrderedFieldCols((current) => {
      const next = [...current];
      const fromIndex = next.indexOf(from);
      const toIndex = next.indexOf(to);
      if (fromIndex < 0 || toIndex < 0) return current;
      next.splice(fromIndex, 1);
      next.splice(toIndex, 0, from);
      return next;
    });
  };

  const saveEditedForms = async () => {
    const changed = forms.filter((form) => hasChangedEdits(form, edits[form.id]));
    if (changed.length === 0) return false;

    setSavingEdits(true);
    try {
      const saved = await Promise.all(
        changed.map((form) =>
          apiFetch<FormRecord>(`/forms/${form.id}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              corrected: edits[form.id] ?? {},
              status: form.review_status,
            }),
          })
        )
      );
      setForms((current) =>
        current.map((form) => saved.find((item) => item.id === form.id) ?? form)
      );
      return true;
    } finally {
      setSavingEdits(false);
    }
  };

  const runExport = async () => {
    setExporting(true);
    setError("");
    setSuccess("");
    try {
      await saveEditedForms();
      const savedPath = await saveExport(format, buildExportParams(), {
        title: t("export.saveDialogTitle"),
      });
      if (savedPath === null) {
        return;
      }
      setSuccess(t("export.savedTo", { path: savedPath }));
    } catch (e) {
      setError(String(e));
    } finally {
      setExporting(false);
    }
  };

  const formatLabel = (f: ExportFormat) => {
    if (f === "csv") return t("export.csv");
    if (f === "xlsx") return t("export.excel");
    return t("export.json");
  };

  const changedCount = forms.filter((form) => hasChangedEdits(form, edits[form.id])).length;

  return (
    <div className="page page--pro">
      <PageHeader title={t("page.export")} />

      <div className="card card--compact">
        <div className="filter-row">
          <div className="filter-field">
            <label>{t("common.formType")}</label>
            <select value={formTypeId} onChange={(e) => setFormTypeId(e.target.value)}>
              <option value="">{t("common.allTypes")}</option>
              {formTypes.map((ft) => (
                <option key={ft.id} value={ft.id}>
                  {ft.name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>{t("common.status")}</label>
            <select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}>
              <option value="">{t("common.all")}</option>
              <option value="approved">{t("common.approved")}</option>
              <option value="pending">{t("common.pending")}</option>
              <option value="rejected">{t("common.rejected")}</option>
            </select>
          </div>
          <button type="button" className="btn btn-sm btn-secondary" onClick={loadPreview} disabled={loading}>
            {loading ? t("common.loading") : t("common.refresh")}
          </button>
        </div>

        <div className="export-actions">
          <div className="export-format">
            <span className="export-format-label">{t("export.format")}</span>
            <div className="segmented" role="group" aria-label={t("export.format")}>
              {FORMATS.map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`segmented-btn${format === f ? " segmented-btn--active" : ""}`}
                  aria-pressed={format === f}
                  onClick={() => setFormat(f)}
                >
                  {formatLabel(f)}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            className="btn"
            onClick={runExport}
            disabled={exporting}
          >
            {exporting ? t("export.exporting") : t("export.export")}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      <div className="card card--compact">
        <div className="card-header card-header--tight tab-window-header">
          <div className="tab-window-tabs" role="tablist" aria-label={t("page.export")}>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "preview"}
              className={`tab-window-tab${activeTab === "preview" ? " tab-window-tab--active" : ""}`}
              onClick={() => setActiveTab("preview")}
            >
              {t("export.preview")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "result"}
              className={`tab-window-tab${activeTab === "result" ? " tab-window-tab--active" : ""}`}
              onClick={() => setActiveTab("result")}
            >
              {t("preview.result")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "edit"}
              className={`tab-window-tab${activeTab === "edit" ? " tab-window-tab--active" : ""}`}
              onClick={() => setActiveTab("edit")}
            >
              {t("export.edit")}
            </button>
          </div>
          <div className="tab-window-actions">
            {activeTab === "edit" && (
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={savingEdits || changedCount === 0}
                onClick={() => void saveEditedForms()}
              >
                {savingEdits ? t("export.savingEdits") : t("export.saveEdits")}
              </button>
            )}
            <span className="muted tab-window-count">
              {t("common.rows", { count: rows.length })}
            </span>
          </div>
        </div>

        {loading && rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.noMatch")}</p>
        ) : activeTab === "edit" ? (
          <ExportEditTable
            rows={editRows}
            fieldCols={effectiveFieldCols}
            allCols={allCols}
            colLabel={colLabel}
            edits={edits}
            saving={savingEdits || exporting}
            draggedColumn={draggedColumn}
            onChange={(formId, key, value) =>
              setEdits((current) => ({
                ...current,
                [formId]: {
                  ...(current[formId] ?? {}),
                  [key]: value,
                },
              }))
            }
            onDragStart={setDraggedColumn}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(targetCol) => {
              if (draggedColumn) moveFieldColumn(draggedColumn, targetCol);
              setDraggedColumn(null);
            }}
            onDragEnd={() => setDraggedColumn(null)}
          />
        ) : activeTab === "result" ? (
          <ExportResultList forms={forms} typeName={typeName} />
        ) : (
          <div className="table-wrap table-wrap--dense">
            <table className="table--dense">
              <thead>
                <tr>
                  {allCols.map((col) => (
                    <th key={col}>{colLabel(col)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.form_id}>
                    {allCols.map((col) => (
                      <td key={col} className={fieldCols.includes(col) ? "td-field" : undefined}>
                        {col === "status" ? (
                          <span className={`status-badge status-${row.status}`}>{row.status}</span>
                        ) : (
                          row[col] ?? "—"
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
