import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { MaintenanceBanner } from '@/components/MaintenanceBanner';
import i18n from '@/i18n';

const STARTS = Date.parse('2026-11-23T19:15:00+05:00');
const MIN = 60_000;
let body: unknown;
let status = 200;

function renderBanner() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MaintenanceBanner />
    </QueryClientProvider>,
  );
}

describe('MaintenanceBanner', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('ru');
    vi.useFakeTimers({ shouldAdvanceTime: true });
    status = 200;
    window.sessionStorage.clear();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }))),
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('за 30 минут — предупреждение с временем, role=status', async () => {
    vi.setSystemTime(STARTS - 30 * MIN);
    body = { starts_at: '2026-11-23T19:15:00+05:00', minutes: 3, kind: 'planned' };
    renderBanner();
    const banner = await screen.findByRole('status');
    expect(banner.textContent).toContain(
      'Обновление кабинета в 19:15 — работа прервётся на 2–3 минуты. Сохраните изменения.',
    );
  });

  it('срочное исправление — другое слово', async () => {
    vi.setSystemTime(STARTS - 10 * MIN);
    body = { starts_at: '2026-11-23T19:15:00+05:00', kind: 'urgent' };
    renderBanner();
    expect((await screen.findByRole('status')).textContent).toContain('Срочное исправление кабинета в 19:15');
  });

  it('внутри работ — «Идёт обновление», без кнопки скрытия', async () => {
    vi.setSystemTime(STARTS + MIN);
    body = { starts_at: '2026-11-23T19:15:00+05:00', minutes: 3 };
    renderBanner();
    expect((await screen.findByRole('status')).textContent).toContain('Идёт обновление');
    expect(screen.queryByRole('button', { name: 'Скрыть' })).toBeNull();
  });

  it('скрыть: баннер уходит, через 10 минут возвращается', async () => {
    vi.setSystemTime(STARTS - 29 * MIN);
    body = { starts_at: '2026-11-23T19:15:00+05:00', minutes: 3 };
    renderBanner();
    await screen.findByRole('status');
    fireEvent.click(screen.getByRole('button', { name: 'Скрыть' }));
    expect(screen.queryByRole('status')).toBeNull();
    await act(async () => {
      vi.setSystemTime(STARTS - 18 * MIN);
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(screen.queryByRole('status')).not.toBeNull();
  });

  it.each([
    [404, ''],
    [200, '{}'],
    [200, '<!doctype html><html></html>'],
  ])('ответ %s %s — баннера нет', async (code, text) => {
    vi.setSystemTime(STARTS - 10 * MIN);
    status = code;
    body = text;
    renderBanner();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(fetch).toHaveBeenCalled();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
