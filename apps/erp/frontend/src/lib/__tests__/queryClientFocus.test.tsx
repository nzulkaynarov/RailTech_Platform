import { describe, it, expect, vi, afterEach } from 'vitest';
import { useQuery } from '@tanstack/react-query';
import { act, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { queryClient, isLiveQuery } from '../queryClient';

/**
 * FIX-58 / D-09 — открытая сессия не видела изменений коллег до перезагрузки: кэш держал данные
 * по 2 минуты, а возврат на вкладку ничего не обновлял. Теперь живые данные (списки и карточки
 * сделок, КП, договоров, счетов…) перечитываются при возврате на вкладку / фокусе окна — без
 * опроса по таймеру. Справочники (долгий staleTime) не дёргаются.
 */
function Probe({ queryKey, staleTime, fn }: { queryKey: string[]; staleTime?: number; fn: () => Promise<string> }) {
  const { data } = useQuery({ queryKey, queryFn: fn, staleTime });
  return <p>{data ?? '…'}</p>;
}

const focusWindow = () => {
  act(() => {
    window.dispatchEvent(new Event('focus'));
  });
};
const showTab = () => {
  act(() => {
    document.dispatchEvent(new Event('visibilitychange', { bubbles: true }));
  });
};

describe('перечитывание при возврате на вкладку (D-09)', () => {
  afterEach(() => queryClient.clear());

  it('живой запрос (staleTime по умолчанию) перечитывается при возврате на вкладку', async () => {
    let n = 0;
    const fn = vi.fn(async () => `v${++n}`);
    renderWithProviders(<Probe queryKey={['deals', 'x']} fn={fn} />, { queryClient });
    expect(await screen.findByText('v1')).toBeInTheDocument();

    showTab();
    expect(await screen.findByText('v2')).toBeInTheDocument();
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('и при фокусе окна', async () => {
    let n = 0;
    const fn = vi.fn(async () => `v${++n}`);
    renderWithProviders(<Probe queryKey={['quotes', 'x']} fn={fn} />, { queryClient });
    await screen.findByText('v1');
    focusWindow();
    await waitFor(() => expect(fn.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it('справочник (staleTime 30 мин) при возврате не перечитывается', async () => {
    const fn = vi.fn(async () => 'dict');
    renderWithProviders(<Probe queryKey={['currencies']} staleTime={30 * 60_000} fn={fn} />, { queryClient });
    await screen.findByText('dict');
    showTab();
    focusWindow();
    await new Promise((r) => setTimeout(r, 50));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('isLiveQuery: staleTime < 5 мин — живое, иначе справочник', () => {
    const q = (staleTime: unknown) => ({ observers: [{ options: { staleTime } }] }) as never;
    expect(isLiveQuery(q(undefined))).toBe(true);
    expect(isLiveQuery(q(60_000))).toBe(true);
    expect(isLiveQuery(q(5 * 60_000))).toBe(false);
    expect(isLiveQuery(q(30 * 60_000))).toBe(false);
  });
});
