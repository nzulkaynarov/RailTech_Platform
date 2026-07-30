import { create } from 'zustand';
import { systemApi } from '@/api/systemApi';
import { toDecimal, formatMoney } from '@/utils/decimal';

export type Currency = 'USD' | 'UZS';

interface CurrencyState {
  currency: Currency;
  rate: number;
  rateLoaded: boolean;
  /** Курс не приехал с сервера и остаётся резервным — суммы в USD приблизительны. */
  rateIsFallback: boolean;
  setCurrency: (currency: Currency) => void;
  loadRate: () => Promise<void>;
  convert: (amountUZS: number) => number;
  format: (amountUZS: number) => string;
}

// Amounts across the app are canonical UZS: the cost engine converts every quote line
// (USD/EUR/…) to UZS via a frozen FX rate, so what reaches this store is already UZS.
// `convert` DIVIDES by the rate for a USD view; `format` renders via the shared
// currency-aware formatMoney (same as the КП builder + PDF) so money reads consistently.
//
// This fixed the critical bug where a UZS КП was shown to the buyer as "$141,120,000"
// (the old code assumed USD input → "$" on the raw UZS number, or ×rate in UZS mode →
// 1.76 trillion). `convert`/`format` are rebuilt on every currency/rate change so their
// identity changes — components that select `s.format` re-render, making the toggle live
// (a stable function ref never triggered a re-render, so the toggle silently did nothing).
const buildConvert = (currency: Currency, rate: number) => (amountUZS: number): number =>
  currency === 'USD' && rate > 0 ? toDecimal(amountUZS).div(rate).toNumber() : amountUZS;

const buildFormat = (currency: Currency, rate: number) => (amountUZS: number): string => {
  if (currency === 'USD') {
    const amountUSD = rate > 0 ? toDecimal(amountUZS).div(rate).toNumber() : 0;
    return formatMoney(amountUSD, 'USD');
  }
  return formatMoney(amountUZS, 'UZS');
};

const DEFAULT_RATE = 12650;

export const useCurrencyStore = create<CurrencyState>((set, get) => ({
  // National currency by default — КП / deals / contracts / invoices are denominated in UZS.
  currency: 'UZS',
  rate: DEFAULT_RATE,
  rateLoaded: false,
  rateIsFallback: false,

  convert: buildConvert('UZS', DEFAULT_RATE),
  format: buildFormat('UZS', DEFAULT_RATE),

  setCurrency: (currency: Currency) =>
    set({ currency, convert: buildConvert(currency, get().rate), format: buildFormat(currency, get().rate) }),

  loadRate: async () => {
    if (get().rateLoaded) return;
    try {
      const settings = await systemApi.getSettings();
      const rate = toDecimal(settings.exchange_rate_usd_uzs).toNumber();
      if (rate > 0) {
        const currency = get().currency;
        set({
          rate,
          rateLoaded: true,
          rateIsFallback: false,
          convert: buildConvert(currency, rate),
          format: buildFormat(currency, rate),
        });
      }
    } catch {
      // Курс остаётся резервным, и попытка повторится — но молчать об этом нельзя: по нему
      // пересчитываются ПОКАЗЫВАЕМЫЕ суммы, и пользователь читал бы их как настоящие
      // (аудит UI, U2). Переключатель валюты помечает такой курс приблизительным.
      set({ rateIsFallback: true });
    }
  },
}));
