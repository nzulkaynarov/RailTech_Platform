import { enUS, ru, type Locale as DateFnsLocale } from 'date-fns/locale';

import enTranslation from './locales/en.json';
import ruTranslation from './locales/ru.json';

/**
 * Реестр локалей — ЕДИНСТВЕННЫЙ источник правды (L3, spec-bilingual-ru-en §5).
 *
 * Ни переключатель, ни форматирование, ни детектор языка не должны знать, сколько языков в
 * системе: раньше «ровно два» было зашито в трёх местах (тумблер RU/EN, тернарник локали
 * date-fns, `Intl.NumberFormat('uz-UZ')`), и третий язык потребовал бы править каждое.
 *
 * Готовность к узбекскому (решение владельца 02-08): коды — BCP 47, поэтому скрипт-варианты
 * `uz-Latn` / `uz-Cyrl` добавляются СТРОКОЙ в этот массив. Django понимает те же коды как
 * `uz_Latn`/`uz_Cyrl`, а CLDR содержит готовые правила транслитерации между скриптами —
 * значит узбекский переводится ОДИН раз, второй скрипт получается конвертацией.
 */
export interface LocaleDefinition {
  /** Код BCP 47: `ru`, `en`, в будущем `uz-Latn` / `uz-Cyrl`. */
  code: string;
  /** Подпись в переключателе — на СВОЁМ языке (канон: «Русский», «English», «Oʻzbekcha»). */
  nativeName: string;
  /** Короткая метка для компактного переключателя. */
  shortLabel: string;
  /** Ресурс переводов i18next. */
  translation: Record<string, unknown>;
  /**
   * Локаль date-fns для относительных дат. Для нового языка без пакета date-fns
   * оставляем undefined — форматирование мягко падает на локаль по умолчанию.
   */
  dateFns?: DateFnsLocale;
  /**
   * Локаль форматирования чисел/дат для `Intl.*`. Обычно совпадает с `code`; отличается
   * там, где интерфейсный язык и региональные форматы расходятся (RU-интерфейс в
   * Узбекистане: суммы и даты остаются в узбекистанском формате).
   */
  formatLocale: string;
}

export const LOCALES: LocaleDefinition[] = [
  {
    code: 'ru',
    nativeName: 'Русский',
    shortLabel: 'РУ',
    translation: ruTranslation,
    dateFns: ru,
    formatLocale: 'ru-UZ',
  },
  {
    code: 'en',
    nativeName: 'English',
    shortLabel: 'EN',
    translation: enTranslation,
    dateFns: enUS,
    formatLocale: 'en-US',
  },
];

export const DEFAULT_LOCALE = 'ru';

/** Ресурсы для i18next: `{ ru: { translation }, en: { translation } }`. */
export const i18nResources = Object.fromEntries(
  LOCALES.map((locale) => [locale.code, { translation: locale.translation }]),
);

/** Определение локали по коду i18next; неизвестный код → локаль по умолчанию. */
export function localeFor(code: string | undefined): LocaleDefinition {
  if (code) {
    const exact = LOCALES.find((locale) => locale.code === code);
    if (exact) return exact;
    // `ru-RU` → `ru`; для скрипт-вариантов (`uz-Latn-UZ` → `uz-Latn`) сначала пробуем
    // две первые части, и только потом язык целиком.
    const parts = code.split('-');
    const withScript = parts.slice(0, 2).join('-');
    const byScript = LOCALES.find((locale) => locale.code === withScript);
    if (byScript) return byScript;
    const byLanguage = LOCALES.find((locale) => locale.code.split('-')[0] === parts[0]);
    if (byLanguage) return byLanguage;
  }
  return LOCALES.find((locale) => locale.code === DEFAULT_LOCALE) ?? LOCALES[0];
}
