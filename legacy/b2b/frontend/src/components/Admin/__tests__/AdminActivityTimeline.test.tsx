/**
 * История записи на операторской карточке.
 *
 * Поверхность существовала (компании, пользователи, подписки, заявки на роль), но само чтение
 * было реализовано ДВАЖДЫ: компонент собирал запрос инлайном, а рядом лежал хук с тем же
 * ключом кэша, который поэтому числился мёртвым. Одна реализация — один способ ошибиться.
 *
 * Главная проверка здесь — про ошибку загрузки. Для журнала аудита «не удалось загрузить» и
 * «действий не было» — противоположные утверждения: во втором случае оператор принимает
 * решение, считая, что с записью ничего не делали.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { AdminActivityTimeline } from '../AdminActivityTimeline';
import { adminApi, type AdminActivityEntry } from '@/api/adminApi';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/adminApi')>();
  return { ...actual, adminApi: { ...actual.adminApi, getActivity: vi.fn() } };
});

function makeEntry(overrides: Partial<AdminActivityEntry> & { id: number }): AdminActivityEntry {
  return {
    action: 'KYC подтверждён',
    detail: 'Уровень L2',
    level: 'SUCCESS',
    reason: '',
    before_data: null,
    after_data: null,
    user_id: 3,
    user_email: 'operator@railtech.uz',
    user_name: 'Оператор Платформы',
    timestamp: '2026-07-30T10:00:00Z',
    ...overrides,
  };
}

describe('история записи', () => {
  beforeEach(() => {
    vi.mocked(adminApi.getActivity).mockReset();
  });

  it('запрашивает журнал именно по этой записи', async () => {
    vi.mocked(adminApi.getActivity).mockResolvedValue({ count: 0, items: [] });
    renderWithProviders(<AdminActivityTimeline entityType="company" entityId={42} />);

    await waitFor(() => expect(adminApi.getActivity).toHaveBeenCalledWith('company', 42, 100));
  });

  it('показывает действие вместе с тем, кто его совершил', async () => {
    vi.mocked(adminApi.getActivity).mockResolvedValue({
      count: 1,
      items: [makeEntry({ id: 1 })],
    });
    renderWithProviders(<AdminActivityTimeline entityType="company" entityId={42} />);

    expect(await screen.findByText('KYC подтверждён')).toBeInTheDocument();
    expect(screen.getByText(/Оператор Платформы/)).toBeInTheDocument();
  });

  it('при сбое загрузки говорит об ошибке, а не «действий не было»', async () => {
    // Для журнала аудита это противоположные утверждения: молчание означало бы, что с
    // записью ничего не делали, и оператор принял бы решение на ложном основании.
    vi.mocked(adminApi.getActivity).mockRejectedValue(new Error('boom'));
    renderWithProviders(<AdminActivityTimeline entityType="company" entityId={42} />);

    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('пустой журнал остаётся пустым журналом', async () => {
    vi.mocked(adminApi.getActivity).mockResolvedValue({ count: 0, items: [] });
    renderWithProviders(<AdminActivityTimeline entityType="company" entityId={42} />);

    expect(await screen.findByText('История изменений пуста')).toBeInTheDocument();
  });
});
