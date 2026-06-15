import { createContext } from "react";

import en from "./locales/en.json";
import zh from "./locales/zh.json";

export type Locale = "en" | "zh";

const MESSAGES: Record<Locale, Record<string, string>> = {
  en: en as Record<string, string>,
  zh: zh as Record<string, string>,
};

export type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
};

export const I18nContext = createContext<I18nContextValue | null>(null);

export function getMessage(locale: Locale, key: string): string {
  return MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;
}
