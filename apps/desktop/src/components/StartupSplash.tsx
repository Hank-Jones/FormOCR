import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import BrandLogo from "./BrandLogo";
import { apiFetchHealth, apiFetchLive, type Health } from "../api/client";
import { useI18n } from "../i18n/context";

async function getApiLogTail(): Promise<string> {
  try {
    return await invoke<string>("get_api_log_tail");
  } catch {
    return "";
  }
}

async function getApiLogPath(): Promise<string> {
  try {
    return await invoke<string>("get_api_log_path");
  } catch {
    return "%LOCALAPPDATA%\\FormOCR\\api-server.log";
  }
}

interface StartupStatus {
  phase: string;
  message: string;
  ready: boolean;
  progress: number;
  error: string | null;
}

const SPLASH_MAX_MS = 6 * 60 * 1000;
/** Keep splash visible at least this long once shown (avoids flash). */
const MIN_SPLASH_MS = 2800;

/** Progress reflects OCR readiness — not desktop bootstrap "ready" alone. */
function splashProgress(
  status: StartupStatus | null,
  health: Health | null,
  apiReachable: boolean
): number {
  if (health?.ocr_ready) return 100;
  const base = status?.progress ?? 8;
  if (health?.ocr_warming || (health && !health.ocr_ready && !health.ocr_error)) {
    return Math.max(72, Math.min(92, base || 80));
  }
  if (apiReachable && !health) return Math.max(base, 50);
  return Math.max(8, Math.min(70, base));
}

function splashStatusText(
  status: StartupStatus | null,
  health: Health | null,
  apiReachable: boolean,
  t: (key: string) => string
): string {
  if (health?.ocr_ready) return t("splash.allReady");
  if (status?.message) return status.message;
  if (health?.ocr_error) return t("splash.ocrError");
  if (health?.ocr_warming) return t("splash.loadingVision");
  if (health && !health.ocr_ready) return t("splash.loadingVision");
  if (apiReachable) return t("splash.connecting");
  return t("splash.initializing");
}

export default function StartupSplash({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const isDev = !!import.meta.env.FORMOCR_DEV_API;
  const [status, setStatus] = useState<StartupStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [apiReachable, setApiReachable] = useState(false);
  const [visible, setVisible] = useState(!isDev);
  const [apiLogTail, setApiLogTail] = useState("");
  const [apiLogPath, setApiLogPath] = useState("");

  const pollInFlight = useRef(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingStoppedRef = useRef(false);
  const dismissedRef = useRef(false);
  const lastFullHealthMs = useRef(0);
  const hasFullHealth = useRef(false);

  const stopSplashPolling = () => {
    pollingStoppedRef.current = true;
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const splashShownAt = useRef(Date.now());

  const dismissSplash = () => {
    if (dismissedRef.current) return;
    dismissedRef.current = true;
    stopSplashPolling();
    const elapsed = Date.now() - splashShownAt.current;
    const wait = Math.max(0, MIN_SPLASH_MS - elapsed);
    setTimeout(() => setVisible(false), wait + 200);
  };

  useEffect(() => {
    if (isDev || !visible || dismissedRef.current) return;

    pollingStoppedRef.current = false;
    const started = Date.now();
    const FULL_HEALTH_INTERVAL_MS = 5000;

    const poll = async () => {
      if (pollingStoppedRef.current || pollInFlight.current) return;
      pollInFlight.current = true;
      try {
        const s = await invoke<StartupStatus>("get_startup_status");
        if (pollingStoppedRef.current) return;
        setStatus(s);

        let reachable = false;
        try {
          await apiFetchLive();
          reachable = true;
          if (!pollingStoppedRef.current) setApiReachable(true);
        } catch {
          if (!pollingStoppedRef.current) setApiReachable(false);
        }

        let h: Health | null = null;
        const now = Date.now();
        const needFull =
          reachable &&
          (now - lastFullHealthMs.current >= FULL_HEALTH_INTERVAL_MS || !hasFullHealth.current);
        if (needFull) {
          try {
            h = await apiFetchHealth();
            lastFullHealthMs.current = now;
            hasFullHealth.current = true;
            if (!pollingStoppedRef.current) setHealth(h);
          } catch {
            /* full health can be slow while Ollama warms — keep last value */
          }
        }

        const isError = s?.phase === "error";
        if (isError && !pollingStoppedRef.current) {
          getApiLogTail().then((tail) => {
            if (!pollingStoppedRef.current) setApiLogTail(tail);
          });
          getApiLogPath().then((p) => {
            if (!pollingStoppedRef.current) setApiLogPath(p);
          });
        }
        const elapsed = Date.now() - started;
        if (!isError) {
          if (h?.ocr_ready) {
            dismissSplash();
            return;
          }
          if (s?.ready && elapsed >= MIN_SPLASH_MS) {
            dismissSplash();
            return;
          }
        }

        if (Date.now() - started > SPLASH_MAX_MS) {
          dismissSplash();
        }
      } catch {
        /* ignore */
      } finally {
        pollInFlight.current = false;
      }
    };

    poll();
    pollIntervalRef.current = setInterval(poll, 1000);
    return () => {
      stopSplashPolling();
    };
  }, [isDev, visible]);

  if (!visible) {
    return <>{children}</>;
  }

  const progress = splashProgress(status, health, apiReachable);
  const statusText = splashStatusText(status, health, apiReachable, t);
  const phase = status?.phase || "init";
  const error = status?.error;
  const ocrReady = !!health?.ocr_ready;
  const visionWarming = !!health && !health.ocr_ready && !health.ocr_error;

  return (
    <>
      <div className="splash-overlay" role="dialog" aria-busy={!status?.ready} aria-label="Loading">
        <div className="splash-bg" />
        <div className="splash-content">
          <BrandLogo className="brand-logo brand-logo--splash" alt={t("app.name")} />

          <div className="splash-progress-track">
            <div
              className="splash-progress-fill"
              style={{ width: `${progress}%` }}
            />
          </div>

          <p className="splash-message">
            {statusText} · {progress}%
          </p>

          {error && (
            <div className="splash-error">
              {error}
              {apiLogPath && (
                <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", wordBreak: "break-all" }}>
                  {t("splash.log")}: <strong>{apiLogPath}</strong>
                </div>
              )}
              {apiLogTail && (
                <pre style={{
                  marginTop: "0.5rem",
                  padding: "0.5rem",
                  background: "rgba(0,0,0,0.3)",
                  borderRadius: 4,
                  fontSize: "0.7rem",
                  maxHeight: 120,
                  overflow: "auto",
                  textAlign: "left",
                  whiteSpace: "pre-wrap",
                }}>
                  {apiLogTail}
                </pre>
              )}
            </div>
          )}

          {!ocrReady && (phase === "vision" || visionWarming) && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ marginTop: "1rem" }}
              onClick={() => dismissSplash()}
            >
              {t("splash.continueSkip")}
            </button>
          )}
        </div>
      </div>
    </>
  );
}
