import type { Health } from "../api/client";
import HealthIndicators from "./HealthIndicators";

/** When vision model is in CPU/RAM — explain whether it's misconfiguration or expected hardware. */
export function visionCpuNotice(
  health: Health,
  t: (key: string) => string
): {
  tone: "error" | "info";
  title: string;
  detail: string;
} | null {
  if (health.ollama_on_gpu !== false) return null;
  const host = health.ollama_host || "";
  if (host.includes(":11434")) {
    return {
      tone: "error",
      title: t("vision.wrongOllama.title"),
      detail: t("vision.wrongOllama.detail"),
    };
  }
  return null;
}

export default function SystemHealthStatus({
  health,
  apiReachable = false,
  variant = "card",
}: {
  health: Health | null;
  apiReachable?: boolean;
  variant?: "card" | "splash";
}) {
  const isDegraded = health?.status === "degraded";
  const ocrLoading = health && !health.ocr_ready && !health.ocr_error && !!health.ocr_warming;

  const wrapClass =
    variant === "splash"
      ? `splash-status${isDegraded ? " splash-status-degraded" : ""}${
          ocrLoading ? " splash-status-loading" : ""
        }`
      : `health-banner${isDegraded ? " health-banner-degraded" : ""}${
          ocrLoading ? " health-banner-loading" : ""
        }`;

  return (
    <div className={wrapClass} role="status" aria-live="polite">
      <HealthIndicators
        health={health}
        apiReachable={apiReachable}
        className={variant === "splash" ? "status-chips--splash" : "status-chips--banner"}
      />
    </div>
  );
}
