import { useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../api/client";
import { usePendingReview } from "../context/PendingReviewContext";
import type { Locale } from "../i18n/context";
import { useI18n } from "../i18n/useI18n";

interface Settings {
  ai_correction_enabled: boolean;
  ocr_lang: string;
  handwriting_ocr_enabled: boolean;
  handwriting_ocr_model: string;
}

type ClearHistoryResult = {
  forms_deleted: number;
  jobs_deleted: number;
  corrections_deleted: number;
  files_deleted: number;
  stale_jobs_marked?: number;
};

const HIDDEN_OCR_SETTINGS = {
  ai_correction_enabled: true,
  handwriting_ocr_enabled: true,
  handwriting_ocr_model: "qwen2.5vl:3b",
} satisfies Pick<
  Settings,
  "ai_correction_enabled" | "handwriting_ocr_enabled" | "handwriting_ocr_model"
>;

function apiErrorMessage(e: unknown, t: (key: string, params?: Record<string, string | number>) => string): string {
  const raw = String(e).replace(/^Error:\s*/, "");
  let detail = raw;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // Keep raw text for non-JSON responses.
  }
  if (detail.includes("Handwriting OCR model is required")) {
    return t("settings.errorModelRequired");
  }
  if (detail.includes("Unsupported OCR language")) {
    return t("settings.errorUnsupportedOcrLang");
  }
  return detail;
}

export default function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const { refresh: refreshPendingCount } = usePendingReview();
  const [ocrLang, setOcrLang] = useState("");
  const [savedSettings, setSavedSettings] = useState<Settings | null>(null);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [clearing, setClearing] = useState(false);
  const [clearMessage, setClearMessage] = useState("");
  const [clearError, setClearError] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [forceClear, setForceClear] = useState(false);

  useEffect(() => {
    apiFetch<Settings>("/settings")
      .then((s) => {
        setOcrLang(s.ocr_lang);
        setSavedSettings({ ...s, ...HIDDEN_OCR_SETTINGS });
        setSettingsLoaded(true);
      })
      .catch((e) => {
        setSaveError(String(e).replace(/^Error:\s*/, ""));
      })
      .finally(() => {
        setSettingsLoading(false);
      });
  }, []);

  const currentSettings = useMemo<Settings>(
    () => ({
      ai_correction_enabled: HIDDEN_OCR_SETTINGS.ai_correction_enabled,
      ocr_lang: ocrLang,
      handwriting_ocr_enabled: HIDDEN_OCR_SETTINGS.handwriting_ocr_enabled,
      handwriting_ocr_model: HIDDEN_OCR_SETTINGS.handwriting_ocr_model,
    }),
    [ocrLang]
  );

  const hasUnsavedChanges =
    settingsLoaded &&
    savedSettings !== null &&
    currentSettings.ocr_lang !== savedSettings.ocr_lang;

  const save = async () => {
    if (!settingsLoaded || saving) return;
    if (!currentSettings.handwriting_ocr_model) {
      setSaveError(t("settings.errorModelRequired"));
      setSaved(false);
      return;
    }
    setSaveError("");
    setSaved(false);
    setSaving(true);
    try {
      const updated = await apiFetch<Settings>("/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentSettings),
      });
      setOcrLang(updated.ocr_lang);
      setSavedSettings({ ...updated, ...HIDDEN_OCR_SETTINGS });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setSaveError(apiErrorMessage(e, t));
    } finally {
      setSaving(false);
    }
  };

  const runClearHistory = async (force: boolean) => {
    setClearing(true);
    setClearMessage("");
    setClearError("");
    try {
      const result = await apiFetch<ClearHistoryResult>("/settings/clear-history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, force }),
      });
      const extra =
        result.stale_jobs_marked && result.stale_jobs_marked > 0
          ? ` ${t("settings.clearHistoryStale", { count: result.stale_jobs_marked })}`
          : "";
      setClearMessage(
        t("settings.clearHistoryDone", {
          forms: result.forms_deleted,
          jobs: result.jobs_deleted,
        }) +
          " " +
          t("settings.clearHistoryDetails", {
            files: result.files_deleted,
            corrections: result.corrections_deleted,
          }) +
          extra
      );
      refreshPendingCount();
      setForceClear(false);
      setConfirmClear(false);
    } catch (e) {
      const msg = String(e);
      if (msg.includes("still running") || msg.includes("409")) {
        setClearError(t("settings.clearHistoryRunning"));
        setForceClear(true);
        setConfirmClear(true);
      } else {
        setClearError(msg);
        setForceClear(false);
      }
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="page page--pro">
      <PageHeader title={t("page.settings")} />
      <div className="card card--compact">
        {settingsLoading && (
          <p className="muted" style={{ marginTop: 0 }}>
            {t("common.loading")}
          </p>
        )}
        <div className="form-group">
          <label>{t("settings.uiLanguage")}</label>
          <select value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
            <option value="en">{t("settings.lang.en")}</option>
            <option value="zh">{t("settings.lang.zh")}</option>
          </select>
        </div>

        <div className="form-group">
          <label>{t("settings.ocrLanguage")}</label>
          <select
            value={ocrLang}
            onChange={(e) => setOcrLang(e.target.value)}
            disabled={!settingsLoaded}
          >
            <option value="" disabled>
              {t("common.loading")}
            </option>
            <option value="en">{t("settings.ocrLang.en")}</option>
            <option value="ch">{t("settings.ocrLang.ch")}</option>
          </select>
        </div>

        <div className="toolbar toolbar--tight" style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            className="btn"
            onClick={save}
            disabled={!settingsLoaded || saving || !hasUnsavedChanges}
          >
            {saving ? t("common.saving") : t("common.save")}
          </button>
          {hasUnsavedChanges && !saving && <span className="muted">{t("settings.unsavedChanges")}</span>}
          {saved && <span className="muted">{t("common.saved")}</span>}
        </div>
        {saveError && (
          <p className="alert alert-error" style={{ marginTop: "0.75rem" }}>
            {saveError}
          </p>
        )}
      </div>

      <div className="card card--compact settings-danger-zone">
        <h3 className="card-title">{t("settings.dataTitle")}</h3>
        {!confirmClear ? (
          <div className="toolbar toolbar--tight" style={{ marginTop: "0.75rem" }}>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => {
                setConfirmClear(true);
                setClearError("");
                setClearMessage("");
              }}
              disabled={clearing}
            >
              {t("settings.clearHistory")}
            </button>
          </div>
        ) : (
          <div className="settings-clear-confirm" style={{ marginTop: "0.75rem" }}>
            <p>{t("settings.clearHistoryConfirm")}</p>
            {forceClear && (
              <p className="alert alert-info" style={{ marginTop: "0.5rem" }}>
                {t("settings.clearHistoryRunning")}
              </p>
            )}
            <div className="toolbar toolbar--tight" style={{ marginTop: "0.5rem" }}>
              <button
                type="button"
                className="btn btn-danger"
                disabled={clearing}
                onClick={() => runClearHistory(forceClear)}
              >
                {clearing
                  ? t("settings.clearHistoryBusy")
                  : forceClear
                    ? t("settings.clearHistoryForce")
                    : t("settings.clearHistoryConfirmBtn")}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={clearing}
                onClick={() => {
                  setConfirmClear(false);
                  setForceClear(false);
                }}
              >
                {t("settings.clearHistoryCancel")}
              </button>
            </div>
          </div>
        )}
        {clearMessage && (
          <p className="alert alert-info" style={{ marginTop: "0.75rem" }}>
            {clearMessage}
          </p>
        )}
        {clearError && (
          <p className="alert alert-error" style={{ marginTop: "0.75rem" }}>
            {clearError}
          </p>
        )}
      </div>
    </div>
  );
}
