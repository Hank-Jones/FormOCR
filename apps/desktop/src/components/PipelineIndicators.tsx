import type { Health, Job } from "../api/client";
import { useI18n } from "../i18n/useI18n";
import { StatusChipRow, type ChipState, type StatusChipItem } from "./StatusChips";

function mergePipeline(job: Job | null, health: Health | null): Record<string, string> {
  const p = { ...(job?.pipeline ?? {}) };
  if (!p.compute || p.compute === "unknown") {
    if (health?.ollama_on_gpu === true) p.compute = "gpu";
    else if (health?.ollama_on_gpu === false && health.handwriting_model_present) {
      p.compute = "cpu";
    }
  }
  return p;
}

export default function PipelineIndicators({
  job,
  health,
}: {
  job: Job | null;
  health?: Health | null;
}) {
  const { t } = useI18n();
  const pipe = mergePipeline(job, health ?? null);

  const preprocessState: ChipState =
    pipe.preprocess === "done"
      ? "done"
      : pipe.preprocess === "active" || job?.phase === "preprocess"
        ? "active"
        : job?.status === "running" || job?.status === "pending"
          ? "pending"
          : "off";

  const visionState: ChipState =
    pipe.vision === "ready"
      ? "done"
      : pipe.vision === "error"
        ? "error"
        : pipe.vision === "warming"
          ? "active"
          : pipe.vision === "pending" && (job?.status === "running" || job?.status === "pending")
            ? "pending"
            : "off";

  const vlmState: ChipState =
    pipe.vlm === "done"
      ? "done"
      : pipe.vlm === "active" || job?.phase === "ocr"
        ? "active"
        : "off";

  const compute = pipe.compute ?? "unknown";
  const computeState: ChipState =
    compute === "gpu" ? "done" : compute === "cpu" ? "warn" : "off";

  const llmState: ChipState =
    pipe.llm === "done" ? "done" : pipe.llm === "active" || job?.phase === "ai" ? "active" : "off";

  const modelShort =
    job?.handwriting_model?.split(":")[0] ?? health?.handwriting_ollama_model?.split(":")[0] ?? "VLM";

  const chips: StatusChipItem[] = [
    {
      id: "preprocess",
      label: t("pipeline.preprocess"),
      state: preprocessState,
      title: t("pipeline.preprocessHint"),
    },
    {
      id: "vision",
      label: t("pipeline.vision"),
      state: visionState,
      title:
        visionState === "error"
          ? t("pipeline.visionError")
          : visionState === "active"
            ? t("pipeline.visionWarming")
            : t("pipeline.visionReady"),
    },
    {
      id: "vlm",
      label: modelShort.toUpperCase(),
      state: vlmState,
      title: job?.handwriting_model ?? health?.handwriting_ollama_model ?? t("pipeline.vlm"),
    },
  ];

  if (compute === "gpu" || compute === "cpu") {
    chips.push({
      id: "compute",
      label: compute === "gpu" ? t("pipeline.gpu") : t("pipeline.cpu"),
      state: computeState,
      title:
        compute === "gpu"
          ? t("pipeline.gpuHint", { mb: health?.ollama_vram_mb ?? 0 })
          : t("pipeline.cpuHint"),
    });
  }

  if (pipe.llm && pipe.llm !== "off") {
    chips.push({
      id: "llm",
      label: t("pipeline.llm"),
      state: llmState,
      title: job?.ai_model ?? t("pipeline.llm"),
    });
  }

  const anyOn = chips.some((c) => c.state !== "off");
  if (!anyOn && !job) return null;

  return <StatusChipRow chips={chips} ariaLabel={t("pipeline.aria")} />;
}
