import type { ComponentType } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { ActiveJobProvider, useActiveJob } from "./context/ActiveJobContext";
import { PendingReviewProvider, usePendingReview } from "./context/PendingReviewContext";
import { SystemHealthProvider, useSystemHealth } from "./context/SystemHealthContext";
import {
  IconDashboard,
  IconExport,
  IconFormTypes,
  IconProcess,
  IconReview,
  IconSettings,
} from "./components/icons";
import { useI18n } from "./i18n/useI18n";
import Dashboard from "./pages/Dashboard";
import FormTypesPage from "./pages/FormTypes";
import TemplateBuilder from "./pages/TemplateBuilder";
import ProcessPage from "./pages/Process";
import ReviewPage from "./pages/Review";
import ExportPage from "./pages/Export";
import SettingsPage from "./pages/Settings";
import BrandLogo from "./components/BrandLogo";
import NavProgressRing from "./components/NavProgressRing";
import NavStatusCheck from "./components/NavStatusCheck";
import { jobProgressLabel, jobProgressPercent } from "./components/ProgressBar";
import StartupGate from "./components/StartupGate";

function NavItem({
  to,
  end,
  labelKey,
  Icon,
}: {
  to: string;
  end?: boolean;
  labelKey: string;
  Icon: ComponentType<{ className?: string }>;
}) {
  const { t } = useI18n();
  const { badgeCount, job, uploading } = useActiveJob();
  const { readiness } = useSystemHealth();
  const { pendingCount } = usePendingReview();

  const isProcessing =
    uploading ||
    (job != null && (job.status === "running" || job.status === "pending"));

  const showProgress = to === "/process" && isProcessing;
  const showProcessBadge = to === "/process" && badgeCount > 0 && !showProgress;
  const showReviewBadge = to === "/review" && pendingCount > 0;

  const progressPercent = job ? jobProgressPercent(job) : 0;
  const progressIndeterminate =
    showProgress &&
    ((!job && uploading) ||
      (job != null &&
        job.status === "pending" &&
        !job.phase &&
        (job.progress_percent == null || job.progress_percent <= 0)));

  const progressAria = job
    ? jobProgressLabel(job, t)
    : uploading
      ? t("process.uploading")
      : t("process.starting");

  const isDashboard = to === "/";
  const dashLoading =
    isDashboard &&
    (readiness === "checking" || readiness === "starting" || readiness === "warming");
  const dashReady = isDashboard && readiness === "ready";
  const dashDegraded = isDashboard && readiness === "degraded";
  const dashError = isDashboard && readiness === "error";

  const dashProgressAria =
    readiness === "checking"
      ? t("nav.dashboardStarting")
      : readiness === "starting"
        ? t("nav.dashboardApi")
        : t("nav.dashboardWarming");

  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
      <span className="nav-icon">
        <Icon className="nav-icon-svg" />
      </span>
      <span className="nav-item-label">{t(labelKey)}</span>
      {showProgress && (
        <NavProgressRing
          percent={progressPercent}
          indeterminate={progressIndeterminate}
          ariaLabel={progressAria}
        />
      )}
      {showProcessBadge && (
        <span className="nav-badge" aria-label={t("nav.processBadge", { count: badgeCount })}>
          {badgeCount > 99 ? "99+" : badgeCount}
        </span>
      )}
      {showReviewBadge && (
        <span
          className="nav-badge nav-badge--review"
          aria-label={t("nav.reviewBadge", { count: pendingCount })}
        >
          {pendingCount > 99 ? "99+" : pendingCount}
        </span>
      )}
      {dashLoading && (
        <NavProgressRing percent={0} indeterminate ariaLabel={dashProgressAria} />
      )}
      {dashReady && <NavStatusCheck variant="ready" ariaLabel={t("nav.dashboardReady")} />}
      {dashDegraded && (
        <NavStatusCheck variant="degraded" ariaLabel={t("nav.dashboardDegraded")} />
      )}
      {dashError && <NavStatusCheck variant="error" ariaLabel={t("nav.dashboardError")} />}
    </NavLink>
  );
}

function AppShell() {
  const { t } = useI18n();

  const navMain = [
    { to: "/", end: true as const, labelKey: "nav.dashboard", Icon: IconDashboard },
    { to: "/process", labelKey: "nav.process", Icon: IconProcess },
    { to: "/review", labelKey: "nav.review", Icon: IconReview },
  ];

  const navSetup = [
    { to: "/export", labelKey: "nav.export", Icon: IconExport },
  ];

  const navSystem = [
    { to: "/form-types", labelKey: "nav.formTypes", Icon: IconFormTypes },
    { to: "/settings", labelKey: "nav.settings", Icon: IconSettings },
  ];

  return (
    <div className="app-layout app-layout--pro">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-logo">
            <BrandLogo className="brand-logo brand-logo--sidebar" alt={t("app.name")} />
          </div>
          <span className="sidebar-title">{t("app.name")}</span>
        </div>

        <nav className="sidebar-nav" aria-label={t("nav.main")}>
          {navMain.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
          {navSetup.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
          {navSystem.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
      </aside>

      <main className="main">
        <div className="main-inner">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/form-types" element={<FormTypesPage />} />
            <Route path="/templates" element={<TemplateBuilder />} />
            <Route path="/templates/:formTypeId" element={<TemplateBuilder />} />
            <Route path="/process" element={<ProcessPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/review/:formId" element={<ReviewPage />} />
            <Route path="/export" element={<ExportPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <StartupGate>
      <BrowserRouter>
        <SystemHealthProvider>
          <PendingReviewProvider>
            <ActiveJobProvider>
              <AppShell />
            </ActiveJobProvider>
          </PendingReviewProvider>
        </SystemHealthProvider>
      </BrowserRouter>
    </StartupGate>
  );
}
