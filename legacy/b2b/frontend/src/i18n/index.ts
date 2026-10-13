import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { DEFAULT_LOCALE, i18nResources } from './locales';

/**
 * Ресурсы и язык по умолчанию берутся из реестра `locales.ts` — добавление языка
 * (включая скрипт-варианты `uz-Latn`/`uz-Cyrl`) не требует правок здесь (L3).
 */
i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: i18nResources,
    fallbackLng: DEFAULT_LOCALE,
    // Коды со скриптом (`uz-Latn`) не должны схлопываться до языка: иначе выбор скрипта
    // терялся бы при перезагрузке. `ru-RU` из браузера при этом всё равно найдёт `ru`
    // через список поддерживаемых локалей.
    supportedLngs: Object.keys(i18nResources),
    nonExplicitSupportedLngs: true,
    interpolation: {
      escapeValue: false,
    },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
    },
  });

export default i18n;
