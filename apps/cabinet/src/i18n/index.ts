import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { getTelegramWebApp } from '@/telegram/webapp';
import { DEFAULT_LOCALE, LANGUAGE_STORAGE_KEY, i18nResources, isSupportedLocale } from './locales';

/**
 * Порядок выбора языка (CLAUDE.md §5): явный выбор в профиле (localStorage) → язык пользователя
 * Telegram в Mini App → язык браузера → `ru`. Язык контакта из `GET /me` применяется после входа
 * (`applyContactLanguage`), но не перекрывает явный выбор человека.
 */
const telegramDetector = {
  name: 'telegram',
  lookup(): string | undefined {
    const code = getTelegramWebApp()?.initDataUnsafe.user?.language_code;
    return isSupportedLocale(code) ? code : undefined;
  },
};

const detector = new LanguageDetector();
detector.addDetector(telegramDetector);

i18n
  .use(detector)
  .use(initReactI18next)
  .init({
    resources: i18nResources,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: Object.keys(i18nResources),
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'telegram', 'navigator'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
      // Кэшируем только явный выбор (`chooseLanguage`), а не угаданный язык.
      caches: [],
    },
  });

// `<html lang>` следует за языком интерфейса — для экранных дикторов и переносов.
const syncHtmlLang = (lng: string) => {
  if (typeof document !== 'undefined') document.documentElement.lang = lng.split('-')[0];
};
syncHtmlLang(i18n.resolvedLanguage ?? i18n.language ?? DEFAULT_LOCALE);
i18n.on('languageChanged', syncHtmlLang);

/** Явный выбор языка человеком — запоминается и перекрывает язык контакта и Telegram. */
export async function chooseLanguage(code: string): Promise<void> {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, code);
  } catch {
    // Приватный режим или запрет хранилища — язык меняется только на сессию.
  }
  await i18n.changeLanguage(code);
}

function explicitLanguage(): string | null {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Язык контакта из `/me`: применяется, если человек ещё не выбирал язык сам. */
export async function applyContactLanguage(code: string): Promise<void> {
  if (explicitLanguage() || !isSupportedLocale(code) || i18n.language === code) return;
  await i18n.changeLanguage(code);
}

export default i18n;
