/**
 * Суммы и числа (SPEC-v3 §5.3, 03-frontend.md §8): `1 234 567 сум`, пробелы разрядов — неразрывные, чтобы сумма не
 * рвалась по строкам. Разбор — без потери точности: строка `"134400000.00"` от BFF не проходит через `number`.
 */
export const NBSP = " ";
export const MINUS = "−";
const EM_DASH = "—";

export type NumberInput = number | string | null | undefined;

/** Слово валюты по языку интерфейса: «сум» (ru), «so‘m» (uz), код ISO для en. */
export const CURRENCY: Record<string, string> = { ru: "сум", uz: "so‘m", en: "UZS" };

function baseLanguage(language: string | undefined): string {
  const base = (language ?? "ru").slice(0, 2).toLowerCase();
  return base in CURRENCY ? base : "ru";
}

/** Десятичное число как целое со шкалой: 12.50 → { digits: 1250n, scale: 2 }. */
interface Decimal {
  negative: boolean;
  digits: bigint;
  scale: number;
}

function parseDecimal(value: number | string): Decimal | null {
  let text: string;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || Math.abs(value) >= 1e21) return null;
    text = value.toFixed(6);
  } else {
    text = value.trim();
  }
  const match = /^([+-])?(\d+)(?:[.,](\d+))?$/.exec(text);
  if (!match) return null;
  const frac = match[3] ?? "";
  return {
    negative: match[1] === "-",
    digits: BigInt(`${match[2] ?? "0"}${frac}`),
    scale: frac.length,
  };
}

/** Округление «половина вверх» до `places` знаков после запятой. */
function roundTo(decimal: Decimal, places: number): Decimal {
  if (decimal.scale === places) return decimal;
  if (decimal.scale < places) {
    return {
      ...decimal,
      digits: decimal.digits * 10n ** BigInt(places - decimal.scale),
      scale: places,
    };
  }
  const divisor = 10n ** BigInt(decimal.scale - places);
  let quotient = decimal.digits / divisor;
  if ((decimal.digits % divisor) * 2n >= divisor) quotient += 1n;
  return { ...decimal, digits: quotient, scale: places };
}

export interface NumberFormatOptions {
  language?: string;
  /**
   * Знаков после запятой: число — ровно столько; `"auto"` (по умолчанию) — округление до сотых и без дробной части,
   * если она нулевая (`134 400 000`, но `1 200,50`).
   */
  fractionDigits?: number | "auto";
}

/** `1 234 567` (ru, uz — неразрывные пробелы, запятая) или `1,234,567` (en). Нечисловое → «—». */
export function formatNumber(value: NumberInput, options: NumberFormatOptions = {}): string {
  if (value === null || value === undefined || value === "") return EM_DASH;
  const parsed = parseDecimal(value);
  if (!parsed) return EM_DASH;
  const { fractionDigits = "auto" } = options;
  const rounded = roundTo(parsed, fractionDigits === "auto" ? 2 : Math.max(0, fractionDigits));
  const unit = 10n ** BigInt(rounded.scale);
  const integer = (rounded.digits / unit).toString();
  let fraction =
    rounded.scale > 0 ? (rounded.digits % unit).toString().padStart(rounded.scale, "0") : "";
  if (fractionDigits === "auto" && /^0*$/.test(fraction)) fraction = "";
  const english = baseLanguage(options.language) === "en";
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, english ? "," : NBSP);
  const isZero = rounded.digits === 0n;
  const sign = rounded.negative && !isZero ? MINUS : "";
  return `${sign}${grouped}${fraction ? (english ? "." : ",") + fraction : ""}`;
}

export interface MoneyFormatOptions extends NumberFormatOptions {
  /** Своя подпись валюты; `false` — только число (колонка таблицы с «Сумма, сум» в заголовке) */
  currency?: string | false;
}

/** `1 234 567 сум`; пустое значение → «—». */
export function formatMoney(value: NumberInput, options: MoneyFormatOptions = {}): string {
  const number = formatNumber(value, options);
  if (number === EM_DASH || options.currency === false) return number;
  return `${number}${NBSP}${options.currency ?? CURRENCY[baseLanguage(options.language)] ?? "сум"}`;
}

/** `30,0 %` — процент с неразрывным пробелом; по умолчанию один знак после запятой. */
export function formatPercent(value: NumberInput, options: NumberFormatOptions = {}): string {
  const number = formatNumber(value, { fractionDigits: 1, ...options });
  return number === EM_DASH ? number : `${number}${NBSP}%`;
}
