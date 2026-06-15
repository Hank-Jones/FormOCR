import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, type FormType } from "../api/client";
import { useI18n } from "../i18n/useI18n";

const MAX_FORM_TYPE_NAME = 128;

function apiErrorMessage(e: unknown, t: (key: string, params?: Record<string, string | number>) => string): string {
  const raw = String(e).replace(/^Error:\s*/, "");
  let detail = raw;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") {
      detail = parsed.detail;
    }
  } catch {
    // Keep the original message for non-JSON API errors.
  }

  if (detail.includes("Name is required")) return t("formTypes.errorNameRequired");
  if (detail.includes("128 characters")) return t("formTypes.errorNameTooLong", { max: MAX_FORM_TYPE_NAME });
  if (detail.includes("Form type name already exists")) return t("formTypes.errorDuplicateName");
  if (detail.includes("Cannot delete form type while jobs are running")) {
    return t("formTypes.errorDeleteRunning");
  }
  return detail;
}

function FormTypeNameCell({
  ft,
  onRenamed,
  onError,
}: {
  ft: FormType;
  onRenamed: (updated: FormType) => void;
  onError: (msg: string) => void;
}) {
  const { t } = useI18n();
  const [value, setValue] = useState(ft.name);
  const [saving, setSaving] = useState(false);
  const skipBlurCommit = useRef(false);

  useEffect(() => {
    setValue(ft.name);
  }, [ft.name]);

  const commit = async () => {
    if (skipBlurCommit.current) {
      skipBlurCommit.current = false;
      return;
    }
    const trimmed = value.trim();
    if (!trimmed) {
      setValue(ft.name);
      onError(t("formTypes.errorNameRequired"));
      return;
    }
    if (trimmed.length > MAX_FORM_TYPE_NAME) {
      setValue(ft.name);
      onError(t("formTypes.errorNameTooLong", { max: MAX_FORM_TYPE_NAME }));
      return;
    }
    if (trimmed === ft.name) return;
    setSaving(true);
    try {
      const updated = await apiFetch<FormType>(`/form-types/${ft.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });
      onRenamed(updated);
      onError("");
    } catch (e) {
      setValue(ft.name);
      onError(apiErrorMessage(e, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <input
        className="inline-edit"
        value={value}
        disabled={saving}
        aria-label={t("formTypes.editName")}
        maxLength={MAX_FORM_TYPE_NAME}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
          if (e.key === "Escape") {
            skipBlurCommit.current = true;
            setValue(ft.name);
            e.currentTarget.blur();
          }
        }}
      />
      {saving && <span className="muted" style={{ marginLeft: "0.5rem" }}>{t("common.saving")}</span>}
    </>
  );
}

export default function FormTypesPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [types, setTypes] = useState<FormType[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = async (): Promise<boolean> => {
    try {
      const list = await apiFetch<FormType[]>("/form-types");
      setTypes(list);
      setError("");
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    }
  };

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = async () => {
      const ok = await load();
      if (!ok && !stopped) {
        timer = setTimeout(run, 2000);
      }
    };
    run();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const create = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("formTypes.errorNameRequired"));
      return;
    }
    if (trimmed.length > MAX_FORM_TYPE_NAME) {
      setError(t("formTypes.errorNameTooLong", { max: MAX_FORM_TYPE_NAME }));
      return;
    }
    if (creating) return;
    setError("");
    setCreating(true);
    try {
      const ft = await apiFetch<FormType>("/form-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });
      setName("");
      sessionStorage.setItem("formocr_select_form_type", String(ft.id));
      await load();
      navigate(`/templates/${ft.id}`);
    } catch (e) {
      setError(apiErrorMessage(e, t));
    } finally {
      setCreating(false);
    }
  };

  const remove = async (ft: FormType) => {
    if (!confirm(t("formTypes.deleteConfirm", { name: ft.name }))) {
      return;
    }
    if (deletingId !== null) return;
    setError("");
    setDeletingId(ft.id);
    try {
      await apiFetch(`/form-types/${ft.id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, t));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="page page--pro">
      <PageHeader title={t("page.formTypes")} />

      <div className="card card--compact">
        <h3 className="card-title">{t("formTypes.newType")}</h3>
        <div className="form-group">
          <label>{t("common.name")}</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("formTypes.placeholder")}
            maxLength={MAX_FORM_TYPE_NAME}
            disabled={creating}
            onKeyDown={(e) => {
              if (e.key === "Enter") create();
            }}
          />
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        <button type="button" className="btn" onClick={create} disabled={creating}>
          {creating ? t("common.saving") : t("formTypes.createOpen")}
        </button>
      </div>

      <div className="card card--compact">
        <div className="card-header card-header--tight">
          <h3 className="card-title">{t("formTypes.allTypes")}</h3>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => load()}>
            {t("common.refresh")}
          </button>
        </div>
        {types.length === 0 ? (
          <p className="empty-state">{t("formTypes.noTypes")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>{t("common.version")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {types.map((ft) => (
                  <tr key={ft.id}>
                    <td className="td-inline-edit">
                      <FormTypeNameCell
                        ft={ft}
                        onRenamed={(updated) =>
                          setTypes((prev) =>
                            prev.map((x) => (x.id === updated.id ? updated : x))
                          )
                        }
                        onError={setError}
                      />
                    </td>
                    <td>v{ft.version}</td>
                    <td>
                      <span className={`status-badge status-${ft.status === "published" ? "approved" : "pending"}`}>
                        {ft.status}
                      </span>
                    </td>
                    <td>
                      <div className="toolbar" style={{ marginBottom: 0 }}>
                        <Link to={`/templates/${ft.id}`} className="btn btn-sm btn-secondary">
                          {t("common.annotate")}
                        </Link>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          disabled={deletingId === ft.id}
                          onClick={() => remove(ft)}
                        >
                          {deletingId === ft.id ? t("common.loading") : t("common.delete")}
                        </button>
                      </div>
                    </td>
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
