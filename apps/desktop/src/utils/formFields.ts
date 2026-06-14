import type { FieldExtractionDetail, FormRecord } from "../api/client";

export function displayFields(form: FormRecord): Record<string, string> {
  const out: Record<string, string> = {};
  const corrected = form.corrected || {};
  const validated = form.validated || {};
  const extracted = form.extracted || {};
  const keys = new Set([
    ...Object.keys(corrected),
    ...Object.keys(validated),
    ...Object.keys(extracted),
  ]);
  for (const k of keys) {
    const c = corrected[k];
    const v = validated[k];
    const e = extracted[k];
    if (c != null && c !== "") {
      out[k] = String(c);
    } else if (v != null && v !== "") {
      out[k] = String(v);
    } else if (e && typeof e === "object" && "text" in e) {
      out[k] = String((e as FieldExtractionDetail).text);
    }
  }
  return out;
}
