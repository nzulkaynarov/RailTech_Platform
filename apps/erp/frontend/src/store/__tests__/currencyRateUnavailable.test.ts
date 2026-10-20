/**
 * Нет курса — нет пересчёта (FIX-41, F-12).
 *
 * Раньше при отказе `systemApi.getSettings` стор оставлял захардкоженный DEFAULT_RATE = 12650 и
 * по нему пересчитывал ПОКАЗЫВАЕМЫЕ суммы в USD. Теперь резервного курса нет: курс приходит только из
 * справочника ERP (`finance.services.fx`), без него суммы остаются в сумах, а USD недоступен.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useCurrencyStore } from '../currencyStore';
import { systemApi } from '@/api/systemApi';

vi.mock('@/api/systemApi', () => ({ systemApi: { getSettings: vi.fn() } }));

const reset = () => {
  useCurrencyStore.setState({ rate: null, rateLoaded: false, rateUnavailable: false });
  useCurrencyStore.getState().setCurrency('UZS');
  vi.mocked(systemApi.getSettings).mockReset();
};

describe('курс из справочника ERP, без резервного значения', () => {
  beforeEach(reset);

  it('до загрузки курса нет: суммы в сумах, USD не включается', () => {
    expect(useCurrencyStore.getState().rate).toBeNull();
    useCurrencyStore.getState().setCurrency('USD');
    expect(useCurrencyStore.getState().currency).toBe('UZS');
    expect(useCurrencyStore.getState().format(1_265_000)).not.toContain('$');
  });

  it('после успешной загрузки курс из ответа, USD доступен', async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: '12600' } as never);

    await useCurrencyStore.getState().loadRate();
    useCurrencyStore.getState().setCurrency('USD');

    const state = useCurrencyStore.getState();
    expect(state.rate).toBe(12600);
    expect(state.rateUnavailable).toBe(false);
    expect(state.currency).toBe('USD');
    expect(state.convert(1_260_000)).toBe(100);
  });

  it('при отказе API курса нет: USD недоступен, суммы не пересчитываются по выдуманному курсу', async () => {
    vi.mocked(systemApi.getSettings).mockRejectedValue(new Error('boom'));

    await useCurrencyStore.getState().loadRate();
    useCurrencyStore.getState().setCurrency('USD');

    const state = useCurrencyStore.getState();
    expect(state.rate).toBeNull();
    expect(state.rateUnavailable).toBe(true);
    expect(state.currency).toBe('UZS');
    expect(state.convert(12_650_000)).toBe(12_650_000);
    expect(state.format(12_650_000)).not.toContain('$');
  });

  it('сервер вернул null (в справочнике нет свежего курса): та же честная деградация', async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: null } as never);

    await useCurrencyStore.getState().loadRate();

    expect(useCurrencyStore.getState().rate).toBeNull();
    expect(useCurrencyStore.getState().rateUnavailable).toBe(true);
    expect(useCurrencyStore.getState().rateLoaded).toBe(false); // не защёлкнуто — следующий вызов повторит
  });

  it('курс пропал, пока был включён USD: возвращаемся в суммы', async () => {
    useCurrencyStore.setState({ rate: 12600 });
    useCurrencyStore.getState().setCurrency('USD');
    vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: null } as never);

    await useCurrencyStore.getState().loadRate();

    expect(useCurrencyStore.getState().currency).toBe('UZS');
  });

  it('нулевой и отрицательный курс — не курс', async () => {
    for (const bad of ['0', '-5']) {
      useCurrencyStore.setState({ rate: null, rateLoaded: false });
      vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: bad } as never);
      await useCurrencyStore.getState().loadRate();
      expect(useCurrencyStore.getState().rate).toBeNull();
    }
  });

  it('401 до входа → вход → курс загружен, USD доступен', async () => {
    // До входа system-settings отвечает 401 — курса нет.
    vi.mocked(systemApi.getSettings).mockRejectedValueOnce(new Error('401'));
    await useCurrencyStore.getState().loadRate();
    expect(useCurrencyStore.getState().rateUnavailable).toBe(true);
    useCurrencyStore.getState().setCurrency('USD');
    expect(useCurrencyStore.getState().currency).toBe('UZS');

    // После входа App зовёт loadRate снова — курс подхватывается без перезагрузки.
    vi.mocked(systemApi.getSettings).mockResolvedValueOnce({ exchange_rate_usd_uzs: '12700' } as never);
    await useCurrencyStore.getState().loadRate();
    useCurrencyStore.getState().setCurrency('USD');

    const state = useCurrencyStore.getState();
    expect(state.rate).toBe(12700);
    expect(state.rateUnavailable).toBe(false);
    expect(state.rateLoaded).toBe(true);
    expect(state.currency).toBe('USD');
  });

  it('курс уже загружен — повторный вызов не ходит в сеть', async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue({ exchange_rate_usd_uzs: '12600' } as never);
    await useCurrencyStore.getState().loadRate();
    await useCurrencyStore.getState().loadRate();
    expect(systemApi.getSettings).toHaveBeenCalledTimes(1);
  });

  it('сервер ответил null → позже курс появился: следующий вызов подхватывает', async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValueOnce({ exchange_rate_usd_uzs: null } as never);
    await useCurrencyStore.getState().loadRate();
    vi.mocked(systemApi.getSettings).mockResolvedValueOnce({ exchange_rate_usd_uzs: '12650' } as never);
    await useCurrencyStore.getState().loadRate();
    expect(useCurrencyStore.getState().rate).toBe(12650);
    expect(useCurrencyStore.getState().rateUnavailable).toBe(false);
  });
});
