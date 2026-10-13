/**
 * Курс валют, который не приехал, — это не «курс по умолчанию», а неизвестный курс.
 *
 * Аудит UI 2026-07-30: при отказе `systemApi.getSettings` стор молча оставлял резервное
 * значение, и по нему пересчитывались ПОКАЗЫВАЕМЫЕ пользователю суммы в USD. Отличить их от
 * настоящих было невозможно. Теперь стор помечает такой курс, а переключатель валюты — суммы.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useCurrencyStore } from '../currencyStore';
import { systemApi } from '@/api/systemApi';

vi.mock('@/api/systemApi', () => ({ systemApi: { getSettings: vi.fn() } }));

describe('резервный курс помечается', () => {
  beforeEach(() => {
    useCurrencyStore.setState({ rateLoaded: false, rateIsFallback: false });
    vi.mocked(systemApi.getSettings).mockReset();
  });

  it('после успешной загрузки курс не считается резервным', async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: '12600' } as never);

    await useCurrencyStore.getState().loadRate();

    expect(useCurrencyStore.getState().rateIsFallback).toBe(false);
    expect(useCurrencyStore.getState().rate).toBe(12600);
  });

  it('при отказе API курс помечен резервным, а не выдан за настоящий', async () => {
    vi.mocked(systemApi.getSettings).mockRejectedValue(new Error('boom'));

    await useCurrencyStore.getState().loadRate();

    expect(useCurrencyStore.getState().rateIsFallback).toBe(true);
    // Пересчёт продолжает работать — приложение остаётся пригодным, просто честно помеченным.
    expect(useCurrencyStore.getState().rate).toBeGreaterThan(0);
  });
});
