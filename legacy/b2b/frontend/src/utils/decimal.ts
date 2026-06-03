import Decimal from 'decimal.js';

/**
 * RailTech Financial Utility
 * Ensures all B2B calculations follow strict decimal precision.
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
  return new Intl.NumberFormat('uz-UZ', {
    style: 'currency',
    currency: currency,
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
