import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, type FormRecord, type Job } from "../api/client";
import { useI18n } from "../i18n/context";

export default function Dashboard() {
  const { t } = useI18n();
  const [forms, setForms] = useState<FormRecord[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    apiFetch<FormRecord[]>("/forms?limit=10").then(setForms).catch(() => {});
    apiFetch<Job[]>("/process/jobs?limit=5").then(setJobs).catch(() => {});
  }, []);

  const pending = forms.filter((f) => f.review_status === "pending");

  return (
    <div className="page page--pro">
      <PageHeader
        title={t("page.dashboard")}
        actions={
          <>
            <Link to="/process" className="btn">
              {t("dashboard.processForms")}
            </Link>
            <Link to="/form-types" className="btn btn-secondary">
              {t("dashboard.buildTemplate")}
            </Link>
          </>
        }
      />

      <div className="card card--compact">
        <div className="card-header card-header--tight">
          <h3 className="card-title">{t("dashboard.recentJobs")}</h3>
        </div>
        {jobs.length === 0 ? (
          <p className="empty-state">{t("dashboard.noJobsStart")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("common.id")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("common.progress")}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>#{j.id}</td>
                    <td>
                      <span className={`status-badge status-${j.status}`}>
                        {j.status}
                      </span>
                    </td>
                    <td>
                      {j.processed_count}/{j.total_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card card--compact">
        <div className="card-header card-header--tight">
          <h3 className="card-title">{t("dashboard.pendingReview")}</h3>
          {pending.length > 0 && (
            <span className="status-badge status-pending">
              {t("dashboard.pendingCount", { count: pending.length })}
            </span>
          )}
        </div>
        {pending.length === 0 ? (
          <p className="empty-state">{t("dashboard.noPendingReview")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("dashboard.form")}</th>
                  <th>{t("common.status")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pending.map((f) => (
                  <tr key={f.id}>
                    <td>#{f.id}</td>
                    <td>{f.review_status}</td>
                    <td>
                      <Link to={`/review/${f.id}`} className="btn btn-sm btn-secondary">
                        {t("common.review")}
                      </Link>
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
