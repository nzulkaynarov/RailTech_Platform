/**
 * «Мои заявки» — первый экран покупателя, и на телефоне он был сырой таблицей на 868 px:
 * строки обрезались, а горизонтальная прокрутка не читалась (оверлейный скроллбар — тот же
 * класс, что чинили в публичной КП #587).
 *
 * `ResponsiveDataTable` — канон продукта: таблица на sm+ и карточки «подпись: значение» ниже.
 * Тест держит ОБЕ половины, потому что jsdom не считает медиазапросы: десктопная разметка и
 * мобильная существуют в дереве одновременно, и проверять надо факт их наличия, а не то,
 * какая из них видима в браузере.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MyRequestsPage from '../MyRequestsPage';
import { crmApi } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return { ...actual, crmApi: { ...actual.crmApi, getDeals: vi.fn() } };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const DEAL = {
  id: 41,
  title: 'Тормозные колодки',
  stage_code: 'DRAFT',
  stage_name: 'Черновик',
  created_at: '2026-08-20T09:00:00Z',
  total_value: '0.00',
  company_name: 'UTY Tashkent',
};

describe('«Мои заявки» на телефоне', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (crmApi.getDeals as ReturnType<typeof vi.fn>).mockResolvedValue([DEAL]);
  });

  it('рядом с таблицей есть мобильная раскладка карточками', async () => {
    renderWithProviders(<MyRequestsPage />);
    await waitFor(() => expect(screen.getAllByText('Тормозные колодки').length).toBeGreaterThan(0));

    // Десктопная половина — обычная таблица.
    expect(document.querySelector('thead')).not.toBeNull();
    // Мобильная — блок, скрытый на sm и выше. Именно его не существовало: страница печатала
    // одну таблицу без альтернативы.
    const mobileBlock = document.querySelector('.sm\\:hidden');
    expect(mobileBlock, 'мобильная раскладка обязана существовать в дереве').not.toBeNull();
    expect(mobileBlock?.textContent).toContain('Тормозные колодки');
    // Подписи полей — признак карточки «подпись: значение», а не обрезанной таблицы.
    expect(mobileBlock?.textContent).toContain('Статус');
  });

  it('строка открывает заявку — и в таблице, и в карточке', async () => {
    const user = userEvent.setup();
    renderWithProviders(<MyRequestsPage />);
    await waitFor(() => expect(screen.getAllByText('Тормозные колодки').length).toBeGreaterThan(0));

    const mobileBlock = document.querySelector('.sm\\:hidden') as HTMLElement;
    await user.click(mobileBlock.querySelector('[role="button"]') as HTMLElement);

    await waitFor(() => expect(window.location.hash).toContain('request-detail/41'));
  });
});
