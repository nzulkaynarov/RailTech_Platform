import { create } from 'zustand';

export type Currency = 'USD' | 'UZS';

interface CurrencyState {
  currency: Currency;
  rate: number;
  setCurrency: (currency: Currency) => void;
  convert: (amountUSD: number) => number;
  format: (amountUSD: number) => string;
}

export const useCurrencyStore = create<CurrencyState>((set, get) => ({
  currency: 'USD',
  rate: 12650,

  setCurrency: (currency: Currency) => set({ currency }),

  convert: (amountUSD: number): number => {
    const { currency, rate } = get();
    return currency === 'USD' ? amountUSD : amountUSD * rate;
  },

  format: (amountUSD: number): string => {
    const { currency, rate } = get();
    if (currency === 'USD') {
      return '$' + amountUSD.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    const amountUZS = amountUSD * rate;
    return amountUZS.toLocaleString('ru-RU') + ' сум';
  },
}));
