import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./en/common.json";
import enModules from "./en/modules.json";
import enShell from "./en/shell.json";
import ruCommon from "./ru/common.json";
import ruModules from "./ru/modules.json";
import ruShell from "./ru/shell.json";
import uzCommon from "./uz/common.json";
import uzModules from "./uz/modules.json";
import uzShell from "./uz/shell.json";

export const LANGUAGES = ["ru", "uz", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export const resources = {
  ru: { common: ruCommon, shell: ruShell, modules: ruModules },
  uz: { common: uzCommon, shell: uzShell, modules: uzModules },
  en: { common: enCommon, shell: enShell, modules: enModules },
} as const;

export const LANGUAGE_STORAGE_KEY = "rt-pf-lang";

function storedLanguage(): Language {
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (value && (LANGUAGES as readonly string[]).includes(value)) return value as Language;
  } catch {
    // Хранилище недоступно — берём язык по умолчанию.
  }
  return "ru";
}

/** Запоминает язык для экрана входа (до того, как профиль сотрудника известен); язык профиля приходит из `Me.language`. */
export function rememberLanguage(language: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Не критично: без хранилища экран входа откроется на русском.
  }
}

/** ru — язык по умолчанию (SPEC-v3 §8); uz — латиница. Пространства имён: common, shell (каркас и вход), modules (меню и заглушки). */
void i18n.use(initReactI18next).init({
  resources,
  lng: storedLanguage(),
  fallbackLng: "ru",
  defaultNS: "common",
  ns: ["common", "shell", "modules"],
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

export default i18n;
