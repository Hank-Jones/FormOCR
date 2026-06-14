export function jobProgressPercent(job: {
  status: string;
  total_count: number;
  processed_count: number;
  phase?: string | null;
  progress_percent?: number | null;
  fields_total?: number | null;
  fields_done?: number | null;
}): number {
  if (job.status === "completed") return 100;
  if (job.status === "failed" || job.status === "cancelled") return 0;

  if (
    job.progress_percent != null &&
    Number.isFinite(job.progress_percent) &&
    job.progress_percent >= 0
  ) {
    const pct = Math.round(job.progress_percent);
    return job.status === "running" || job.status === "pending"
      ? Math.min(99, pct)
      : pct;
  }

  if (job.total_count <= 0) return 0;
  const files = job.total_count;
  let frac = job.processed_count / files;
  const ft = job.fields_total ?? 0;
  if (ft > 0 && (job.status === "running" || job.status === "pending")) {
    frac += (job.fields_done ?? 0) / ft / files;
  }
  return Math.min(99, Math.max(0, Math.round(frac * 100)));
}

export function jobProgressLabel(
  job: {
    status: string;
    total_count: number;
    processed_count: number;
    phase?: string | null;
    message?: string | null;
    fields_total?: number | null;
    fields_done?: number | null;
    progress_percent?: number | null;
  },
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  if (job.message) return job.message;
  if (job.status === "completed") return t("progress.complete");
  if (job.status === "cancelled") return t("progress.cancelled");
  if (job.status === "failed") return t("progress.failed");
  const phaseLabels: Record<string, string> = {
    preprocess: t("progress.preprocess"),
    detect: t("progress.detect"),
    ocr: t("progress.ocr"),
    ai: t("progress.ai"),
    file: t("progress.file"),
    save: t("progress.save"),
  };
  if (job.phase && phaseLabels[job.phase]) {
    if (job.phase === "ocr" && job.fields_total && job.fields_total > 0) {
      return t("progress.readingFields", {
        done: job.fields_done ?? 0,
        total: job.fields_total,
      });
    }
    return phaseLabels[job.phase];
  }
  if (job.fields_total && job.fields_total > 0) {
    return t("progress.readingFields", {
      done: job.fields_done ?? 0,
      total: job.fields_total,
    });
  }
  return t("progress.processingFiles", {
    done: job.processed_count,
    total: job.total_count,
  });
}

export default function ProgressBar({
  percent,
  label,
  indeterminate = false,
}: {
  percent: number;
  label: string;
  indeterminate?: boolean;
}) {
  const clamped = Math.min(100, Math.max(0, percent));
  const showIndeterminate = indeterminate && clamped <= 0;

  return (
    <div
      className="progress-wrap"
      role="progressbar"
      aria-valuenow={showIndeterminate ? undefined : clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="progress-label">
        <span>{label}</span>
        {!showIndeterminate && <span className="progress-pct">{clamped}%</span>}
      </div>
      <div className={`progress-track${showIndeterminate ? " progress-indeterminate" : ""}`}>
        {!showIndeterminate && (
          <div className="progress-fill" style={{ width: `${clamped}%` }} />
        )}
      </div>
    </div>
  );
}
