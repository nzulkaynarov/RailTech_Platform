import i18n from '@/i18n';
import { localeFor } from '@/i18n/locales';

/**
 * Форматирование дат, чисел и денег по языку ИНТЕРФЕЙСА (L3, spec-bilingual-ru-en §5).
 *
 * До этого 58 вызовов `toLocaleDateString()` шли без локали (то есть по локали браузера, а не
 * интерфейса), а `formatMoney` был прибит к литералу `'uz-UZ'` — суммы и даты не следовали за
 * языком вообще. Здесь один вход: локаль берётся из реестра, а не угадывается на месте.
 *
 * Региональный формат намеренно отделён от языка (`formatLocale`): русский интерфейс в
 * Узбекистане должен печатать узбекистанские форматы, а не российские.
 */
function activeFormatLocale(): string {
  return localeFor(i18n.language).formatLocale;
}

/** Дата: `07.12.2026` / `12/7/2026` — по локали интерфейса. */
export function formatDate(value: string | number | Date | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (value === null || value === undefined || value === '') return '—';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(activeFormatLocale(), options);
}

/** Дата и время — для журналов и таймлайнов. */
export function formatDateTime(value: string | number | Date | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (value === null || value === undefined || value === '') return '—';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(activeFormatLocale(), options);
}

/** Число с разделителями разрядов по локали интерфейса. */
export function formatNumber(value: number | string | null | undefined, options?: Intl.NumberFormatOptions): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(num)) return '—';
  return new Intl.NumberFormat(activeFormatLocale(), options).format(num);
}

/** Локаль date-fns активного языка — для относительных дат («3 минуты назад»). */
export function activeDateFnsLocale() {
  return localeFor(i18n.language).dateFns;
}
