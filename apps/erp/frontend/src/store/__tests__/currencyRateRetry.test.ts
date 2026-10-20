/**
 * Курса нет — запрос не повторяется на каждый срабатывающий эффект (FIX-54, F-15).
 *
 * Раньше пока справочник без свежего курса, `loadRate` ходил в сеть при каждом срабатывании эффекта App
 * (смена маршрута, перерисовка) — десятки одинаковых запросов `system-settings` за сессию. Теперь: один запрос
 * в полёте, повтор неявного вызова — не раньше окончания паузы (30 с, дальше вдвое, не больше 10 мин),
 * явное действие (`{ force: true }`: вход, кнопка) пробивает паузу.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useCurrencyStore } from '../currencyStore';
import { systemApi } from '@/api/systemApi';

vi.mock('@/api/systemApi', () => ({ systemApi: { getSettings: vi.fn() } }));

const getSettings = vi.mocked(systemApi.getSettings);
const noRate = { exchange_rate_usd_uzs: null } as never;
const withRate = { exchange_rate_usd_uzs: '12600' } as never;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-21T10:00:00Z'));
  useCurrencyStore.setState({ rate: null, rateLoaded: false, rateUnavailable: false, rateRetryAt: 0, rateFailures: 0 });
  useCurrencyStore.getState().setCurrency('UZS');
  getSettings.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('повтор загрузки курса', () => {
  it('параллельные вызовы делят один запрос', async () => {
    getSettings.mockResolvedValue(withRate);
    const { loadRate } = useCurrencyStore.getState();

    await Promise.all([loadRate(), loadRate(), loadRate({ force: true })]);

    expect(getSettings).toHaveBeenCalledTimes(1);
    expect(useCurrencyStore.getState().rate).toBe(12600);
  });

  it('курса нет: следующие неявные вызовы не ходят в сеть, пока идёт пауза', async () => {
    getSettings.mockResolvedValue(noRate);
    const { loadRate } = useCurrencyStore.getState();

    await loadRate();
    await loadRate();
    await loadRate();
    expect(getSettings).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(29_000);
    await loadRate();
    expect(getSettings).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(2_000); // 31 с — пауза вышла
    await loadRate();
    expect(getSettings).toHaveBeenCalledTimes(2);
  });

  it('пауза растёт вдвое и не превышает 10 минут', async () => {
    getSettings.mockRejectedValue(new Error('boom'));
    const { loadRate } = useCurrencyStore.getState();
    const pauses: number[] = [];
    for (let i = 0; i < 8; i += 1) {
      await loadRate({ force: true });
      pauses.push(useCurrencyStore.getState().rateRetryAt - Date.now());
    }
    expect(pauses).toEqual([30_000, 60_000, 120_000, 240_000, 480_000, 600_000, 600_000, 600_000]);
  });

  it('явное действие пробивает паузу', async () => {
    getSettings.mockResolvedValueOnce(noRate);
    await useCurrencyStore.getState().loadRate();
    getSettings.mockResolvedValueOnce(withRate);

    await useCurrencyStore.getState().loadRate({ force: true });

    expect(getSettings).toHaveBeenCalledTimes(2);
    expect(useCurrencyStore.getState().rate).toBe(12600);
  });

  it('успех сбрасывает счётчик пауз', async () => {
    getSettings.mockResolvedValueOnce(noRate);
    await useCurrencyStore.getState().loadRate();
    expect(useCurrencyStore.getState().rateFailures).toBe(1);

    getSettings.mockResolvedValueOnce(withRate);
    await useCurrencyStore.getState().loadRate({ force: true });

    expect(useCurrencyStore.getState().rateFailures).toBe(0);
    expect(useCurrencyStore.getState().rateRetryAt).toBe(0);
  });

  it('курс загружен: больше никаких запросов, и неявных, и явных', async () => {
    getSettings.mockResolvedValue(withRate);
    await useCurrencyStore.getState().loadRate();
    await useCurrencyStore.getState().loadRate();
    await useCurrencyStore.getState().loadRate({ force: true });
    expect(getSettings).toHaveBeenCalledTimes(1);
  });
});
