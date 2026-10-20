import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ActsPage } from '../ActsPage';
import { actsApi, type Act } from '@/api/billingApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';

// Заказчик вернул акт с причиной — диалог отказа обещает ему, что «исполнитель выставит акт
// заново». Пути для этого не существовало: у возвращённого акта оставалась одна кнопка
// «Аннулировать», а «Сформировать акт» на странице счетов порождала ВТОРОЙ документ.
vi.mock('@/api/billingApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/billingApi')>();
  return {
    ...actual,
    actsApi: { ...actual.actsApi, list: vi.fn(), reissue: vi.fn(), cancel: vi.fn(), remind: vi.fn() },
  };
});

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function makeAct(overrides: Partial<Act>): Act {
  return {
    id: 1,
    deal: 42,
    contract: null,
    invoice: 7,
    number: 'ACT-2026-00001',
    status: 'DRAFT',
    issued_at: '2026-08-20',
    signed_at: null,
    total_amount: '112.00',
    pdf_file: null,
    pdf_url: null,
    signed_file: null,
    signed_file_url: null,
    viewer_can_remind: false,
    viewer_can_cancel: true,
    viewer_can_reissue: true,
    issuer_signer: null,
    issuer_signer_name: '',
    issuer_signed_at: null,
    acceptor_signer: null,
    acceptor_signer_name: '',
    acceptor_signed_at: null,
    rejection_reason: 'Объём не совпал',
    cancellation_reason: '',
    reminder_sent_at: null,
    notes: '',
    created_at: '2026-08-20T10:00:00Z',
    updated_at: '2026-08-20T10:00:00Z',
    ...overrides,
  } as Act;
}

describe('Возвращённый акт выпускается заново', () => {
  beforeEach(() => {
    // Действия исполнителя по акту — право fulfillment.act из /me (FIX-58, D-03).
    useUserStore.setState({ capabilities: { permissions: ['fulfillment.act'] } });
    vi.clearAllMocks();
    (actsApi.reissue as ReturnType<typeof vi.fn>).mockResolvedValue(makeAct({ status: 'ISSUED' }));
  });

  it('у возвращённого акта есть кнопка «Выставить заново», и она зовёт свой эндпоинт', async () => {
    const user = userEvent.setup();
    (actsApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([makeAct({})]);
    renderWithProviders(<ActsPage />);

    // Номер печатается и в строке реестра, и в карточке — берём первый (канон соседнего теста).
    fireEvent.click((await screen.findAllByText('ACT-2026-00001'))[0]);
    const card = await screen.findByRole('dialog');

    await user.click(within(card).getByRole('button', { name: /Выставить заново/ }));

    await waitFor(() => expect(actsApi.reissue).toHaveBeenCalledWith(1));
  });

  it('у выставленного акта такой кнопки нет — выпускать заново нечего', async () => {
    (actsApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeAct({ status: 'ISSUED', viewer_can_reissue: false, viewer_can_remind: true, rejection_reason: '' }),
    ]);
    renderWithProviders(<ActsPage />);

    fireEvent.click((await screen.findAllByText('ACT-2026-00001'))[0]);
    const card = await screen.findByRole('dialog');

    await within(card).findByRole('button', { name: /Напомнить/ });
    expect(within(card).queryByRole('button', { name: /Выставить заново/ })).not.toBeInTheDocument();
  });
});
