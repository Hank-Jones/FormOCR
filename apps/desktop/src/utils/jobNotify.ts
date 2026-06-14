import type { Job } from "../api/client";

export type NotifyLabels = {
  titleFailed: string;
  titleComplete: string;
  bodyFailed: (id: number) => string;
  bodyComplete: (id: number, summary: string) => string;
  jobSummary: (n: number, total: number) => string;
};

function jobSummary(job: Job, labels: NotifyLabels): string {
  const n = job.processed_count ?? 0;
  const total = job.total_count ?? 0;
  if (total > 0) return labels.jobSummary(n, total);
  return `job #${job.id}`;
}

/** Desktop notification when processing finishes (other tab or another app). */
export async function notifyJobFinished(job: Job, labels: NotifyLabels): Promise<void> {
  const failed = job.status === "failed";
  const title = failed ? labels.titleFailed : labels.titleComplete;
  const summary = jobSummary(job, labels);
  const body = failed
    ? labels.bodyFailed(job.id)
    : labels.bodyComplete(job.id, summary);

  try {
    const { isPermissionGranted, requestPermission, sendNotification } = await import(
      "@tauri-apps/plugin-notification"
    );
    let granted = await isPermissionGranted();
    if (!granted) {
      const perm = await requestPermission();
      granted = perm === "granted";
    }
    if (granted) {
      await sendNotification({ title, body });
      return;
    }
  } catch {
    /* Not in Tauri (e.g. Vite-only dev) — fall through */
  }

  if (typeof window !== "undefined" && "Notification" in window) {
    if (Notification.permission === "default") {
      await Notification.requestPermission();
    }
    if (Notification.permission === "granted") {
      new Notification(title, { body, tag: `formocr-job-${job.id}` });
    }
  }
}
