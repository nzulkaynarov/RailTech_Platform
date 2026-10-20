import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote } from '@/api/crmApi';
import { QuoteView } from '../QuoteView';

/**
 * FIX-58 / D-12 — карточка КП на сделке:
 *  • «Базовая цена» позиции с себестоимостью в USD печаталась «120,00 UZS»: форматтер сумов
 *    применялся к числу в валюте строки. Теперь — в валюте самой строки.
 *  • Наблюдатель (нет `quote.view_cost_margin`) видел колонки себестоимости с «не число UZS»:
 *    сервер поля вырезает, а интерфейс всё равно рисовал колонки.
 */
let permissions: string[] = [];
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (state: { capabilities: { permissions: string[] } }) => unknown) =>
    selector({ capabilities: { permissions } }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (state: { format: (value: number) => string }) => unknown) =>
    selector({ format: (value: number) => `${value} UZS` }),
}));
vi.mock('@/components/CRM/QuoteFxRates', () => ({ QuoteFxRates: () => null }));

const deal = { id: 5 } as unknown as Deal;

function quoteWith(item: Record<string, unknown>): Quote {
  return {
    id: 1,
    version: 1,
    status_code: 'SENT',
    status_name: 'Отправлено',
    created_at: '2026-07-01T10:00:00Z',
    total_incl_vat: '1000',
    subtotal_excl_vat: '900',
    vat_amount: '100',
    vat_rate: '12',
    charges_total: '0',
    items: [{ id: 1, imported_raw_name: 'Болт', quantity: 2, final_price_excl_vat: '450', margin_percent: '10', ...item }],
  } as unknown as Quote;
}

describe('QuoteView — колонки себестоимости', () => {
  beforeEach(() => {
    permissions = ['quote.view_cost_margin'];
  });

  it('базовая цена позиции в USD печатается в USD, а не сумах', () => {
    renderWithProviders(
      <QuoteView deal={deal} quote={quoteWith({ frozen_base_price: '120.00', frozen_currency: 'USD' })} />,
    );
    const row = screen.getByText('Болт').closest('tr') as HTMLElement;
    const cells = within(row).getAllByRole('cell');
    const base = cells[4].textContent ?? '';
    expect(base).toMatch(/USD|\$/);
    expect(base).not.toMatch(/UZS|сум/);
    expect(base).toMatch(/120/);
  });

  it('позиция без валюты — в сумах', () => {
    renderWithProviders(
      <QuoteView deal={deal} quote={quoteWith({ frozen_base_price: '5000', frozen_currency: null })} />,
    );
    const row = screen.getByText('Болт').closest('tr') as HTMLElement;
    expect(within(row).getAllByRole('cell')[4].textContent).toMatch(/UZS|сум/);
  });

  it('без права видеть себестоимость колонок «Базовая цена» и «Наценка» нет, нет и «NaN»', () => {
    permissions = [];
    renderWithProviders(
      <QuoteView deal={deal} quote={quoteWith({ frozen_base_price: undefined, frozen_currency: undefined, margin_percent: undefined })} />,
    );
    expect(screen.queryByRole('columnheader', { name: 'Базовая цена' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Наценка' })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Финальная цена/ })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|не число/i);
  });
});
