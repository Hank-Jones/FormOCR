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

function errorDetail(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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
    let detail = "";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        detail = parsed.detail;
      }
    } catch {
      // Fall through to the raw response text for non-JSON errors.
    }
    if (detail) throw new Error(detail);
    throw new Error(text || `Export failed (${res.status})`);
  }

  const blob = await res.blob();
  if (blob.size === 0) {
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

  if (isTauri()) {
    let dest: string | null;
    try {
      dest = await save({
        title: opts?.title,
        defaultPath: defaultFilename,
        filters: formatFilters(format),
      });
    } catch (e) {
      throw new Error(`Could not open the save dialog. ${errorDetail(e)}`);
    }
    if (dest === null) {
      return null;
    }
    const blob = await fetchExportBlob(format, params);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    try {
      await writeFile(dest, bytes);
    } catch (e) {
      throw new Error(
        `Could not save export to the selected location. Choose Documents, Downloads, Desktop, your home folder, or Temp. ${errorDetail(e)}`
      );
    }
    return dest;
  }

  const blob = await fetchExportBlob(format, params);
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
