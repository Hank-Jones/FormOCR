import { useCallback, useEffect, useRef, useState } from "react";

import { Link, useLocation } from "react-router-dom";

import {
  apiFetch,
  apiUpload,
  type FormRecord,
  type FormType,
  type Job,
} from "../api/client";

import PageHeader from "../components/PageHeader";
import ProcessingPreview from "../components/ProcessingPreview";
import ProgressBar, { jobProgressLabel, jobProgressPercent } from "../components/ProgressBar";
import { useActiveJob } from "../context/ActiveJobContext";
import { useI18n } from "../i18n/context";
import { displayFields } from "../utils/formFields";

function toMs(iso?: string | null): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function formatDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function FormResultCard({ form }: { form: FormRecord }) {
  const { t } = useI18n();
  const fields = displayFields(form);

  return (
    <div className="card" style={{ marginBottom: "0.75rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div>
          <strong>{t("process.form", { id: form.id })}</strong>
          <span style={{ marginLeft: "0.5rem", color: "var(--muted)" }}>
            {form.review_status}
          </span>
        </div>
        {form.review_status === "pending" && (
          <Link to={`/review/${form.id}`} className="btn">
            {t("common.review")}
          </Link>
        )}
      </div>

      {Object.keys(fields).length > 0 ? (
        <table style={{ marginTop: "0.75rem", width: "100%", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--muted)" }}>
              <th>{t("process.field")}</th>
              <th>{t("process.result")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(fields).map(([key, value]) => (
              <tr key={key}>
                <td style={{ color: "var(--muted)", paddingRight: "0.75rem" }}>{key}</td>
                <td>{value || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--muted)", marginTop: "0.5rem" }}>{t("process.noFields")}</p>
      )}
    </div>
  );
}

export default function ProcessPage() {
  const { t } = useI18n();
  const progressLabel = (job: Parameters<typeof jobProgressLabel>[0]) => jobProgressLabel(job, t);
  const location = useLocation();
  const { job, uploading, trackJob, cancelJob, cancelling } = useActiveJob();
  const [formTypes, setFormTypes] = useState<FormType[]>([]);
  const [formTypeId, setFormTypeId] = useState<string>("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [batchForms, setBatchForms] = useState<FormRecord[]>([]);
  const [resultsError, setResultsError] = useState("");
  const [error, setError] = useState("");
  const [previewForm, setPreviewForm] = useState<FormRecord | null>(null);
  const [uploadStarting, setUploadStarting] = useState(false);
  const [clockMs, setClockMs] = useState(() => Date.now());
  const uploadStartMsRef = useRef<number | null>(null);
  const jobStartMsRef = useRef<number | null>(null);
  const trackedJobIdRef = useRef<number | null>(null);

  const loadFormTypes = useCallback(async (): Promise<boolean> => {
    try {
      const types = await apiFetch<FormType[]>("/form-types");
      setFormTypes(types);
      const pick = sessionStorage.getItem("formocr_select_form_type");
      if (pick && types.some((t) => String(t.id) === pick)) {
        setFormTypeId(pick);
        sessionStorage.removeItem("formocr_select_form_type");
        return true;
      }
      const published = types.filter((t) => t.status === "published");
      if (published.length === 1 && !formTypeId) {
        setFormTypeId(String(published[0].id));
      }
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = async () => {
      const ok = await loadFormTypes();
      if (!ok && !stopped) timer = setTimeout(run, 2000);
    };
    run();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [loadFormTypes]);

  useEffect(() => {
    if (location.pathname === "/process") {
      loadFormTypes();
    }
  }, [location.pathname, loadFormTypes]);

  useEffect(() => {
    const onFocus = () => loadFormTypes();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [loadFormTypes]);

  const loadJobForms = async (jobId: number, formIds?: number[] | null) => {
    setResultsError("");
    if (formIds && formIds.length > 0) {
      const forms = await Promise.all(
        formIds.map((id) => apiFetch<FormRecord>(`/forms/${id}`))
      );
      setBatchForms(forms);
      return;
    }
    const forms = await apiFetch<FormRecord[]>(`/process/jobs/${jobId}/forms`);
    if (forms.length === 0) {
      const alt = await apiFetch<FormRecord[]>(`/forms?job_id=${jobId}`);
      setBatchForms(alt);
      if (alt.length === 0) {
        setResultsError(t("process.noSavedForms"));
      }
      return;
    }
    setBatchForms(forms);
  };

  const refreshResults = async () => {
    if (!job) return;
    setResultsError("");
    try {
      await loadJobForms(job.id, job.form_ids);
    } catch (e) {
      setResultsError(String(e));
    }
  };

  const refreshPreviewForm = async (j: Job) => {
    const fid = j.current_form_id ?? j.form_ids?.[j.form_ids.length - 1];
    if (!fid) {
      setPreviewForm(null);
      return;
    }
    try {
      const f = await apiFetch<FormRecord>(`/forms/${fid}`);
      setPreviewForm(f);
    } catch {
      setPreviewForm(null);
    }
  };

  useEffect(() => {
    if (!job) {
      setPreviewForm(null);
      return;
    }
    const refresh = async () => {
      if (
        job.current_form_id ||
        job.preview_raw_path ||
        job.processed_count > 0 ||
        job.form_ids?.length
      ) {
        await refreshPreviewForm(job);
      }
      if (job.processed_count > 0 || job.form_ids?.length) {
        await loadJobForms(job.id, job.form_ids).catch((e) => {
          setResultsError(String(e));
        });
      }
    };
    void refresh();
    if (job.status === "running" || job.status === "pending") {
      const id = setInterval(() => void refresh(), 800);
      return () => clearInterval(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status, job?.processed_count, job?.fields_done, job?.form_ids?.length]);

  const isActive =
    uploadStarting ||
    uploading ||
    (job != null && (job.status === "running" || job.status === "pending"));

  const timerRunning =
    uploadStarting ||
    uploading ||
    (job != null &&
      (job.status === "running" ||
        job.status === "pending" ||
        job.status === "completed" ||
        job.status === "failed"));

  useEffect(() => {
    if (!timerRunning) return;
    const id = setInterval(() => setClockMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [timerRunning]);

  useEffect(() => {
    if (!job?.id) {
      if (!uploadStarting && !uploading) {
        jobStartMsRef.current = null;
        trackedJobIdRef.current = null;
      }
      return;
    }
    if (trackedJobIdRef.current !== job.id) {
      trackedJobIdRef.current = job.id;
      jobStartMsRef.current = toMs(job.created_at) ?? Date.now();
      uploadStartMsRef.current = null;
    }
  }, [job?.id, job?.created_at, uploadStarting, uploading]);

  const startMs = jobStartMsRef.current ?? uploadStartMsRef.current;
  const endMs = job?.completed_at ? toMs(job.completed_at) : null;
  const elapsedMs =
    startMs != null ? Math.max(0, (endMs ?? clockMs) - startMs) : null;

  const errorSteps =
    job?.steps?.filter(
      (s) =>
        /failed|error|not ready|incomplete/i.test(s) && !/^Preprocess:/i.test(s)
    ) ?? [];

  const publishedTypes = formTypes.filter((t) => t.status === "published");
  const canProcess = Boolean(formTypeId) && !isActive;
  const canStartProcess = canProcess && selectedFiles.length > 0;
  const selectedFileSummary =
    selectedFiles.length === 1
      ? t("process.selectedFile", { name: selectedFiles[0].name })
      : selectedFiles.length > 1
        ? t("process.selectedFiles", { count: selectedFiles.length })
        : "";

  const processFiles = async (files: File[]) => {
    if (files.length === 0) return;
    if (!formTypeId) {
      setError(t("process.selectFormType"));
      return;
    }
    setError("");
    setBatchForms([]);
    setPreviewForm(null);
    setResultsError("");
    uploadStartMsRef.current = Date.now();
    setUploadStarting(true);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    const params = new URLSearchParams();
    params.set("form_type_id", formTypeId);
    params.set("auto_detect", "false");
    params.set("use_ai", "false");
    try {
      const j = await apiUpload<Job>(`/process/batch?${params}`, fd);
      setSelectedFiles([]);
      trackJob(j);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploadStarting(false);
    }
  };

  return (
    <div className="page page--pro">
      <PageHeader title={t("page.process")} />

      <div className="card card--compact">
        <h3 className="card-title">{t("process.newJob")}</h3>
        <div className="form-group">
          <label>{t("common.formType")}</label>
          <select
            value={formTypeId}
            onChange={(e) => setFormTypeId(e.target.value)}
            required
          >
            <option value="">{t("process.selectFormTypePlaceholder")}</option>
            {publishedTypes.map((ft) => (
              <option key={ft.id} value={ft.id}>
                {ft.name}
              </option>
            ))}
          </select>
          {publishedTypes.length === 0 && (
            <p className="alert alert-info" style={{ marginTop: "0.5rem" }}>
              {t("process.noPublishedTypes")}
            </p>
          )}
        </div>
        <div className="upload-zone">
          <label className={`btn btn-lg${canProcess ? "" : " btn-disabled"}`}>
            {t("process.chooseFile")}
            <input
              type="file"
              accept="image/*,.pdf"
              hidden
              disabled={!canProcess}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setError("");
                  setSelectedFiles([f]);
                }
                e.target.value = "";
              }}
            />
          </label>
          <label className={`btn btn-lg btn-secondary${canProcess ? "" : " btn-disabled"}`}>
            {t("process.batchFiles")}
            <input
              type="file"
              accept="image/*,.pdf"
              multiple
              hidden
              disabled={!canProcess}
              onChange={(e) => {
                if (e.target.files?.length) {
                  setError("");
                  setSelectedFiles(Array.from(e.target.files));
                }
                e.target.value = "";
              }}
            />
          </label>
          
          {selectedFiles.length > 0 && !isActive && (
            <button
              type="button"
              className="btn btn-lg"
              disabled={!canStartProcess}
              onClick={() => void processFiles(selectedFiles)}
            >
              {t("process.startProcess")}
            </button>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {(uploading || job) && (
        <div className="card">
          <h3>{job ? t("process.processingJob", { id: job.id }) : t("process.starting")}</h3>
          {job ? (
            <>
              <ProgressBar
                percent={jobProgressPercent(job)}
                label={progressLabel(job)}
                indeterminate={
                  job.status === "pending" &&
                  !job.phase &&
                  (job.progress_percent == null || job.progress_percent <= 0)
                }
              />
              {elapsedMs != null && (
                <p
                  className="muted"
                  style={{ marginTop: "0.35rem", fontSize: "0.85rem" }}
                >
                  {t("process.processingTime")}:{" "}
                  <strong>{formatDuration(elapsedMs)}</strong>
                </p>
              )}
              {isActive && job && (
                <div style={{ marginTop: "0.75rem" }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={cancelling}
                    onClick={() => void cancelJob(job.id)}
                  >
                    {cancelling ? t("process.cancelling") : t("process.cancel")}
                  </button>
                </div>
              )}

              <ProcessingPreview
                job={job}
                form={
                  previewForm ??
                  (job.current_form_id
                    ? batchForms.find((f) => f.id === job.current_form_id) ?? null
                    : null)
                }
              />

              {job.ai_error && (
                <p className="alert alert-error" style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
                  {job.ai_error}
                </p>
              )}
              {errorSteps.length > 0 && (
                <div className="alert alert-error" style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
                  {errorSteps.map((line) => (
                    <p key={line} style={{ margin: "0.2rem 0" }}>
                      {line}
                    </p>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <ProgressBar percent={0} label={t("process.uploading")} indeterminate />
              {elapsedMs != null && (
                <p
                  className="muted"
                  style={{ marginTop: "0.35rem", fontSize: "0.85rem" }}
                >
                  {t("process.processingTime")}:{" "}
                  <strong>{formatDuration(elapsedMs)}</strong>
                </p>
              )}
            </>
          )}

          {job?.status === "cancelled" && (
            <p className="alert alert-info" style={{ marginTop: "0.75rem" }}>
              {t("process.cancelled")}
            </p>
          )}

          {job?.status === "failed" && !job.ai_error && (
            <p className="alert alert-error" style={{ marginTop: "0.75rem" }}>
              {t("process.failed")}
            </p>
          )}

          {resultsError && (
            <div className="alert alert-error" style={{ marginTop: "0.75rem" }}>
              {resultsError}
              {job?.status === "completed" && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ marginLeft: "0.75rem", padding: "0.2rem 0.5rem", fontSize: "0.8rem" }}
                  onClick={() => refreshResults()}
                >
                  {t("process.refreshResults")}
                </button>
              )}
            </div>
          )}

          {job?.status === "completed" && batchForms.length === 0 && resultsError && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ marginTop: "0.5rem" }}
              onClick={() => refreshResults()}
            >
              {t("process.refreshResults")}
            </button>
          )}

          {batchForms.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <h4 style={{ marginBottom: "0.5rem" }}>{t("process.results", { count: batchForms.length })}</h4>
              {batchForms.map((f) => (
                <FormResultCard key={f.id} form={f} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
