import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import PageHeader from "../components/PageHeader";
import { IconTrash } from "../components/icons";
import ReviewImageViewer from "../components/ReviewImageViewer";
import ResizableSplit from "../components/ResizableSplit";
import {
  apiFetch,
  apiImageBlobUrl,
  type FormFieldMeta,
  type FormRecord,
  type FormType,
} from "../api/client";
import { useI18n } from "../i18n/useI18n";
import { saveExportRows, type ExportFormat } from "../utils/exportDownload";
import { displayFields } from "../utils/formFields";

const META_COLS = ["form_id", "form_type", "status", "created"] as const;
const EDIT_META_COLS = ["form_id"] as const;
const DEFAULT_COLUMN_WIDTH = 160;
const MIN_COLUMN_WIDTH = 30;
const MAX_COLUMN_WIDTH = 420;
const DEFAULT_PREVIEW_TABLE_HEIGHT = 620;
const MIN_PREVIEW_TABLE_HEIGHT = 240;
const MAX_PREVIEW_TABLE_HEIGHT = 900;
const TWO_COLUMN_MIN_FIELDS = 6;
const EXPORT_COLUMN_ORDER_STORAGE_KEY = "formocr.export.columnOrder";
const EXPORT_COLUMN_WIDTHS_STORAGE_KEY = "formocr.export.columnWidths";
const EXPORT_PREVIEW_TABLE_HEIGHT_STORAGE_KEY = "formocr.export.previewTableHeight";
const EXPORT_RESULT_VIEW_MODE_STORAGE_KEY = "formocr.export.resultViewMode";

type ExportRow = Record<string, string>;
type ExportTab = "preview" | "result" | "edit";
type ExportEdits = Record<number, Record<string, string>>;
type SortState = { col: string; direction: "asc" | "desc" } | null;
type ExportResultViewMode = "sections" | "review";

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function apiErrorMessage(
  e: unknown,
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  const raw = String(e).replace(/^Error:\s*/, "");
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Keep raw text for non-JSON responses.
  }
  return raw || t("common.error");
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function loadExportColumnOrder(): string[] {
  try {
    const value = window.localStorage.getItem(EXPORT_COLUMN_ORDER_STORAGE_KEY);
    const parsed: unknown = value ? JSON.parse(value) : [];
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string")
      ? parsed
      : [];
  } catch {
    return [];
  }
}

function loadExportColumnWidths(): Record<string, number> {
  try {
    const value = window.localStorage.getItem(EXPORT_COLUMN_WIDTHS_STORAGE_KEY);
    const parsed: unknown = value ? JSON.parse(value) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const widths: Record<string, number> = {};
    for (const [col, width] of Object.entries(parsed)) {
      if (typeof width === "number" && Number.isFinite(width)) {
        widths[col] = Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, width));
      }
    }
    return widths;
  } catch {
    return {};
  }
}

function loadPreviewTableHeight(): number {
  try {
    const value = window.localStorage.getItem(EXPORT_PREVIEW_TABLE_HEIGHT_STORAGE_KEY);
    const height = value ? Number(value) : DEFAULT_PREVIEW_TABLE_HEIGHT;
    return Number.isFinite(height)
      ? clamp(height, MIN_PREVIEW_TABLE_HEIGHT, MAX_PREVIEW_TABLE_HEIGHT)
      : DEFAULT_PREVIEW_TABLE_HEIGHT;
  } catch {
    return DEFAULT_PREVIEW_TABLE_HEIGHT;
  }
}

function loadExportResultViewMode(): ExportResultViewMode {
  try {
    const value = window.localStorage.getItem(EXPORT_RESULT_VIEW_MODE_STORAGE_KEY);
    return value === "review" ? "review" : "sections";
  } catch {
    return "sections";
  }
}

function confClass(c: number | undefined): string {
  if (c === undefined) return "";
  if (c >= 0.9) return "conf-high";
  if (c >= 0.7) return "conf-mid";
  return "conf-low";
}

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

function buildResultRows(
  forms: FormRecord[],
  edits: ExportEdits,
  typeName: (id: number | null) => string
): ExportRow[] {
  return forms.map((form) => ({
    form_id: String(form.id),
    form_type: typeName(form.form_type_id),
    status: form.review_status,
    created: form.created_at || "",
    ...(edits[form.id] ?? editableFields(form)),
  }));
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
  rows,
  fieldCols,
  allCols,
  columnWidths,
  sort,
  disabled,
  draggedColumn,
  selectedFormId,
  colLabel,
  deleteLabel,
  onDelete,
  onSort,
  onResizeStart,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onSelect,
}: {
  rows: ExportRow[];
  fieldCols: string[];
  allCols: readonly string[];
  columnWidths: Record<string, number>;
  sort: SortState;
  disabled: boolean;
  draggedColumn: string | null;
  selectedFormId: number | null;
  colLabel: (col: string) => string;
  deleteLabel: string;
  onDelete: (formId: number) => void;
  onSort: (col: string) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>, col: string) => void;
  onDragStart: (col: string) => void;
  onDragOver: (event: DragEvent<HTMLTableCellElement>) => void;
  onDrop: (col: string) => void;
  onDragEnd: () => void;
  onSelect: (formId: number) => void;
}) {
  return (
    <div className="table-wrap table-wrap--dense export-table-wrap export-result-table-wrap">
      <table className="table--dense table--resizable export-result-table">
        <colgroup>
          <col className="export-edit-actions-colgroup" />
          {allCols.map((col) => (
            <col key={col} style={{ width: columnWidths[col] ?? DEFAULT_COLUMN_WIDTH }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th className="export-edit-actions-col" aria-label={deleteLabel} />
            {allCols.map((col) => (
              <ExportColumnHeader
                key={col}
                col={col}
                width={columnWidths[col] ?? DEFAULT_COLUMN_WIDTH}
                colLabel={colLabel}
                sort={sort}
                draggedColumn={draggedColumn}
                onSort={onSort}
                onResizeStart={onResizeStart}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onDragEnd={onDragEnd}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const formId = Number(row.form_id);
            const selected = selectedFormId === formId;
            return (
              <tr
                key={row.form_id}
                className={selected ? "export-result-row--active" : undefined}
                tabIndex={0}
                onClick={() => onSelect(formId)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(formId);
                  }
                }}
              >
                <td className="export-edit-actions-cell">
                  <button
                    type="button"
                    className="export-delete-icon-btn"
                    disabled={disabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(formId);
                    }}
                    aria-label={`${deleteLabel} ${row.form_id}`}
                    title={deleteLabel}
                  >
                    <IconTrash className="export-delete-icon" />
                  </button>
                </td>
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExportResultReview({
  forms,
  selectedFormId,
  edits,
  saving,
  deletingFormId,
  changedCount,
  colLabel,
  deleteLabel,
  onSelect,
  onChange,
  onDelete,
  onSave,
}: {
  forms: FormRecord[];
  selectedFormId: number | null;
  edits: ExportEdits;
  saving: boolean;
  deletingFormId: number | null;
  changedCount: number;
  colLabel: (col: string) => string;
  deleteLabel: string;
  onSelect: (formId: number) => void;
  onChange: (formId: number, key: string, value: string) => void;
  onDelete: (formId: number) => void;
  onSave: () => void | Promise<unknown>;
}) {
  const { t } = useI18n();
  const selectedForm = forms.find((form) => form.id === selectedFormId) ?? forms[0] ?? null;
  const selectedId = selectedForm?.id ?? null;
  const [imgSrc, setImgSrc] = useState("");
  const [fieldMeta, setFieldMeta] = useState<Record<string, FormFieldMeta>>({});
  const [selectedFieldKey, setSelectedFieldKey] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedForm) {
      setImgSrc("");
      setFieldMeta({});
      setSelectedFieldKey(null);
      return;
    }

    let stopped = false;
    let blobUrl: string | null = null;
    setImgSrc("");
    setFieldMeta({});
    setSelectedFieldKey(null);

    apiFetch<FormFieldMeta[]>(`/forms/${selectedForm.id}/fields`)
      .then((meta) => {
        if (stopped) return;
        const map: Record<string, FormFieldMeta> = {};
        for (const field of meta) map[field.key] = field;
        setFieldMeta(map);
        setSelectedFieldKey(meta.find((field) => field.bbox_norm)?.key ?? null);
      })
      .catch(() => {
        if (!stopped) {
          setFieldMeta({});
          setSelectedFieldKey(null);
        }
      });

    apiImageBlobUrl(`/forms/${selectedForm.id}/image?processed=false`)
      .then((url) => {
        if (stopped) {
          URL.revokeObjectURL(url);
          return;
        }
        blobUrl = url;
        setImgSrc(url);
      })
      .catch(() => {
        if (!stopped) setImgSrc("");
      });

    return () => {
      stopped = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [selectedForm]);

  if (!selectedForm || selectedId === null) {
    return <p className="empty-state empty-state--sm">{t("common.noMatch")}</p>;
  }

  const fields = edits[selectedId] ?? editableFields(selectedForm);
  const keys = Object.keys(fields).sort();
  const multiColumn = keys.length >= TWO_COLUMN_MIN_FIELDS;

  return (
    <div className="export-result-review">
      <div className="export-result-review-picker-row">
        <div className="export-result-review-picker">
          <label htmlFor="export-result-review-form">{t("export.selectedForm")}</label>
          <select
            id="export-result-review-form"
            value={selectedId}
            onChange={(event) => onSelect(Number(event.target.value))}
          >
            {forms.map((form) => (
              <option key={form.id} value={form.id}>
                {t("process.form", { id: form.id })}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          disabled={saving || deletingFormId === selectedId}
          onClick={() => onDelete(selectedId)}
        >
          {deletingFormId === selectedId ? t("common.loading") : deleteLabel}
        </button>
      </div>
      <ResizableSplit
        className="export-review-split"
        storageKey="formocr-export-review-split"
        defaultLeftPct={55}
        minLeftPct={32}
        maxLeftPct={82}
        left={
          <section className="review-pane review-pane--image" aria-label={t("review.imagePane")}>
            <ReviewImageViewer
              src={imgSrc}
              boxes={Object.values(fieldMeta)
                .filter((field): field is FormFieldMeta & {
                  bbox_norm: [number, number, number, number];
                } => Array.isArray(field.bbox_norm) && field.bbox_norm.length === 4)
                .map((field) => ({
                  key: field.key,
                  bbox_norm: field.bbox_norm,
                  active: field.key === selectedFieldKey,
                }))}
              onSelectBox={setSelectedFieldKey}
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
                  const multiline = lines >= 2 || (fields[key] ?? "").includes("\n");
                  return (
                    <div
                      key={key}
                      className={`form-group review-field-item${
                        selectedFieldKey === key ? " review-field-item--active" : ""
                      }`}
                      onClick={() => setSelectedFieldKey(key)}
                    >
                      <label htmlFor={`export-review-field-${selectedId}-${key}`}>
                        {colLabel(key)}
                        {multiline && lines >= 2
                          ? ` (${t("review.multiline", { count: lines })})`
                          : ""}
                      </label>
                      {multiline ? (
                        <textarea
                          id={`export-review-field-${selectedId}-${key}`}
                          className={confClass(selectedForm.confidence?.[key])}
                          rows={Math.max(2, lines || Math.min(6, fields[key].split("\n").length))}
                          value={fields[key] ?? ""}
                          disabled={saving}
                          onChange={(event) => onChange(selectedId, key, event.target.value)}
                        />
                      ) : (
                        <input
                          id={`export-review-field-${selectedId}-${key}`}
                          className={confClass(selectedForm.confidence?.[key])}
                          value={fields[key] ?? ""}
                          disabled={saving}
                          onChange={(event) => onChange(selectedId, key, event.target.value)}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="review-actions toolbar export-result-review-actions">
              <button
                type="button"
                className="btn"
                disabled={saving || changedCount === 0}
                onClick={() => void onSave()}
              >
                {saving ? t("export.savingEdits") : t("export.saveEdits")}
              </button>
              {changedCount > 0 && (
                <span className="muted">{t("common.rows", { count: changedCount })}</span>
              )}
            </div>
          </section>
        }
      />
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
  edits: ExportEdits
): ExportRow[] {
  return forms.map((form) => {
    const row: ExportRow = {
      form_id: String(form.id),
    };
    for (const [key, value] of Object.entries(edits[form.id] ?? editableFields(form))) {
      row[key] = value;
    }
    return row;
  });
}

function compareValues(a: string | undefined, b: string | undefined): number {
  const av = a ?? "";
  const bv = b ?? "";
  const an = Number(av);
  const bn = Number(bv);
  if (av.trim() !== "" && bv.trim() !== "" && Number.isFinite(an) && Number.isFinite(bn)) {
    return an - bn;
  }
  return av.localeCompare(bv, undefined, { numeric: true, sensitivity: "base" });
}

function sortRows(rows: ExportRow[], sort: SortState): ExportRow[] {
  if (!sort) return rows;
  const dir = sort.direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => compareValues(a[sort.col], b[sort.col]) * dir);
}

function ExportColumnHeader({
  col,
  width,
  colLabel,
  sort,
  draggedColumn,
  onSort,
  onResizeStart,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  col: string;
  width: number;
  colLabel: (col: string) => string;
  sort: SortState;
  draggedColumn: string | null;
  onSort: (col: string) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>, col: string) => void;
  onDragStart: (col: string) => void;
  onDragOver: (event: DragEvent<HTMLTableCellElement>) => void;
  onDrop: (col: string) => void;
  onDragEnd: () => void;
}) {
  const activeSort = sort?.col === col ? sort.direction : null;
  return (
    <th
      className={[
        "export-table-th",
        draggedColumn === col ? "export-table-th--dragging" : "",
      ].filter(Boolean).join(" ")}
      style={{ width }}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", col);
        onDragStart(col);
      }}
      onDragOver={onDragOver}
      onDrop={() => onDrop(col)}
      onDragEnd={onDragEnd}
      title="Drag to move column"
    >
      <div className="export-table-th-content">
        <button
          type="button"
          className="export-table-sort-btn"
          onClick={() => onSort(col)}
          title="Sort by column"
        >
          <span>{colLabel(col)}</span>
          {activeSort && (
            <span className="export-table-sort-mark">
              {activeSort === "asc" ? "A-Z" : "Z-A"}
            </span>
          )}
        </button>
        <button
          type="button"
          className="export-table-resize-handle"
          draggable={false}
          onPointerDown={(event) => onResizeStart(event, col)}
          aria-label={`Resize ${colLabel(col)} column`}
          title="Drag to resize"
        />
      </div>
    </th>
  );
}

function ExportEditTable({
  rows,
  fieldCols,
  allCols,
  colLabel,
  columnWidths,
  sort,
  disabled,
  draggedColumn,
  deleteLabel,
  onDelete,
  onSort,
  onResizeStart,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  rows: ExportRow[];
  fieldCols: string[];
  allCols: readonly string[];
  colLabel: (col: string) => string;
  columnWidths: Record<string, number>;
  sort: SortState;
  disabled: boolean;
  draggedColumn: string | null;
  deleteLabel: string;
  onDelete: (formId: number) => void;
  onSort: (col: string) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>, col: string) => void;
  onDragStart: (col: string) => void;
  onDragOver: (event: DragEvent<HTMLTableCellElement>) => void;
  onDrop: (col: string) => void;
  onDragEnd: () => void;
}) {
  return (
    <div className="table-wrap table-wrap--dense export-table-wrap export-edit-table-wrap">
      <table className="table--dense table--resizable export-edit-table">
        <colgroup>
          <col className="export-edit-actions-colgroup" />
          {allCols.map((col) => (
            <col key={col} style={{ width: columnWidths[col] ?? DEFAULT_COLUMN_WIDTH }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th className="export-edit-actions-col" aria-label={deleteLabel} />
            {allCols.map((col) => (
              <ExportColumnHeader
                key={col}
                col={col}
                width={columnWidths[col] ?? DEFAULT_COLUMN_WIDTH}
                colLabel={colLabel}
                sort={sort}
                draggedColumn={draggedColumn}
                onSort={onSort}
                onResizeStart={onResizeStart}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onDragEnd={onDragEnd}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const formId = Number(row.form_id);
            return (
              <tr key={row.form_id}>
                <td className="export-edit-actions-cell">
                  <button
                    type="button"
                    className="export-delete-icon-btn"
                    disabled={disabled}
                    onClick={() => onDelete(formId)}
                    aria-label={`${deleteLabel} ${row.form_id}`}
                    title={deleteLabel}
                  >
                    <IconTrash className="export-delete-icon" />
                  </button>
                </td>
                {allCols.map((col) => (
                  <td key={col} className={fieldCols.includes(col) ? "td-field" : undefined}>
                    {row[col] ?? "—"}
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
  const [activeTab, setActiveTab] = useState<ExportTab>("preview");
  const [forms, setForms] = useState<FormRecord[]>([]);
  const [edits, setEdits] = useState<ExportEdits>({});
  const [deletedFormIds, setDeletedFormIds] = useState<Set<number>>(() => new Set());
  const [orderedCols, setOrderedCols] = useState<string[]>(loadExportColumnOrder);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(
    loadExportColumnWidths
  );
  const [previewTableHeight, setPreviewTableHeight] = useState(loadPreviewTableHeight);
  const [resultViewMode, setResultViewMode] =
    useState<ExportResultViewMode>(loadExportResultViewMode);
  const [selectedResultFormId, setSelectedResultFormId] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState>(null);
  const [draggedColumn, setDraggedColumn] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [savingEdits, setSavingEdits] = useState(false);
  const [deletingFormId, setDeletingFormId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const resizingColumnRef = useRef<{
    col: string;
    startX: number;
    startWidth: number;
  } | null>(null);

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
      setDeletedFormIds(new Set());
    } catch (e) {
      setError(apiErrorMessage(e, t));
      setForms([]);
      setDeletedFormIds(new Set());
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

  useEffect(() => {
    const next: ExportEdits = {};
    for (const form of forms) {
      next[form.id] = editableFields(form);
    }
    setEdits(next);
  }, [forms]);

  const exportForms = useMemo(
    () => forms.filter((form) => !deletedFormIds.has(form.id)),
    [forms, deletedFormIds]
  );
  const rows = useMemo(() => buildRows(exportForms, typeName), [exportForms, typeName]);
  const resultRows = useMemo(
    () => buildResultRows(exportForms, edits, typeName),
    [exportForms, edits, typeName]
  );
  const fieldCols = useMemo(() => fieldColumns(rows), [rows]);
  const baseCols = useMemo(() => [...META_COLS, ...fieldCols], [fieldCols]);
  const editBaseCols = useMemo(() => [...EDIT_META_COLS, ...fieldCols], [fieldCols]);
  const effectiveOrderedCols = orderedCols.length > 0 ? orderedCols : baseCols;
  const previewCols = useMemo(
    () => effectiveOrderedCols.filter((col) => baseCols.includes(col)),
    [baseCols, effectiveOrderedCols]
  );
  const editCols = useMemo(
    () => effectiveOrderedCols.filter((col) => editBaseCols.includes(col)),
    [editBaseCols, effectiveOrderedCols]
  );
  const editRows = useMemo(
    () => buildEditedRows(exportForms, edits),
    [exportForms, edits]
  );
  const visiblePreviewSort = sort && previewCols.includes(sort.col) ? sort : null;
  const visibleEditSort = sort && editCols.includes(sort.col) ? sort : null;
  const sortedRows = useMemo(
    () => sortRows(rows, visiblePreviewSort),
    [rows, visiblePreviewSort]
  );
  const sortedResultRows = useMemo(
    () => sortRows(resultRows, visiblePreviewSort),
    [resultRows, visiblePreviewSort]
  );
  const sortedEditRows = useMemo(
    () => sortRows(editRows, visibleEditSort),
    [editRows, visibleEditSort]
  );

  useEffect(() => {
    setSelectedResultFormId((current) => {
      if (current && exportForms.some((form) => form.id === current)) return current;
      return exportForms[0]?.id ?? null;
    });
  }, [exportForms]);

  useEffect(() => {
    setOrderedCols((current) => {
      const next = current.filter((col) => baseCols.includes(col));
      for (const col of baseCols) {
        if (!next.includes(col)) next.push(col);
      }
      return next;
    });
  }, [baseCols]);

  useEffect(() => {
    setColumnWidths((current) => {
      const next: Record<string, number> = {};
      for (const col of baseCols) {
        const width = current[col];
        if (typeof width === "number" && Number.isFinite(width)) {
          next[col] = Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, width));
        }
      }
      return next;
    });
  }, [baseCols]);

  useEffect(() => {
    window.localStorage.setItem(EXPORT_COLUMN_ORDER_STORAGE_KEY, JSON.stringify(orderedCols));
  }, [orderedCols]);

  useEffect(() => {
    window.localStorage.setItem(EXPORT_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);

  useEffect(() => {
    window.localStorage.setItem(
      EXPORT_PREVIEW_TABLE_HEIGHT_STORAGE_KEY,
      String(previewTableHeight)
    );
  }, [previewTableHeight]);

  useEffect(() => {
    window.localStorage.setItem(EXPORT_RESULT_VIEW_MODE_STORAGE_KEY, resultViewMode);
  }, [resultViewMode]);

  const moveColumn = (from: string, to: string) => {
    if (from === to) return;
    setOrderedCols((current) => {
      const next = [...current];
      const fromIndex = next.indexOf(from);
      const toIndex = next.indexOf(to);
      if (fromIndex < 0 || toIndex < 0) return current;
      next.splice(fromIndex, 1);
      next.splice(toIndex, 0, from);
      return next;
    });
  };

  const toggleSort = (col: string) => {
    setSort((current) => {
      if (current?.col !== col) return { col, direction: "asc" };
      if (current.direction === "asc") return { col, direction: "desc" };
      return null;
    });
  };

  const startColumnResize = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>, col: string) => {
      event.preventDefault();
      event.stopPropagation();
      resizingColumnRef.current = {
        col,
        startX: event.clientX,
        startWidth: columnWidths[col] ?? DEFAULT_COLUMN_WIDTH,
      };
      const handlePointerMove = (moveEvent: PointerEvent) => {
        const current = resizingColumnRef.current;
        if (!current) return;
        const nextWidth = Math.min(
          MAX_COLUMN_WIDTH,
          Math.max(MIN_COLUMN_WIDTH, current.startWidth + moveEvent.clientX - current.startX)
        );
        setColumnWidths((widths) => ({
          ...widths,
          [current.col]: nextWidth,
        }));
      };
      const handlePointerUp = () => {
        resizingColumnRef.current = null;
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    },
    [columnWidths]
  );

  const saveEditedForms = async () => {
    const changed = exportForms.filter((form) => hasChangedEdits(form, edits[form.id]));
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

  const deleteFormResult = async (formId: number) => {
    if (deletingFormId !== null || savingEdits || exporting) return;
    if (!window.confirm(t("export.deleteConfirm", { id: formId }))) return;

    setDeletingFormId(formId);
    setError("");
    setSuccess("");
    try {
      await apiFetch(`/forms/${formId}`, { method: "DELETE" }, { retries: 1 });
      setForms((current) => current.filter((form) => form.id !== formId));
      setEdits((current) => {
        const next = { ...current };
        delete next[formId];
        return next;
      });
      setDeletedFormIds((current) => {
        const next = new Set(current);
        next.delete(formId);
        return next;
      });
      setSuccess(t("export.deletedResult", { id: formId }));
    } catch (e) {
      setError(apiErrorMessage(e, t));
    } finally {
      setDeletingFormId(null);
    }
  };

  const runExport = async () => {
    if (exporting) return;
    setExporting(true);
    setError("");
    setSuccess("");
    try {
      const savedPath = await saveExportRows(format, editCols, sortedEditRows, {
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

  const changedCount = exportForms.filter((form) => hasChangedEdits(form, edits[form.id])).length;
  const updateEdit = (formId: number, key: string, value: string) =>
    setEdits((current) => ({
      ...current,
      [formId]: {
        ...(current[formId] ?? {}),
        [key]: value,
      },
    }));

  return (
    <div className="page page--pro page--export">
      <PageHeader title={t("page.export")} />

      <div className="card card--compact export-toolbar-card">
        <div className="export-toolbar">
          <div className="export-toolbar-fields">
            <div className="filter-field export-filter-field">
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
            <div className="filter-field export-filter-field">
              <label>{t("common.status")}</label>
              <select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}>
                <option value="">{t("common.all")}</option>
                <option value="approved">{t("common.approved")}</option>
                <option value="pending">{t("common.pending")}</option>
                <option value="rejected">{t("common.rejected")}</option>
              </select>
            </div>
          </div>

          <div className="export-toolbar-actions">
            <button
              type="button"
              className="btn btn-sm btn-secondary export-refresh-btn"
              onClick={loadPreview}
              disabled={loading}
            >
              {loading ? t("common.loading") : t("common.refresh")}
            </button>
            <div className="export-format">
              <span className="export-format-label">{t("export.format")}</span>
              <div
                className="segmented export-format-segmented"
                role="group"
                aria-label={t("export.format")}
              >
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
              className="btn export-primary-action"
              onClick={runExport}
              disabled={exporting}
            >
              {exporting ? t("export.exporting") : t("export.export")}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      <div className="card card--compact export-data-card">
        <div className="card-header card-header--tight tab-window-header export-tab-header">
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
            {activeTab === "preview" && (
              <label className="export-height-control">
                <span>{t("export.previewHeight")}</span>
                <input
                  type="range"
                  min={MIN_PREVIEW_TABLE_HEIGHT}
                  max={MAX_PREVIEW_TABLE_HEIGHT}
                  step={20}
                  value={previewTableHeight}
                  onChange={(event) => setPreviewTableHeight(Number(event.target.value))}
                />
                <output>{previewTableHeight}px</output>
              </label>
            )}
            {activeTab === "result" && (
              <div
                className="segmented export-view-segmented"
                role="group"
                aria-label={t("export.resultViewMode")}
              >
                <button
                  type="button"
                  className={`segmented-btn${
                    resultViewMode === "sections" ? " segmented-btn--active" : ""
                  }`}
                  aria-pressed={resultViewMode === "sections"}
                  onClick={() => setResultViewMode("sections")}
                >
                  {t("export.view.sections")}
                </button>
                <button
                  type="button"
                  className={`segmented-btn${
                    resultViewMode === "review" ? " segmented-btn--active" : ""
                  }`}
                  aria-pressed={resultViewMode === "review"}
                  onClick={() => setResultViewMode("review")}
                >
                  {t("export.view.review")}
                </button>
              </div>
            )}
            <span className="muted tab-window-count">
              {t("common.rows", { count: rows.length })}
            </span>
          </div>
        </div>
        <p className="muted" style={{ marginLeft: "0.5rem", marginTop: "0.25rem", fontSize: "0.85rem" }}>
          {t("export.previewLimit")}
        </p>

        {loading && rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="empty-state empty-state--sm">{t("common.noMatch")}</p>
        ) : activeTab === "edit" ? (
          <ExportEditTable
            rows={sortedEditRows}
            fieldCols={fieldCols}
            allCols={editCols}
            colLabel={colLabel}
            columnWidths={columnWidths}
            sort={visibleEditSort}
            disabled={savingEdits || exporting || deletingFormId !== null}
            draggedColumn={draggedColumn}
            deleteLabel={t("common.delete")}
            onSort={toggleSort}
            onResizeStart={startColumnResize}
            onDelete={(formId) => void deleteFormResult(formId)}
            onDragStart={setDraggedColumn}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(targetCol) => {
              if (draggedColumn) moveColumn(draggedColumn, targetCol);
              setDraggedColumn(null);
            }}
            onDragEnd={() => setDraggedColumn(null)}
          />
        ) : activeTab === "result" ? (
          <div className="export-result-workspace">
            {resultViewMode === "review" ? (
              <ExportResultReview
                forms={exportForms}
                selectedFormId={selectedResultFormId}
                edits={edits}
                saving={savingEdits || exporting || deletingFormId !== null}
                deletingFormId={deletingFormId}
                changedCount={changedCount}
                colLabel={colLabel}
                deleteLabel={t("common.delete")}
                onSelect={setSelectedResultFormId}
                onChange={updateEdit}
                onDelete={(formId) => void deleteFormResult(formId)}
                onSave={saveEditedForms}
              />
            ) : (
              <ExportResultList
                rows={sortedResultRows}
                fieldCols={fieldCols}
                allCols={previewCols}
                columnWidths={columnWidths}
                sort={visiblePreviewSort}
                disabled={savingEdits || exporting || deletingFormId !== null}
                draggedColumn={draggedColumn}
                selectedFormId={selectedResultFormId}
                colLabel={colLabel}
                deleteLabel={t("common.delete")}
                onDelete={(formId) => void deleteFormResult(formId)}
                onSort={toggleSort}
                onResizeStart={startColumnResize}
                onDragStart={setDraggedColumn}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(targetCol) => {
                  if (draggedColumn) moveColumn(draggedColumn, targetCol);
                  setDraggedColumn(null);
                }}
                onDragEnd={() => setDraggedColumn(null)}
                onSelect={(formId) => {
                  setSelectedResultFormId(formId);
                  setResultViewMode("review");
                }}
              />
            )}
          </div>
        ) : (
          <div
            className="table-wrap table-wrap--dense export-table-wrap"
            style={{ maxHeight: previewTableHeight }}
          >
            <table className="table--dense table--resizable">
              <colgroup>
                {previewCols.map((col) => (
                  <col key={col} style={{ width: columnWidths[col] ?? DEFAULT_COLUMN_WIDTH }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  {previewCols.map((col) => (
                    <ExportColumnHeader
                      key={col}
                      col={col}
                      width={columnWidths[col] ?? DEFAULT_COLUMN_WIDTH}
                      colLabel={colLabel}
                      sort={visiblePreviewSort}
                      draggedColumn={draggedColumn}
                      onSort={toggleSort}
                      onResizeStart={startColumnResize}
                      onDragStart={setDraggedColumn}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(targetCol) => {
                        if (draggedColumn) moveColumn(draggedColumn, targetCol);
                        setDraggedColumn(null);
                      }}
                      onDragEnd={() => setDraggedColumn(null)}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row) => (
                  <tr key={row.form_id}>
                    {previewCols.map((col) => (
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
