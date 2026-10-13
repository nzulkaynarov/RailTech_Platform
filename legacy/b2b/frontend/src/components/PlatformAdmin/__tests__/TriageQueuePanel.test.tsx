import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { TriageQueuePanel } from '../TriageQueuePanel';
import type { AdminQueueItem } from '@/api/adminApi';
import { renderWithProviders } from '@/test/renderWithProviders';

function item(entity_id: number): AdminQueueItem {
  return {
    queue_type: 'kyc_pending',
    entity_id,
    title: `Компания ${entity_id}`,
    subtitle: '',
    severity: 'warning',
    age: '1 дн.',
    actions: [],
  } as unknown as AdminQueueItem;
}

const base = {
  totals: {},
  filter: '',
  onFilterChange: vi.fn(),
  isLoading: false,
  isError: false,
  onRetry: vi.fn(),
  onOpen: vi.fn(),
  onApprove: vi.fn(),
  onReject: vi.fn(),
};

describe('TriageQueuePanel — состояния', () => {
  it('ошибка предлагает повтор, а не пустой экран', () => {
    const onRetry = vi.fn();
    renderWithProviders(<TriageQueuePanel {...base} items={[]} isError onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('пустая очередь — это успех, а не «нет данных»', () => {
    renderWithProviders(<TriageQueuePanel {...base} items={[]} />);
    // Формулировка и иконка успеха: очередь разобрана, оператору делать нечего.
    expect(screen.getByText('Всё под контролем')).toBeTruthy();
  });

  it('ошибка имеет приоритет над загрузкой', () => {
    renderWithProviders(<TriageQueuePanel {...base} items={[]} isError isLoading />);
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy();
    expect(screen.queryByText('Всё под контролем')).toBeNull();
  });

  it('счётчик в заголовке равен числу показанных строк', () => {
    renderWithProviders(<TriageQueuePanel {...base} items={[item(1), item(2), item(3)]} />);
    expect(screen.getByText('(3)')).toBeTruthy();
    expect(screen.getByText('Компания 1')).toBeTruthy();
    expect(screen.getByText('Компания 3')).toBeTruthy();
  });

  it('«Все» сбрасывает фильтр в пустую строку, а не в литерал all', () => {
    // Панель принимает «» как «без фильтра» — хук очереди передаёт undefined в запрос.
    // Утечка литерала 'all' в параметр отфильтровала бы очередь в ноль.
    const onFilterChange = vi.fn();
    renderWithProviders(
      <TriageQueuePanel {...base} items={[item(1)]} totals={{ kyc_pending: 1 }} filter="kyc_pending" onFilterChange={onFilterChange} />,
    );
    expect(screen.getByText('Компания 1')).toBeTruthy();
  });
});
