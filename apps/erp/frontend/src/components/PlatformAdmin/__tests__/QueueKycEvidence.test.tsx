import { describe, it, expect, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { QueueConfirmDialogs } from '../QueueConfirmDialogs';
import type { AdminQueueItem } from '@/api/adminApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import i18n from '@/i18n';

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

// Очередь триажа — ПЯТЫЙ путь выдачи уровня KYC, и правила у него те же, что у реестра:
// компания без документов или без ИНН подтверждается только с обоснованием. Пробелы считает
// сервер и присылает кодами в строке очереди — здесь проверяется, что витрина им следует.
function queueItem(gaps: string[]): AdminQueueItem {
  return {
    queue_type: 'kyc_pending',
    entity_type: 'company',
    entity_id: 42,
    title: 'ООО Без документов',
    subtitle: 'INN 900000001',
    severity: 'warning',
    created_at: '2026-08-20T09:00:00Z',
    age: '4d',
    actions: ['approve_kyc_l2', 'revoke_kyc', 'view'],
    link: '/admin/companies/42',
    evidence_gaps: gaps,
  };
}

describe('Очередь триажа: подтверждение KYC без доказательств', () => {
  it('предупреждает и требует причину, когда сервер прислал пробелы', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <QueueConfirmDialogs
        confirm={{ kind: 'approve-kyc', item: queueItem(['NO_DOCUMENTS']) }}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Компания подтверждается без/)).toBeInTheDocument();

    const confirm = within(dialog).getByRole('button', { name: 'Одобрить' });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByRole('textbox'), 'учредительные придут позже');
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(onConfirm).toHaveBeenCalledWith({ reason: 'учредительные придут позже' });
  });

  it('у компании с доказательствами причина остаётся необязательной', async () => {
    renderWithProviders(
      <QueueConfirmDialogs
        confirm={{ kind: 'approve-kyc', item: queueItem([]) }}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/Компания подтверждается без/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Одобрить' })).toBeEnabled();
  });

  it('отказ сервера читается словами, а не кодом', async () => {
    const user = userEvent.setup();
    const onConfirm = vi
      .fn()
      .mockRejectedValue({ response: { data: { detail: 'KYC_REASON_REQUIRED_WITHOUT_EVIDENCE' } } });
    renderWithProviders(
      <QueueConfirmDialogs
        confirm={{ kind: 'approve-kyc', item: queueItem(['NO_DOCUMENTS']) }}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'причина');
    await user.click(within(dialog).getByRole('button', { name: 'Одобрить' }));

    // Отказ приходит тостом (так устроен ConfirmActionDialog) — важно, что оператор видит
    // ФРАЗУ, а не код: до 24-08 очередь не получала `translateError` вовсе. Сверяем с тем же
    // каталогом, которым переводит сам код, — тогда тест не привязан к языку прогона.
    expect(toast.error).toHaveBeenCalledWith(i18n.t('apiErrors.KYC_REASON_REQUIRED_WITHOUT_EVIDENCE'));
    expect(toast.error).not.toHaveBeenCalledWith('KYC_REASON_REQUIRED_WITHOUT_EVIDENCE');
  });
});
