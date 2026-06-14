import { invoke } from "@tauri-apps/api/core";

let cachedBase: string | null = null;

export function clearApiBaseCache(): void {
  cachedBase = null;
}

const API_RETRY_ATTEMPTS = 40;
const API_RETRY_MS = 400;

export type ApiFetchOptions = {
  /** Max attempts including the first try (default 40). Use 1 for polling endpoints. */
  retries?: number;
  retryMs?: number;
};

function isTransientFetchError(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  const msg = err instanceof Error ? err.message : String(err);
  return /failed to fetch|network|ECONNREFUSED|connection/i.test(msg);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export async function getApiBase(): Promise<string> {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  if (import.meta.env.FORMOCR_DEV_API) {
    return import.meta.env.FORMOCR_DEV_API;
  }
  if (cachedBase) return cachedBase;
  try {
    cachedBase = await invoke<string>("get_api_base_url");
    return cachedBase;
  } catch {
    cachedBase = "http://127.0.0.1:8765";
    return cachedBase;
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  opts?: ApiFetchOptions
): Promise<T> {
  const maxAttempts = opts?.retries ?? API_RETRY_ATTEMPTS;
  const retryMs = opts?.retryMs ?? API_RETRY_MS;
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const base = await getApiBase();
      const res = await fetch(`${base}${path}`, init);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        return res.json() as Promise<T>;
      }
      return res as unknown as T;
    } catch (err) {
      lastErr = err;
      if (!isTransientFetchError(err) || attempt >= maxAttempts - 1) {
        throw err;
      }
      await sleep(retryMs);
    }
  }
  throw lastErr;
}

export async function apiUpload<T>(
  path: string,
  formData: FormData
): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < API_RETRY_ATTEMPTS; attempt++) {
    try {
      const base = await getApiBase();
      const res = await fetch(`${base}${path}`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    } catch (err) {
      lastErr = err;
      if (!isTransientFetchError(err) || attempt >= API_RETRY_ATTEMPTS - 1) {
        throw err;
      }
      await sleep(API_RETRY_MS);
    }
  }
  throw lastErr;
}

export function imageUrl(formId: number, processed = false): Promise<string> {
  return getApiBase().then(
    (base) => `${base}/forms/${formId}/image?processed=${processed}`
  );
}

/** Fetch image bytes from API and return a blob: URL (works in Tauri WebView). */
export async function apiImageBlobUrl(path: string): Promise<string> {
  const base = await getApiBase();
  const res = await fetch(`${base}${path}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `Image HTTP ${res.status}`);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export function templateSampleImageUrl(sampleId: number): Promise<string> {
  return apiImageBlobUrl(`/templates/samples/${sampleId}/image`);
}

export interface FormType {
  id: number;
  name: string;
  version: number;
  status: string;
  anchor_keywords: string[] | null;
  field_styles?: Record<string, string[]> | null;
  created_at: string;
}

export interface TemplateSample {
  id: number;
  form_type_id: number;
  image_path: string;
  page_index: number;
  width: number | null;
  height: number | null;
  annotations?: AnnotationField[] | null;
}

export interface AnnotationField {
  key: string;
  label: string;
  field_type: FieldType;
  bbox_norm: [number, number, number, number];
  style_key?: string | null;
  allowed_values?: string[] | null;
  /** Expected handwritten lines in this box (2–20). Omit or 1 for single line. */
  line_count?: number | null;
}

export type FieldType =
  | "name"
  | "location"
  | "gender"
  | "date"
  | "string"
  | "number"
  | "phone"
  | "email"
  | "college_name"
  | "school_name"
  | "company_name"
  | "hobby"
  | "address"
  | "city"
  | "country"
  | "zip_code"
  | "id_number"
  | "age"
  | "occupation"
  | "department"
  | "title"
  | "custom";

export const FIELD_TYPE_OPTIONS: { value: FieldType; label: string }[] = [
  { value: "name", label: "Name" },
  { value: "location", label: "Location" },
  { value: "gender", label: "Gender" },
  { value: "date", label: "Date" },
  { value: "string", label: "Text / string" },
  { value: "number", label: "Number" },
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
  { value: "college_name", label: "College name" },
  { value: "school_name", label: "School name" },
  { value: "company_name", label: "Company name" },
  { value: "hobby", label: "Hobby" },
  { value: "address", label: "Address" },
  { value: "city", label: "City" },
  { value: "country", label: "Country" },
  { value: "zip_code", label: "ZIP / postal code" },
  { value: "id_number", label: "ID number" },
  { value: "age", label: "Age" },
  { value: "occupation", label: "Occupation" },
  { value: "department", label: "Department" },
  { value: "title", label: "Title / position" },
  { value: "custom", label: "Custom" },
];

export interface FieldExtractionDetail {
  text: string;
  confidence: number;
  engine?: string;
  qwen_text?: string | null;
  paddle_text?: string | null;
  tesseract_text?: string | null;
  phi3_text?: string | null;
}

export interface FormRecord {
  id: number;
  form_type_id: number | null;
  job_id: number | null;
  raw_image_path: string;
  processed_image_path: string | null;
  extracted: Record<string, FieldExtractionDetail> | null;
  validated: Record<string, string> | null;
  corrected: Record<string, string> | null;
  confidence: Record<string, number> | null;
  review_status: string;
  detection_score?: number | null;
  created_at: string;
}

export interface Job {
  id: number;
  status: string;
  form_type_id: number | null;
  total_count: number;
  processed_count: number;
  created_at: string;
  completed_at: string | null;
  phase?: string | null;
  message?: string | null;
  fields_total?: number | null;
  fields_done?: number | null;
  progress_percent?: number | null;
  ocr_lang?: string | null;
  handwriting_model?: string | null;
  ai_model?: string | null;
  ocr_engine_counts?: Record<string, number> | null;
  ai_error?: string | null;
  steps?: string[] | null;
  last_field_key?: string | null;
  last_field_engine?: string | null;
  form_ids?: number[] | null;
  current_form_id?: number | null;
  preview_raw_path?: string | null;
  preview_processed_path?: string | null;
  pipeline?: Record<string, string> | null;
}

export function jobPreviewImageUrl(jobId: number, variant: "raw" | "processed"): Promise<string> {
  return apiImageBlobUrl(`/process/jobs/${jobId}/preview-image?variant=${variant}`);
}

export interface FormFieldMeta {
  key: string;
  label: string;
  field_type: string;
  line_count?: number | null;
  bbox_norm?: [number, number, number, number] | null;
}

export function formFieldCropUrl(formId: number, fieldKey: string): Promise<string> {
  return apiImageBlobUrl(
    `/forms/${formId}/fields/${encodeURIComponent(fieldKey)}/crop`
  );
}

export interface Health {
  status: string;
  api: boolean;
  ocr_ready: boolean;
  ocr_warming?: boolean | null;
  ollama_ready: boolean;
  ollama_model_present: boolean;
  handwriting_model_present?: boolean | null;
  handwriting_ollama_model?: string | null;
  data_dir: string;
  paddle_models_dir?: string | null;
  ocr_error?: string | null;
  ollama_model?: string | null;
  api_build?: string | null;
  ollama_host?: string | null;
  ollama_on_gpu?: boolean | null;
  ollama_vram_mb?: number | null;
  ollama_gpu_summary?: string | null;
}

/** Fast liveness probe — no retry storm while the engine is starting. */
export function apiFetchLive(): Promise<Health> {
  return apiFetch<Health>("/health/live", undefined, { retries: 2, retryMs: 300 });
}

/** Full health (Ollama/GPU) — poll sparingly; can be slow while vision warms. */
export function apiFetchHealth(): Promise<Health> {
  return apiFetch<Health>("/health", undefined, { retries: 1, retryMs: 0 });
}
