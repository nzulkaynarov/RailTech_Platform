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

export const calculateVAT = (subtotal: string | number, vatRate: string | number): string => {
  const rate = toDecimal(vatRate).div(100);
  return toDecimal(subtotal).mul(rate).toString();
};
