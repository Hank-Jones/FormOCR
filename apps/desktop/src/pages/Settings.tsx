import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../api/client";
import { usePendingReview } from "../context/PendingReviewContext";
import { useI18n, type Locale } from "../i18n/context";

interface Settings {
  ocr_lang: string;
  handwriting_ocr_model: string;
}

type ClearHistoryResult = {
  forms_deleted: number;
  jobs_deleted: number;
  corrections_deleted: number;
  files_deleted: number;
  stale_jobs_marked?: number;
};

export default function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const { refresh: refreshPendingCount } = usePendingReview();
  const KO_DEFAULT_HW_MODEL = "qwen2.5vl:3b";
  const [ocrLang, setOcrLang] = useState("ch");
  const [saved, setSaved] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearMessage, setClearMessage] = useState("");
  const [clearError, setClearError] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [forceClear, setForceClear] = useState(false);

  useEffect(() => {
    apiFetch<Settings>("/settings").then((s) => {
      setOcrLang(s.ocr_lang || "ch");
    });
  }, []);

  const save = async () => {
    await apiFetch<Settings>("/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ai_correction_enabled: false,
        ocr_lang: ocrLang,
        handwriting_ocr_enabled: true,
        handwriting_ocr_model: KO_DEFAULT_HW_MODEL,
      }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const runClearHistory = async (force: boolean) => {
    setClearing(true);
    setClearMessage("");
    setClearError("");
    setConfirmClear(false);
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
        }) + extra
      );
      refreshPendingCount();
      setForceClear(false);
    } catch (e) {
      const msg = String(e);
      if (msg.includes("still running") || msg.includes("409")) {
        setClearError(t("settings.clearHistoryRunning"));
        setForceClear(true);
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
        <div className="form-group">
          <label>{t("settings.uiLanguage")}</label>
          <select value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
            <option value="en">{t("settings.lang.en")}</option>
            <option value="zh">{t("settings.lang.zh")}</option>
          </select>
        </div>

        <div className="form-group">
          <label>{t("settings.ocrLanguage")}</label>
          <select value={ocrLang} onChange={(e) => setOcrLang(e.target.value)}>
            <option value="en">{t("settings.ocrLang.en")}</option>
            <option value="ch">{t("settings.ocrLang.ch")}</option>
          </select>
        </div>

        <div className="toolbar toolbar--tight" style={{ marginTop: "0.75rem" }}>
          <button type="button" className="btn" onClick={save}>
            {t("common.save")}
          </button>
          {saved && <span className="muted">{t("common.saved")}</span>}
        </div>
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
