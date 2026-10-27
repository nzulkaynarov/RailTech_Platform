import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enAudit from "./en/audit.json";
import enBridge from "./en/bridge.json";
import enCalc from "./en/calc.json";
import enBus from "./en/bus.json";
import enBot from "./en/bot.json";
import enCommon from "./en/common.json";
import enCompany from "./en/company.json";
import enDictionary from "./en/dictionary.json";
import enDocuments from "./en/documents.json";
import enIntegrations from "./en/integrations.json";
import enKb from "./en/kb.json";
import enLetters from "./en/letters.json";
import enModules from "./en/modules.json";
import enProfile from "./en/profile.json";
import enShell from "./en/shell.json";
import enUi from "./en/ui.json";
import ruAudit from "./ru/audit.json";
import ruBridge from "./ru/bridge.json";
import ruCalc from "./ru/calc.json";
import ruBus from "./ru/bus.json";
import ruBot from "./ru/bot.json";
import ruCommon from "./ru/common.json";
import ruCompany from "./ru/company.json";
import ruDictionary from "./ru/dictionary.json";
import ruDocuments from "./ru/documents.json";
import ruIntegrations from "./ru/integrations.json";
import ruKb from "./ru/kb.json";
import ruLetters from "./ru/letters.json";
import ruModules from "./ru/modules.json";
import ruProfile from "./ru/profile.json";
import ruShell from "./ru/shell.json";
import ruUi from "./ru/ui.json";
import uzAudit from "./uz/audit.json";
import uzBridge from "./uz/bridge.json";
import uzCalc from "./uz/calc.json";
import uzBus from "./uz/bus.json";
import uzBot from "./uz/bot.json";
import uzCommon from "./uz/common.json";
import uzCompany from "./uz/company.json";
import uzDictionary from "./uz/dictionary.json";
import uzDocuments from "./uz/documents.json";
import uzIntegrations from "./uz/integrations.json";
import uzKb from "./uz/kb.json";
import uzLetters from "./uz/letters.json";
import uzModules from "./uz/modules.json";
import uzProfile from "./uz/profile.json";
import uzShell from "./uz/shell.json";
import uzUi from "./uz/ui.json";

export const LANGUAGES = ["ru", "uz", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export const resources = {
  ru: {
    common: ruCommon,
    audit: ruAudit,
    bridge: ruBridge,
    calc: ruCalc,
    shell: ruShell,
    modules: ruModules,
    dictionary: ruDictionary,
    documents: ruDocuments,
    integrations: ruIntegrations,
    bus: ruBus,
    kb: ruKb,
    letters: ruLetters,
    profile: ruProfile,
    bot: ruBot,
    ui: ruUi,
    company: ruCompany,
  },
  uz: {
    common: uzCommon,
    audit: uzAudit,
    bridge: uzBridge,
    calc: uzCalc,
    shell: uzShell,
    modules: uzModules,
    dictionary: uzDictionary,
    documents: uzDocuments,
    integrations: uzIntegrations,
    bus: uzBus,
    kb: uzKb,
    letters: uzLetters,
    profile: uzProfile,
    bot: uzBot,
    ui: uzUi,
    company: uzCompany,
  },
  en: {
    common: enCommon,
    audit: enAudit,
    bridge: enBridge,
    calc: enCalc,
    shell: enShell,
    modules: enModules,
    dictionary: enDictionary,
    documents: enDocuments,
    integrations: enIntegrations,
    bus: enBus,
    kb: enKb,
    letters: enLetters,
    profile: enProfile,
    bot: enBot,
    ui: enUi,
    company: enCompany,
  },
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

/** ru — язык по умолчанию (SPEC-v3 §8); uz — латиница. Пространства имён: common, shell (каркас и вход), modules (меню и заглушки), dictionary (словарь SPEC-v3 §2: стадии и статусы), ui (тексты общих компонентов), integrations (Admin · Внешние интеграции), company (Admin · Компания), kb (CRM · База знаний), bot (Admin · Настройки бота), bus (Admin · Журнал интеграций), documents (EDS · Создать документ и «Мои документы»), letters (EDS · Входящие письма и резолюция), calc (Расчёт по заявке), profile (страница /me, «Забыли пароль?»). */
void i18n.use(initReactI18next).init({
  resources,
  lng: storedLanguage(),
  fallbackLng: "ru",
  defaultNS: "common",
  ns: [
    "common",
    "shell",
    "bridge",
    "modules",
    "dictionary",
    "documents",
    "ui",
    "integrations",
    "company",
    "bus",
    "kb",
    "bot",
    "letters",
    "calc",
    "profile",
  ],
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

export default i18n;
