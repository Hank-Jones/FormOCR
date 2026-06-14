import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

import { apiFetch, type Job } from "../api/client";
import { useI18n } from "../i18n/context";
import { notifyJobFinished } from "../utils/jobNotify";

export const ACTIVE_JOB_KEY = "formocr_active_job_id";
const BADGE_KEY = "formocr_process_badge";

function readBadge(): number {
  try {
    const n = Number(sessionStorage.getItem(BADGE_KEY));
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
  } catch {
    return 0;
  }
}

function writeBadge(n: number) {
  try {
    if (n > 0) sessionStorage.setItem(BADGE_KEY, String(n));
    else sessionStorage.removeItem(BADGE_KEY);
  } catch {
    /* ignore */
  }
}

type ActiveJobContextValue = {
  job: Job | null;
  uploading: boolean;
  badgeCount: number;
  clearBadge: () => void;
  trackJob: (job: Job) => void;
  cancelJob: (jobId: number) => Promise<void>;
  cancelling: boolean;
};

const ActiveJobContext = createContext<ActiveJobContextValue | null>(null);

export function ActiveJobProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const location = useLocation();
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [badgeCount, setBadgeCount] = useState(readBadge);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobIdRef = useRef<number | null>(null);
  const notifiedRef = useRef<number | null>(null);
  const pathnameRef = useRef(location.pathname);
  pathnameRef.current = location.pathname;

  const clearBadge = useCallback(() => {
    setBadgeCount(0);
    writeBadge(0);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const bumpBadge = useCallback(() => {
    setBadgeCount((prev) => {
      const next = prev + 1;
      writeBadge(next);
      return next;
    });
  }, []);

  const onJobTerminal = useCallback(
    (j: Job) => {
      if (notifiedRef.current === j.id) return;
      notifiedRef.current = j.id;

      const awayFromProcess = pathnameRef.current !== "/process";
      const appInBackground = typeof document !== "undefined" && document.hidden;

      if (awayFromProcess) {
        bumpBadge();
      }
      if (awayFromProcess || appInBackground) {
        void notifyJobFinished(j, {
          titleFailed: t("notify.titleFailed"),
          titleComplete: t("notify.titleComplete"),
          bodyFailed: (id) => t("notify.bodyFailed", { id }),
          bodyComplete: (id, summary) => t("notify.bodyComplete", { id, summary }),
          jobSummary: (n, total) => t("notify.summary", { n, total }),
        });
      }
    },
    [bumpBadge, t]
  );

  const pollJob = useCallback(
    (id: number) => {
      stopPolling();
      jobIdRef.current = id;
      try {
        sessionStorage.setItem(ACTIVE_JOB_KEY, String(id));
      } catch {
        /* ignore */
      }

      const tick = async () => {
        try {
          const j = await apiFetch<Job>(`/process/jobs/${id}`);
          setJob(j);
          if (j.status === "completed" || j.status === "failed" || j.status === "cancelled") {
            stopPolling();
            setUploading(false);
            setCancelling(false);
            jobIdRef.current = null;
            try {
              sessionStorage.removeItem(ACTIVE_JOB_KEY);
            } catch {
              /* ignore */
            }
            onJobTerminal(j);
          }
        } catch {
          stopPolling();
          setUploading(false);
        }
      };

      tick();
      pollRef.current = setInterval(tick, 800);
    },
    [stopPolling, onJobTerminal]
  );

  const trackJob = useCallback(
    (j: Job) => {
      notifiedRef.current = null;
      setJob(j);
      setUploading(true);
      if (j.status === "running" || j.status === "pending") {
        pollJob(j.id);
      } else {
        setUploading(false);
      }
    },
    [pollJob]
  );

  const cancelJob = useCallback(async (jobId: number) => {
    setCancelling(true);
    try {
      const j = await apiFetch<Job>(`/process/jobs/${jobId}/cancel`, { method: "POST" });
      setJob(j);
      if (j.status === "cancelled") {
        stopPolling();
        setUploading(false);
        setCancelling(false);
        jobIdRef.current = null;
        try {
          sessionStorage.removeItem(ACTIVE_JOB_KEY);
        } catch {
          /* ignore */
        }
      }
    } catch {
      setCancelling(false);
    }
  }, [stopPolling]);

  useEffect(() => {
    if (location.pathname === "/process") {
      clearBadge();
    }
  }, [location.pathname, clearBadge]);

  useEffect(() => {
    void (async () => {
      try {
        const { isPermissionGranted, requestPermission } = await import(
          "@tauri-apps/plugin-notification"
        );
        if (!(await isPermissionGranted())) {
          await requestPermission();
        }
      } catch {
        /* browser dev or permission denied */
      }
    })();
  }, []);

  useEffect(() => {
    const raw = sessionStorage.getItem(ACTIVE_JOB_KEY);
    const id = raw ? Number(raw) : NaN;
    if (!Number.isFinite(id) || id <= 0) return;

    apiFetch<Job>(`/process/jobs/${id}`)
      .then((j) => {
        setJob(j);
        if (j.status === "running" || j.status === "pending") {
          setUploading(true);
          pollJob(id);
        } else {
          setUploading(false);
          setCancelling(false);
          try {
            sessionStorage.removeItem(ACTIVE_JOB_KEY);
          } catch {
            /* ignore */
          }
        }
      })
      .catch(() => {});

    return () => stopPolling();
    // Resume once on app load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  return (
    <ActiveJobContext.Provider
      value={{ job, uploading, badgeCount, clearBadge, trackJob, cancelJob, cancelling }}
    >
      {children}
    </ActiveJobContext.Provider>
  );
}

export function useActiveJob(): ActiveJobContextValue {
  const ctx = useContext(ActiveJobContext);
  if (!ctx) {
    throw new Error("useActiveJob must be used within ActiveJobProvider");
  }
  return ctx;
}
