import enTranslation from './locales/en.json';
import ruTranslation from './locales/ru.json';
import uzTranslation from './locales/uz.json';

/**
 * Реестр локалей — единственный источник правды (как в ERP, L3). Переключатель, детектор языка и
 * форматирование не знают, сколько языков в системе. Коды совпадают с `Language` контракта
 * (`ru | uz | en`, erp-portal.yaml): язык контакта из `GET /me` подставляется без преобразований.
 * `uz` — узбекская латиница (новый словарь, M2-CAB-01).
 */
export interface LocaleDefinition {
  /** Код из контракта `Language`. */
  code: 'ru' | 'uz' | 'en';
  /** Подпись в переключателе — на своём языке. */
  nativeName: string;
  shortLabel: string;
  translation: Record<string, unknown>;
  /** Локаль для `Intl.*`: в Узбекистане суммы и даты в узбекистанском формате при любом языке. */
  formatLocale: string;
}

export const LOCALES: LocaleDefinition[] = [
  { code: 'ru', nativeName: 'Русский', shortLabel: 'РУ', translation: ruTranslation, formatLocale: 'ru-UZ' },
  { code: 'uz', nativeName: 'Oʻzbekcha', shortLabel: 'UZ', translation: uzTranslation, formatLocale: 'uz-Latn-UZ' },
  { code: 'en', nativeName: 'English', shortLabel: 'EN', translation: enTranslation, formatLocale: 'en-US' },
];

export const DEFAULT_LOCALE: LocaleDefinition['code'] = 'ru';

/** Ключ localStorage с явным выбором языка; пока его нет — язык берётся из `/me` или Telegram. */
export const LANGUAGE_STORAGE_KEY = 'cabinet.language';

export const i18nResources = Object.fromEntries(
  LOCALES.map((locale) => [locale.code, { translation: locale.translation }]),
);

export function isSupportedLocale(code: string | null | undefined): code is LocaleDefinition['code'] {
  return LOCALES.some((locale) => locale.code === code);
}

/** `ru-RU` → `ru`, `uz-Latn-UZ` → `uz`; неизвестный код → локаль по умолчанию. */
export function localeFor(code: string | undefined): LocaleDefinition {
  const language = code?.split('-')[0];
  return LOCALES.find((locale) => locale.code === language) ?? LOCALES[0];
}
