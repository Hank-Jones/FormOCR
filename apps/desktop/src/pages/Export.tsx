import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch, type FormRecord, type FormType } from "../api/client";
import { useI18n } from "../i18n/context";
import { saveExport, type ExportFormat } from "../utils/exportDownload";
import { displayFields } from "../utils/formFields";

const META_COLS = ["form_id", "form_type", "status", "created"] as const;
const EXPORT_STATUSES = [
  "approved",
  "pending",
  "rejected",
  "processing",
  "needs_type",
  "no_template",
  "cancelled",
] as const;

type ExportRow = Record<string, string>;

function buildRows(forms: FormRecord[], typeName: (id: number | null) => string): ExportRow[] {
  return forms.map((f) => {
    const fields = displayFields(f);
    const row: ExportRow = {
      form_id: String(f.id),
      form_type: typeName(f.form_type_id),
      status: f.review_status,
      created: f.created_at || "",
    };
    for (const [k, v] of Object.entries(fields)) {
      row[k] = v || "";
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

function apiErrorMessage(e: unknown, t: (key: string, params?: Record<string, string | number>) => string): string {
  const detail = String(e).replace(/^Error:\s*/, "");
  if (detail.includes("No data to export")) return t("export.errorNoData");
  if (detail.includes("Unsupported review status")) return t("export.errorUnsupportedStatus");
  return detail;
}

export default function ExportPage() {
  const { t } = useI18n();
  const [formTypes, setFormTypes] = useState<FormType[]>([]);
  const [formTypeId, setFormTypeId] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [forms, setForms] = useState<FormRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const typeName = useCallback(
    (id: number | null) => {
      if (!id) return "";
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
      setError(apiErrorMessage(e, t));
      setForms([]);
    } finally {
      setLoading(false);
    }
  }, [formTypeId, reviewStatus, t]);

  useEffect(() => {
    apiFetch<FormType[]>("/form-types").then(setFormTypes).catch(() => {});
  }, []);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  const rows = useMemo(() => buildRows(forms, typeName), [forms, typeName]);
  const fieldCols = useMemo(() => fieldColumns(rows), [rows]);
  const allCols = useMemo(() => [...META_COLS, ...fieldCols], [fieldCols]);

  const buildExportParams = () => {
    const params = new URLSearchParams();
    if (formTypeId) params.set("form_type_id", formTypeId);
    if (reviewStatus) params.set("review_status", reviewStatus);
    return params;
  };

  const runExport = async () => {
    if (exporting) return;
    setExporting(true);
    setError("");
    setSuccess("");
    try {
      const savedPath = await saveExport(format, buildExportParams(), {
        title: t("export.saveDialogTitle"),
      });
      if (savedPath === null) {
        return;
      }
      setSuccess(t("export.savedTo", { path: savedPath }));
    } catch (e) {
      setError(apiErrorMessage(e, t));
    } finally {
      setExporting(false);
    }
  };

  const formatLabel = (f: ExportFormat) => {
    if (f === "csv") return t("export.csv");
    if (f === "xlsx") return t("export.excel");
    return t("export.json");
  };

  const statusLabel = (status: string) => {
    if (status === "approved") return t("common.approved");
    if (status === "pending") return t("common.pending");
    if (status === "rejected") return t("common.rejected");
    if (status === "processing") return t("export.status.processing");
    if (status === "needs_type") return t("export.status.needsType");
    if (status === "no_template") return t("export.status.noTemplate");
    if (status === "cancelled") return t("export.status.cancelled");
    return status;
  };

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
              {EXPORT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {statusLabel(status)}
                </option>
              ))}
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
        <div className="card-header card-header--tight">
          <h3 className="card-title">
            {t("export.preview")}
            <span className="muted" style={{ fontWeight: 400, marginLeft: "0.5rem" }}>
              {t("common.rows", { count: rows.length })}
            </span>
          </h3>
        </div>
        <p className="muted" style={{ marginTop: "-0.25rem", fontSize: "0.85rem" }}>
          {t("export.previewLimit")}
        </p>

        {loading && rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.noMatch")}</p>
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
                          <span className={`status-badge status-${row.status}`}>
                            {statusLabel(row.status)}
                          </span>
                        ) : (
                          row[col] ?? ""
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
