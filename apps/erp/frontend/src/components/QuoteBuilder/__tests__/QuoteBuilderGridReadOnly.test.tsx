import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, QuoteItem } from '@/api/crmApi';
import { QuoteBuilderGrid } from '@/components/QuoteBuilder/QuoteBuilderGrid';
import {
  useDeal, useQuoteItems, useUpdateQuoteItem, useBulkUpdateQuoteItems, useBulkCreateQuoteItems,
  useBulkDeleteQuoteItems, useCreateQuoteItem, useDeleteQuoteItem,
} from '@/hooks/useCRM';

/**
 * FIX-58 / D-03 — конструктор КП в режиме «только чтение»: Наблюдатель (нет права
 * `quote.edit_pricing`) и КП не в черновике (после согласования, отправки, акцепта — сервер
 * отвечает 409, интерфейс не предлагает правок). Просмотр остаётся: позиции, итоги, раскрытие строки.
 */
vi.mock('@/hooks/useCRM', () => ({
  useDeal: vi.fn(),
  useQuoteItems: vi.fn(),
  useUpdateQuoteItem: vi.fn(),
  useBulkUpdateQuoteItems: vi.fn(),
  useBulkCreateQuoteItems: vi.fn(),
  useBulkDeleteQuoteItems: vi.fn(),
  useCreateQuoteItem: vi.fn(),
  useDeleteQuoteItem: vi.fn(),
  useSetQuoteDeliveryBasis: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/hooks/useMasterData', () => ({ useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }] }) }));
vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));
vi.mock('@/components/CRM/QuoteChargesSection', () => ({ QuoteChargesSection: () => null }));
vi.mock('@/components/CRM/QuoteSettingsDialog', () => ({ QuoteSettingsDialog: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/ReassignProductDialog', () => ({ ReassignProductDialog: () => null }));
vi.mock('@/components/QuoteBuilder/AICatalogMatchDialog', () => ({ AICatalogMatchDialog: () => null }));

const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });
const setHook = (hook: unknown, value: unknown) => (hook as Mock).mockReturnValue(value);

const deal = {
  id: 7,
  active_quote: {
    id: 200,
    status_code: 'DRAFT',
    quote_currency: 'UZS',
    vat_rate: '12',
    margin_percent: '20',
    cost_currency_default: 'UZS',
    delivery_basis: null,
    frozen_at: null,
    fx_snapshot: {},
    fx_manual: {},
    charges: [],
    charges_total: '0',
    subtotal_excl_vat: '120',
    vat_amount: '14.4',
    total_incl_vat: '134.4',
    effective_delivery_lead_time_days: 0,
    economics: null,
  },
} as unknown as Deal;
const item = {
  id: 1, product: 1, product_name: 'Рельс Р65', product_sku: 'SKU-1', quantity: 3,
  frozen_base_price: '100', frozen_currency: 'UZS', customs_duty: '0', discount_percent: '0',
  lead_time_days: 0, hs_code: '', margin_percent: '0', landed_cost: '100', final_price_excl_vat: '120',
  offer_supplier_name: 'ООО Поставщик',
} as unknown as QuoteItem;

describe('QuoteBuilderGrid readOnly (D-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    [useUpdateQuoteItem, useBulkUpdateQuoteItems, useBulkCreateQuoteItems, useBulkDeleteQuoteItems, useCreateQuoteItem, useDeleteQuoteItem]
      .forEach((h) => setHook(h, mkMutation()));
    setHook(useDeal, { data: deal, isLoading: false });
    setHook(useQuoteItems, { data: [item], isLoading: false });
  });

  it('по умолчанию правки есть: «Добавить», удалить строку, «Сохранить»', () => {
    renderWithProviders(<QuoteBuilderGrid dealId={7} />);
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Удалить позицию 1|Удалить строку 1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
  });

  it('readOnly: нет кнопок правки и сохранения, поля заблокированы, позиция и итоги видны', () => {
    renderWithProviders(<QuoteBuilderGrid dealId={7} readOnly />);
    expect(screen.queryByRole('button', { name: 'Добавить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Удалить позицию 1|Удалить строку 1/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Настройки КП/ })).not.toBeInTheDocument();
    const qty = screen.getByRole('textbox', { name: 'Кол-во' });
    expect(qty).toBeDisabled();
    expect(screen.getByText('Рельс Р65')).toBeInTheDocument();
    expect(screen.getByText('Только чтение')).toBeInTheDocument();
  });
});
