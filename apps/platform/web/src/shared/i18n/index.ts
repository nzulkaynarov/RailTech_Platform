import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./en/common.json";
import ruCommon from "./ru/common.json";
import uzCommon from "./uz/common.json";

export const LANGUAGES = ["ru", "uz", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export const resources = {
  ru: { common: ruCommon },
  uz: { common: uzCommon },
  en: { common: enCommon },
} as const;

/** ru — язык по умолчанию (SPEC-v3 §8); uz — латиница. Пространства имён: common, позже dictionary и модули. */
void i18n.use(initReactI18next).init({
  resources,
  lng: "ru",
  fallbackLng: "ru",
  defaultNS: "common",
  ns: ["common"],
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

export default i18n;
