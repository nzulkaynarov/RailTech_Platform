import { create } from 'zustand';
import { systemApi } from '@/api/systemApi';
import { toDecimal, formatMoney } from '@/utils/decimal';

export type Currency = 'USD' | 'UZS';

interface CurrencyState {
  currency: Currency;
  /** Курс USD→UZS из справочника курсов ERP (ЦБ РУз); `null` — курса нет, пересчёта в USD нет. */
  rate: number | null;
  rateLoaded: boolean;
  /** Курса нет (не загрузился или в справочнике нет свежего): суммы остаются в сумах, USD недоступен. */
  rateUnavailable: boolean;
  /** Не раньше этого момента (мс) неявный `loadRate` снова пойдёт в сеть; 0 — пауза не идёт. */
  rateRetryAt: number;
  /** Сколько загрузок подряд не дали курса: от этого растёт пауза. */
  rateFailures: number;
  setCurrency: (currency: Currency) => void;
  /** `force` — явное действие (вход, кнопка): пауза между повторами его не держит. */
  loadRate: (options?: { force?: boolean }) => Promise<void>;
  convert: (amountUZS: number) => number;
  format: (amountUZS: number) => string;
}

// Amounts across the app are canonical UZS: the cost engine converts every quote line
// (USD/EUR/…) to UZS via a frozen FX rate, so what reaches this store is already UZS.
// `convert` DIVIDES by the rate for a USD view; `format` renders via the shared
// currency-aware formatMoney (same as the КП builder + PDF) so money reads consistently.
//
// Курс один — `finance.services.fx` на бэкенде, приходит в `system-settings` только на чтение
// (FIX-41, F-12). Резервного значения в коде нет: выдумать курс значит показать выдуманные суммы
// (раньше DEFAULT_RATE = 12650 молча пересчитывал показываемые суммы). Нет курса — суммы остаются
// в сумах, переключатель USD недоступен.
//
// This fixed the critical bug where a UZS КП was shown to the client as "$141,120,000" (the old
// code assumed USD input → "$" on the raw UZS number, or ×rate in UZS mode → 1.76 trillion).
// `convert`/`format` are rebuilt on every currency/rate change so their identity changes —
// components that select `s.format` re-render, making the toggle live.
const usdRate = (currency: Currency, rate: number | null): number | null =>
  currency === 'USD' && rate !== null && rate > 0 ? rate : null;

const buildConvert = (currency: Currency, rate: number | null) => (amountUZS: number): number => {
  const divisor = usdRate(currency, rate);
  return divisor === null ? amountUZS : toDecimal(amountUZS).div(divisor).toNumber();
};

const buildFormat = (currency: Currency, rate: number | null) => (amountUZS: number): string => {
  const divisor = usdRate(currency, rate);
  return divisor === null
    ? formatMoney(amountUZS, 'UZS')
    : formatMoney(toDecimal(amountUZS).div(divisor).toNumber(), 'USD');
};

// Повтор загрузки, пока курса нет (FIX-54, F-15): один запрос в полёте и пауза 30 с, дальше вдвое, не больше 10 мин.
// Неявные вызовы (эффекты, перерисовки) в паузе молчат; явное действие — `loadRate({ force: true })`.
const RETRY_BASE_MS = 30_000;
const RETRY_MAX_MS = 600_000;
const retryDelay = (failures: number): number => Math.min(RETRY_BASE_MS * 2 ** (failures - 1), RETRY_MAX_MS);

let inFlight: Promise<void> | null = null;

export const useCurrencyStore = create<CurrencyState>((set, get) => ({
  // National currency by default — КП / deals / contracts / invoices are denominated in UZS.
  currency: 'UZS',
  rate: null,
  rateLoaded: false,
  rateUnavailable: false,
  rateRetryAt: 0,
  rateFailures: 0,

  convert: buildConvert('UZS', null),
  format: buildFormat('UZS', null),

  setCurrency: (requested: Currency) => {
    const { rate } = get();
    // Без курса USD включить нельзя — остаёмся в сумах.
    const currency: Currency = requested === 'USD' && !(rate !== null && rate > 0) ? 'UZS' : requested;
    set({ currency, convert: buildConvert(currency, rate), format: buildFormat(currency, rate) });
  },

  loadRate: async ({ force = false } = {}) => {
    if (get().rateLoaded) return;
    if (inFlight) return inFlight;
    if (!force && Date.now() < get().rateRetryAt) return;
    const failed = () => {
      const rateFailures = get().rateFailures + 1;
      return { rateFailures, rateRetryAt: Date.now() + retryDelay(rateFailures) };
    };
    inFlight = (async () => {
      try {
        const settings = await systemApi.getSettings();
        const rate =
          settings.exchange_rate_usd_uzs == null ? null : toDecimal(settings.exchange_rate_usd_uzs).toNumber();
        const usable = rate !== null && rate > 0 ? rate : null;
        const currency: Currency = usable === null ? 'UZS' : get().currency;
        set({
          rate: usable,
          // Курса нет — не «защёлкиваем» загрузку: повторится по явному действию или после паузы.
          rateLoaded: usable !== null,
          rateUnavailable: usable === null,
          currency,
          convert: buildConvert(currency, usable),
          format: buildFormat(currency, usable),
          ...(usable === null ? failed() : { rateFailures: 0, rateRetryAt: 0 }),
        });
      } catch {
        // Курс не приехал — попытка повторится, а пока суммы честно остаются в сумах и USD недоступен:
        // пересчитывать показываемые суммы по выдуманному курсу нельзя (аудит UI, U2; аудит FIX-41).
        const currency: Currency = 'UZS';
        set({
          rate: null,
          rateUnavailable: true,
          currency,
          convert: buildConvert(currency, null),
          format: buildFormat(currency, null),
          ...failed(),
        });
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  },
}));
