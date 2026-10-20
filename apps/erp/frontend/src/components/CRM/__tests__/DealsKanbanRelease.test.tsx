/**
 * «Взять в работу» получило обратное действие.
 *
 * Эндпоинт возврата в очередь и хук `useReleaseDeal` существовали, но не вызывались ниоткуда
 * (аудит UI 2026-07-30, §3.2): менеджер, взявший заявку по ошибке, оставался с ней навсегда.
 * Паттерн — очереди Salesforce: запись возвращается команде, откуда её берёт любой коллега.
 *
 * Право показывать кнопку приходит С СЕРВЕРА (`viewer_can_release`) тем же предикатом, что и
 * само действие. Фронт его не выводит: именно самостоятельный вывод прав дал 13 тупиков волны U1.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { toast } from 'sonner';

import { DealsKanban } from '../DealsKanban';
import { crmApi, type Deal } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';

vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, claimDeal: vi.fn(), releaseDeal: vi.fn() },
  };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const STAGES = [{ code: 'RFQ_OPEN', name: 'Заявка открыта' }];

function makeDeal(overrides: Partial<Deal> & { id: number }): Deal {
  return { created_at: '2026-07-01T10:00:00Z', stage_code: 'RFQ_OPEN', ...overrides };
}

/** Карточка, владеющая подписью. */
async function findCard(text: string): Promise<HTMLElement> {
  const node = await screen.findByText(text);
  const card = node.closest('[data-slot="card"]') ?? node.closest('div');
  if (!card) throw new Error(`нет карточки для «${text}»`);
  return card as HTMLElement;
}

describe('возврат сделки в очередь', () => {
  beforeEach(() => {
    // Кнопки взять / вернуть — по праву deal.manage из /me (D-03, FIX-58).
    useUserStore.setState({ capabilities: { permissions: ['deal.manage'] } });
    vi.mocked(crmApi.releaseDeal).mockReset().mockResolvedValue({ id: 2 } as never);
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it('кнопка есть у того, кому сервер разрешил возврат', async () => {
    const deals = [makeDeal({ id: 2, title: 'Стрелочный перевод', assigned_to: 9, assigned_to_name: 'Алишер', viewer_can_release: true })];
    renderWithProviders(<DealsKanban deals={deals} stages={STAGES} />);

    const card = await findCard('Стрелочный перевод');
    expect(within(card).getByRole('button', { name: 'Вернуть в очередь' })).toBeInTheDocument();
  });

  it('кнопки НЕТ у того, кому сервер возврат не разрешил', async () => {
    // Коллега видит владельца записи, но распоряжаться ею не может — и кнопки не видит.
    const deals = [makeDeal({ id: 2, title: 'Стрелочный перевод', assigned_to: 9, assigned_to_name: 'Алишер', viewer_can_release: false })];
    renderWithProviders(<DealsKanban deals={deals} stages={STAGES} />);

    await screen.findByText('Стрелочный перевод');
    expect(screen.queryByRole('button', { name: 'Вернуть в очередь' })).not.toBeInTheDocument();
  });

  it('невзятая заявка предлагает «Взять», но не «Вернуть» — возвращать нечего', async () => {
    const deals = [makeDeal({ id: 1, title: 'Рельсы Р65', assigned_to: null })];
    renderWithProviders(<DealsKanban deals={deals} stages={STAGES} />);

    await screen.findByText('Рельсы Р65');
    expect(screen.getByRole('button', { name: 'Взять в работу' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Вернуть в очередь' })).not.toBeInTheDocument();
  });

  it('клик вызывает возврат именно этой сделки и подтверждает результат', async () => {
    const deals = [makeDeal({ id: 2, title: 'Стрелочный перевод', assigned_to: 9, viewer_can_release: true })];
    renderWithProviders(<DealsKanban deals={deals} stages={STAGES} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Вернуть в очередь' }));

    await waitFor(() => expect(crmApi.releaseDeal).toHaveBeenCalledWith(2));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });
});
