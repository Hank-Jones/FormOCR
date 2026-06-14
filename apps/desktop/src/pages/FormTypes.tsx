import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, type FormType } from "../api/client";
import { useI18n } from "../i18n/context";

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

  useEffect(() => {
    setValue(ft.name);
  }, [ft.name]);

  const commit = async () => {
    const trimmed = value.trim();
    if (!trimmed) {
      setValue(ft.name);
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
    } catch (e) {
      setValue(ft.name);
      onError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <input
      className="inline-edit"
      value={value}
      disabled={saving}
      aria-label={t("formTypes.editName")}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => void commit()}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
        if (e.key === "Escape") {
          setValue(ft.name);
          e.currentTarget.blur();
        }
      }}
    />
  );
}

export default function FormTypesPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [types, setTypes] = useState<FormType[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

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
    if (!name.trim()) return;
    setError("");
    try {
      const ft = await apiFetch<FormType>("/form-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      setName("");
      sessionStorage.setItem("formocr_select_form_type", String(ft.id));
      await load();
      navigate(`/templates/${ft.id}`);
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (ft: FormType) => {
    if (!confirm(t("formTypes.deleteConfirm", { name: ft.name }))) {
      return;
    }
    setError("");
    try {
      await apiFetch(`/form-types/${ft.id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(String(e));
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
            onKeyDown={(e) => {
              if (e.key === "Enter") create();
            }}
          />
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        <button type="button" className="btn" onClick={create}>
          {t("formTypes.createOpen")}
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
                          onClick={() => remove(ft)}
                        >
                          {t("common.delete")}
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
