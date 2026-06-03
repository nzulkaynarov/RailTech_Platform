import { create } from 'zustand';
import { systemApi } from '@/api/systemApi';
import { toDecimal } from '@/utils/decimal';

export type Currency = 'USD' | 'UZS';

interface CurrencyState {
  currency: Currency;
  rate: number;
  rateLoaded: boolean;
  setCurrency: (currency: Currency) => void;
  loadRate: () => Promise<void>;
  convert: (amountUSD: number) => number;
  format: (amountUSD: number) => string;
}

export const useCurrencyStore = create<CurrencyState>((set, get) => ({
  currency: 'USD',
  rate: 12650,
  rateLoaded: false,

  setCurrency: (currency: Currency) => set({ currency }),

  loadRate: async () => {
    if (get().rateLoaded) return;
    try {
      const settings = await systemApi.getSettings();
      const rate = toDecimal(settings.exchange_rate_usd_uzs).toNumber();
      if (rate > 0) {
        set({ rate, rateLoaded: true });
      }
    } catch {
      // Keep fallback rate on error — will retry on next call
    }
  },

  convert: (amountUSD: number): number => {
    const { currency, rate } = get();
    return currency === 'USD' ? amountUSD : toDecimal(amountUSD).mul(rate).toNumber();
  },

  format: (amountUSD: number): string => {
    const { currency, rate } = get();
    if (currency === 'USD') {
      return '$' + amountUSD.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    const amountUZS = toDecimal(amountUSD).mul(rate).toNumber();
    return amountUZS.toLocaleString('ru-RU') + ' сум';
  },
}));
