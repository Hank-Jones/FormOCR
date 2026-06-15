import type { Health } from "../api/client";
import { useI18n } from "../i18n/useI18n";
import { StatusChipRow, type ChipState, type StatusChipItem } from "./StatusChips";

function modelShortName(model?: string | null): string {
  if (!model) return "VLM";
  const base = model.split(":")[0] ?? model;
  return base.length > 14 ? base.slice(0, 12) + "…" : base;
}

export function buildHealthChips(
  health: Health | null,
  apiReachable: boolean,
  t: (key: string, params?: Record<string, string | number>) => string
): StatusChipItem[] {
  if (!health && !apiReachable) {
    return [
      { id: "api", label: t("health.chip.api"), state: "pending", title: t("health.statusStarting") },
      { id: "ocr", label: t("health.chip.ocr"), state: "pending", title: t("health.notStarted") },
    ];
  }
  if (!health) {
    return [
      { id: "api", label: t("health.chip.api"), state: "active", title: t("health.statusOkLoading") },
      { id: "ocr", label: t("health.chip.ocr"), state: "active", title: t("health.warming") },
    ];
  }

  const apiState: ChipState =
    health.status === "ok" ? "done" : health.status === "degraded" ? "warn" : "pending";

  let ocrState: ChipState = "pending";
  let ocrTitle = t("health.notStarted");
  if (health.ocr_error) {
    ocrState = "error";
    ocrTitle = t("health.error", { msg: health.ocr_error });
  } else if (health.ocr_ready) {
    ocrState = "done";
    ocrTitle = t("health.ready");
  } else if (health.ocr_warming) {
    ocrState = "active";
    ocrTitle = t("health.warming");
  }

  let visionState: ChipState = "off";
  let visionTitle = t("health.visionOffline");
  if (health.handwriting_model_present) {
    visionState = "done";
    visionTitle = t("health.visionReady");
  } else if (health.ollama_ready) {
    visionState = health.ocr_warming ? "active" : "warn";
    visionTitle = t("health.visionMissing");
  }

  const model = health.handwriting_ollama_model;
  const modelLabel = modelShortName(model).toUpperCase();
  let modelState: ChipState = "off";
  let modelTitle = model ?? t("pipeline.vlm");
  if (health.handwriting_model_present && health.ocr_ready) {
    modelState = "done";
  } else if (health.ocr_warming || (health.ollama_ready && !health.handwriting_model_present)) {
    modelState = "active";
  } else if (health.ollama_ready) {
    modelState = "warn";
  }

  const chips: StatusChipItem[] = [
    {
      id: "api",
      label: t("health.chip.api"),
      state: apiState,
      title: `${t("health.chip.status")}: ${health.status}`,
    },
    { id: "ocr", label: t("health.chip.ocr"), state: ocrState, title: ocrTitle },
    { id: "vision", label: t("pipeline.vision"), state: visionState, title: visionTitle },
  ];

  if (modelState !== "off" || health.ocr_warming || health.ocr_ready) {
    chips.push({
      id: "model",
      label: modelLabel,
      state: modelState,
      title: modelTitle,
    });
  }

  if (health.ollama_on_gpu === true) {
    chips.push({
      id: "compute",
      label: t("pipeline.gpu"),
      state: "done",
      title: t("pipeline.gpuHint", { mb: health.ollama_vram_mb ?? 0 }),
    });
  } else if (
    health.ollama_on_gpu === false &&
    (health.handwriting_model_present || health.ocr_ready || health.ocr_warming)
  ) {
    const host = health.ollama_host || "";
    chips.push({
      id: "compute",
      label: t("pipeline.cpu"),
      state: host.includes(":11434") ? "error" : "warn",
      title: host.includes(":11434")
        ? t("vision.wrongOllama.detail")
        : t("pipeline.cpuHint"),
    });
  }

  return chips;
}

export default function HealthIndicators({
  health,
  apiReachable = false,
  className = "",
}: {
  health: Health | null;
  apiReachable?: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  const chips = buildHealthChips(health, apiReachable, t);
  return (
    <StatusChipRow chips={chips} ariaLabel={t("health.chip.aria")} className={className} />
  );
}
