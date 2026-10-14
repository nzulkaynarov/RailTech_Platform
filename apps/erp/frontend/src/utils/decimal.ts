import Decimal from 'decimal.js';
import i18n from '@/i18n';
import { localeFor } from '@/i18n/locales';

/** Региональный формат активного языка интерфейса (реестр локалей — единственный источник). */
function moneyFormatLocale(): string {
  return localeFor(i18n.language).formatLocale;
}


/**
 * ERP Financial Utility
 * Ensures all calculations follow strict decimal precision.
 */

export const toDecimal = (value: string | number | undefined | null): Decimal => {
  if (value === undefined || value === null || value === '') return new Decimal(0);
  try {
    return new Decimal(value);
  } catch {
    return new Decimal(0);
  }
};

export const formatMoney = (value: string | number | undefined | null, currency = 'USD'): string => {
  const amount = toDecimal(value).toNumber();
  // Guard against empty/malformed currency codes (e.g. a КП item with an unset
  // frozen_currency). Intl.NumberFormat throws RangeError "currency is not a
  // well-formed currency code" for anything that isn't an ISO-4217 3-letter code —
  // the default param only covers `undefined`, NOT `''`. Fall back to USD.
  const code = (typeof currency === 'string' ? currency : '').trim().toUpperCase();
  const safeCode = /^[A-Z]{3}$/.test(code) ? code : 'USD';
  // L3: региональный формат берётся из реестра локалей по языку ИНТЕРФЕЙСА, а не из
  // литерала 'uz-UZ' — иначе группировка разрядов и положение символа валюты никогда не
  // следовали за языком. Русский интерфейс в Узбекистане при этом остаётся в узбекистанском
  // формате: `formatLocale` в реестре отделён от кода языка ровно для этого.
  return new Intl.NumberFormat(moneyFormatLocale(), {
    style: 'currency',
    currency: safeCode,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
};

export const calculateLineTotal = (price: string | number, quantity: number): string => {
  return toDecimal(price).mul(quantity).toString();
};

/** Exact sum of money values (avoids float drift). Returns a JS number for display. */
export const sumMoney = (values: Array<string | number | undefined | null>): number =>
  values.reduce<Decimal>((acc, v) => acc.plus(toDecimal(v)), new Decimal(0)).toNumber();

/** Exact line total (price × quantity) as a JS number for aggregation. */
export const lineTotal = (price: string | number | undefined | null, quantity: number): number =>
  toDecimal(price).mul(quantity).toNumber();

export const calculateVAT = (subtotal: string | number, vatRate: string | number): string => {
  const rate = toDecimal(vatRate).div(100);
  return toDecimal(subtotal).mul(rate).toString();
};
