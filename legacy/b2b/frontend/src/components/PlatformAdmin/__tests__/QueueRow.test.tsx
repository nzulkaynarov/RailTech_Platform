import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { QueueRow } from '../QueueRow';
import type { AdminQueueItem } from '@/api/adminApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Набор действий приходит С СЕРВЕРА (`item.actions`), а не выводится из типа очереди на
// фронте. Значит кнопки «Одобрить»/«Отклонить» обязаны появляться ровно тогда, когда бэкенд
// их заявил: лишняя кнопка = операция, на которую у оператора нет права, а недостающая =
// тупик, из которого запись очереди не разрешить.

function item(overrides: Partial<AdminQueueItem> = {}): AdminQueueItem {
  return {
    queue_type: 'kyc_pending',
    entity_id: 1,
    title: 'ООО «Тест»',
    subtitle: 'ИНН 300000000',
    severity: 'warning',
    age: '2 дн.',
    actions: [],
    ...overrides,
  } as AdminQueueItem;
}

describe('QueueRow — кнопки следуют за actions с сервера', () => {
  it('без заявленных действий остаётся только «Открыть»', () => {
    renderWithProviders(<QueueRow item={item()} onOpen={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Открыть' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Одобрить' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull();
  });

  it('approve_kyc показывает «Одобрить»', () => {
    renderWithProviders(
      <QueueRow item={item({ actions: ['approve_kyc'] })} onOpen={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Одобрить' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull();
  });

  it('revoke_kyc показывает «Отклонить» (префикс revoke, не только reject)', () => {
    renderWithProviders(
      <QueueRow item={item({ actions: ['revoke_kyc'] })} onOpen={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Отклонить' })).toBeTruthy();
  });

  it('без переданного обработчика кнопка не рисуется, даже если действие заявлено', () => {
    renderWithProviders(<QueueRow item={item({ actions: ['approve_kyc'] })} onOpen={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Одобрить' })).toBeNull();
  });

  it('нажатия отдают саму запись очереди', () => {
    const onOpen = vi.fn();
    const onApprove = vi.fn();
    const target = item({ actions: ['approve_kyc'] });
    renderWithProviders(<QueueRow item={target} onOpen={onOpen} onApprove={onApprove} />);

    fireEvent.click(screen.getByRole('button', { name: 'Одобрить' }));
    expect(onApprove).toHaveBeenCalledWith(target);

    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(onOpen).toHaveBeenCalledWith(target);
  });

  it('неизвестный тип очереди рендерится, а не падает на отсутствующей иконке', () => {
    renderWithProviders(
      <QueueRow item={item({ queue_type: 'something_new' as AdminQueueItem['queue_type'] })} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('ООО «Тест»')).toBeTruthy();
  });
});
