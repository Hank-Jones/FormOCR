import { isTauri } from "@tauri-apps/api/core";
import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { getApiBase } from "../api/client";

export type ExportFormat = "csv" | "xlsx" | "json";

export type ExportSaveOptions = {
  /** Dialog title (localized). */
  title?: string;
  /** Suggested file name, e.g. formocr_export_2026-05-27.csv */
  defaultFilename: string;
};

function defaultExportFilename(format: ExportFormat): string {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const ext = format === "json" ? "json" : format;
  return `formocr_export_${stamp}.${ext}`;
}

function formatFilters(format: ExportFormat) {
  if (format === "csv") {
    return [{ name: "CSV", extensions: ["csv"] }];
  }
  if (format === "xlsx") {
    return [{ name: "Excel", extensions: ["xlsx"] }];
  }
  return [{ name: "JSON", extensions: ["json"] }];
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 150);
}

async function fetchExportBlob(
  format: ExportFormat,
  params: URLSearchParams
): Promise<Blob> {
  const base = await getApiBase();
  const path =
    format === "json" ? `/export/json?${params}` : `/export/${format}?${params}`;
  const res = await fetch(`${base}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Export failed (${res.status})`);
  }

  if (format === "json") {
    const data = await res.json();
    return new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json;charset=utf-8",
    });
  }

  const blob = await res.blob();
  if (blob.size === 0 && format !== "csv") {
    throw new Error("No data to export for the current filters.");
  }
  return blob;
}

/** Save export via native dialog (Tauri) or browser download fallback. */
export async function saveExport(
  format: ExportFormat,
  params: URLSearchParams,
  opts?: Partial<ExportSaveOptions>
): Promise<string | null> {
  const defaultFilename = opts?.defaultFilename ?? defaultExportFilename(format);
  const blob = await fetchExportBlob(format, params);

  if (isTauri()) {
    const dest = await save({
      title: opts?.title,
      defaultPath: defaultFilename,
      filters: formatFilters(format),
    });
    if (dest === null) {
      return null;
    }
    const bytes = new Uint8Array(await blob.arrayBuffer());
    await writeFile(dest, bytes);
    return dest;
  }

  triggerBrowserDownload(blob, defaultFilename);
  return defaultFilename;
}

/** @deprecated Use saveExport */
export async function downloadExport(
  format: ExportFormat,
  params: URLSearchParams
): Promise<void> {
  await saveExport(format, params);
}
