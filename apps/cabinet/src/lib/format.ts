import i18n from '@/i18n';
import { localeFor } from '@/i18n/locales';
import type { Money } from '@/api/portal';

/**
 * Форматирование денег, чисел и дат — одна точка входа (CLAUDE.md §5), по образцу B2B `lib/formatLocale.ts`.
 *
 * - Локаль — `formatLocale` из реестра языков (`ru-UZ`, `uz-Latn-UZ`, `en-US`): русский интерфейс в
 *   Узбекистане печатает узбекистанские форматы. Явный `language` — для тестов и подписей вне React.
 * - Деньги — строка `^-?\d+\.\d{2}$` и код валюты из API (CONTRACTS §0). В `Intl` уходит сама строка —
 *   без потери точности на больших суммах; нулевые копейки не печатаются, ненулевые — всегда две цифры.
 * - Даты: `date-time` из API показывается в поясе Asia/Tashkent; `date` (календарный день без пояса) —
 *   как есть, без сдвига на часовой пояс браузера.
 */
export const BUSINESS_TIME_ZONE = 'Asia/Tashkent';
const EMPTY = '—';
const AMOUNT_RE = /^(-?)(\d+)\.(\d{2})$/;
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function formatLocaleOf(language?: string): string {
  return localeFor(language ?? i18n.resolvedLanguage ?? i18n.language).formatLocale;
}

/** Строковая сумма для `Intl` (ES2023 принимает строку как точное десятичное; старые движки — как Number). */
type NumberFormatInput = Parameters<Intl.NumberFormat['format']>[0];

export function formatMoney(money: Money | null | undefined, language?: string): string {
  if (!money || !AMOUNT_RE.test(money.amount)) return EMPTY;
  const hasCents = !money.amount.endsWith('.00');
  try {
    return new Intl.NumberFormat(formatLocaleOf(language), {
      style: 'currency',
      currency: money.currency,
      minimumFractionDigits: hasCents ? 2 : 0,
      maximumFractionDigits: 2,
    }).format(money.amount as unknown as NumberFormatInput);
  } catch {
    // Неизвестный код валюты — число и код как есть.
    return `${formatDecimal(money.amount, language)} ${money.currency}`;
  }
}

/** Количество/десятичная строка из API (`"200"`, `"12.5"`) — с разделителями по локали. */
export function formatDecimal(value: string | number | null | undefined, language?: string): string {
  if (value === null || value === undefined || value === '') return EMPTY;
  const text = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  const fraction = text.split('.')[1]?.length ?? 0;
  return new Intl.NumberFormat(formatLocaleOf(language), {
    maximumFractionDigits: Math.min(fraction, 6),
  }).format(text as unknown as NumberFormatInput);
}

/** «200 шт» — количество и единица строки; без количества — прочерк. */
export function formatQuantity(quantity: string | null | undefined, unit: string | null | undefined, language?: string): string {
  if (quantity === null || quantity === undefined || quantity === '') return EMPTY;
  const number = formatDecimal(quantity, language);
  return unit ? `${number} ${unit}` : number;
}

/** Календарная дата `YYYY-MM-DD` (поле `format: date`): «25 окт. 2026 г.», без сдвига по поясу. */
export function formatDate(value: string | null | undefined, language?: string): string {
  if (!value) return EMPTY;
  const match = DATE_ONLY_RE.exec(value);
  if (match) {
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return new Intl.DateTimeFormat(formatLocaleOf(language), { ...DATE_STYLE, timeZone: 'UTC' }).format(date);
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return EMPTY;
  return new Intl.DateTimeFormat(formatLocaleOf(language), { ...DATE_STYLE, timeZone: BUSINESS_TIME_ZONE }).format(date);
}

/** Момент `date-time` (ISO с поясом) — дата и время в Asia/Tashkent. */
export function formatDateTime(value: string | null | undefined, language?: string): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return EMPTY;
  return new Intl.DateTimeFormat(formatLocaleOf(language), {
    ...DATE_STYLE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: BUSINESS_TIME_ZONE,
  }).format(date);
}

const DATE_STYLE: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' };

/** Размер файла: «180 КБ» по-русски, «180 kB» по-английски — единицы через `Intl` (unit). */
export function formatFileSize(bytes: number | null | undefined, language?: string): string {
  if (bytes === null || bytes === undefined || bytes < 0) return EMPTY;
  const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte'] as const;
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return new Intl.NumberFormat(formatLocaleOf(language), {
    style: 'unit',
    unit: units[index],
    unitDisplay: 'short',
    maximumFractionDigits: index === 0 || value >= 10 ? 0 : 1,
  }).format(value);
}

// --- календарь Ташкента и сроки ---------------------------------------------------------------

/** Сегодняшний календарный день в Asia/Tashkent как `YYYY-MM-DD` (для сравнения со сроками из API). */
export function businessToday(now: number = Date.now()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: BUSINESS_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(now));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** Сколько дней от `from` до `to` (оба `YYYY-MM-DD`); отрицательное — `to` раньше `from`. */
export function daysBetween(from: string, to: string): number {
  const toUtc = (value: string) => {
    const match = DATE_ONLY_RE.exec(value);
    return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : Number.NaN;
  };
  return Math.round((toUtc(to) - toUtc(from)) / 86_400_000);
}

// --- арифметика сумм без плавающей точки --------------------------------------------------------

/** `"13750000.50"` → 1375000050n (копейки); не сумма — `null`. */
export function amountToCents(amount: string): bigint | null {
  const match = AMOUNT_RE.exec(amount);
  if (!match) return null;
  const cents = BigInt(match[2]) * 100n + BigInt(match[3]);
  return match[1] ? -cents : cents;
}

/** 1375000050n → `"13750000.50"`. */
export function centsToAmount(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const rest = (abs % 100n).toString().padStart(2, '0');
  return `${negative ? '-' : ''}${whole}.${rest}`;
}

/** Разность двух сумм одной валюты (`a − b`); разные валюты или не суммы — `null`. */
export function subtractMoney(a: Money, b: Money): Money | null {
  if (a.currency !== b.currency) return null;
  const left = amountToCents(a.amount);
  const right = amountToCents(b.amount);
  if (left === null || right === null) return null;
  return { amount: centsToAmount(left - right), currency: a.currency };
}

/** Сумма по валютам: `[{UZS 10}, {USD 5}, {UZS 2}]` → `[{UZS 12}, {USD 5}]` в порядке появления. */
export function sumByCurrency(items: Money[]): Money[] {
  const totals = new Map<string, bigint>();
  for (const item of items) {
    const cents = amountToCents(item.amount);
    if (cents === null) continue;
    totals.set(item.currency, (totals.get(item.currency) ?? 0n) + cents);
  }
  return Array.from(totals, ([currency, cents]) => ({ amount: centsToAmount(cents), currency }));
}
