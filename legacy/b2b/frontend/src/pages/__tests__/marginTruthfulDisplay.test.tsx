import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, QuoteItem } from '@/api/crmApi';
import { RequestDetailPage } from '@/pages/RequestDetailPage';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import {
  useDeal,
  useChangeDealStage,
  useApproveQuote,
  useRejectQuote,
  useSendQuoteToClient,
  useUpdateRequestMeta,
  usePreflightCheck,
  useQuoteRequestDiff,
  useQuoteItems,
  useUpdateQuoteItem,
  useBulkUpdateQuoteItems,
  useCreateQuoteItem,
  useDeleteQuoteItem,
  useSetQuoteDeliveryBasis,
  useClaimDeal,
} from '@/hooks/useCRM';

/**
 * WP-7 — «Правдивое отображение наценки». Two display-only guarantees:
 *  1. RequestDetailPage never renders a FALSE «0.0%» for a per-line margin that the
 *     deal-detail endpoint does not carry (QuoteItem.margin_percent is a dead model
 *     default of 0 — the КП markup is applied at quote level). It must read «—».
 *  2. QuoteBuilderGrid's marginCell is READ-ONLY — the per-line margin can never be
 *     mistaken for an editable input; the hint points at «Настройки КП».
 */

// Data hooks are mocked so the components render deterministically off fixtures.
vi.mock('@/hooks/useCRM', () => ({
  useDeal: vi.fn(),
  useChangeDealStage: vi.fn(),
  useApproveQuote: vi.fn(),
  useRejectQuote: vi.fn(),
  useSendQuoteToClient: vi.fn(),
  useUpdateRequestMeta: vi.fn(),
  usePreflightCheck: vi.fn(),
  useQuoteRequestDiff: vi.fn(),
  useQuoteItems: vi.fn(),
  useUpdateQuoteItem: vi.fn(),
  useBulkUpdateQuoteItems: vi.fn(),
  useCreateQuoteItem: vi.fn(),
  useDeleteQuoteItem: vi.fn(),
  useSetQuoteDeliveryBasis: vi.fn(),
  useClaimDeal: vi.fn(),
}));

// Page context: seller sees the margin column; a plain currency formatter keeps assertions simple.
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (state: { activeStatus: string }) => unknown) => selector({ activeStatus: 'SELLER' }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (state: { format: (value: number) => string }) => unknown) =>
    selector({ format: (value: number) => `${value} сум` }),
}));
vi.mock('@/hooks/useViewerMode', () => ({ useIsViewerMode: () => false }));
vi.mock('@/hooks/useMasterData', () => ({ useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }] }) }));
vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));

// Heavy children are irrelevant to the margin surface under test — stub them to null.
vi.mock('@/components/Sourcing/DealChatPanel', () => ({ DealChatPanel: () => null }));
vi.mock('@/components/CRM/DealTimeline', () => ({ DealTimeline: () => null }));
vi.mock('@/components/CRM/CoverageCheck', () => ({ CoverageCheck: () => null }));
vi.mock('@/components/CRM/RejectQuoteDialog', () => ({ RejectQuoteDialog: () => null }));
vi.mock('@/components/Admin/ConfirmActionDialog', () => ({ ConfirmActionDialog: () => null }));
vi.mock('@/components/CRM/RequestItemsEditor', () => ({ RequestItemsEditor: () => null }));
vi.mock('@/components/CRM/PreflightWarnings', () => ({ PreflightWarnings: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteApprovalChain', () => ({ QuoteApprovalChain: () => null }));
vi.mock('@/components/CRM/DeliveryBasisSelect', () => ({ DeliveryBasisSelect: () => null }));
vi.mock('@/components/CRM/QuoteChargesSection', () => ({ QuoteChargesSection: () => null }));
vi.mock('@/components/CRM/QuoteSettingsDialog', () => ({ QuoteSettingsDialog: () => null }));
vi.mock('@/components/CRM/ReassignProductDialog', () => ({ ReassignProductDialog: () => null }));
vi.mock('@/components/Admin/AICatalogMatchDialog', () => ({ AICatalogMatchDialog: () => null }));
vi.mock('@/components/Shared/DocumentActions', () => ({ DocumentActions: () => null }));

const setHook = (hook: unknown, value: unknown) => {
  (hook as Mock).mockReturnValue(value);
};
const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });

// A sent seller КП: one line with a dead per-line margin (0.00) + one with a real value (18.50).
const pageDeal = {
  id: 42,
  title: 'Заявка на рельсы',
  stage_code: 'CALCULATING',
  stage_name: 'Расчёт',
  company_name: 'ООО Магистраль',
  client_name: 'ООО Магистраль',
  can_edit_request: false,
  target_sellers_data: [],
  quotes: [],
  active_quote: {
    id: 100,
    version: 1,
    status_code: 'SENT',
    status_name: 'Отправлено',
    created_at: '2026-07-01T10:00:00Z',
    total_incl_vat: '134.40',
    subtotal_excl_vat: '120.00',
    vat_amount: '14.40',
    vat_rate: '12',
    charges_total: '0',
    notes: '',
    items: [
      {
        id: 1,
        product_name: 'Рельс Р65',
        quantity: 2,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '100.00',
        margin_percent: '0.00',
        final_price_excl_vat: '120.00',
      },
      {
        id: 2,
        product_name: 'Шпала ЖБ',
        quantity: 1,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '50.00',
        margin_percent: '18.50',
        final_price_excl_vat: '59.25',
      },
    ],
  },
} as unknown as Deal;

const gridEconomics = {
  total_landed_cost: '100',
  gross_profit: '20',
  gross_margin_percent: '30.0',
  markup_percent: '20',
  operating_profit: '20',
  min_margin_percent: '15',
  target_margin_percent: '25',
  below_cost: false,
  below_floor: false,
  fx_missing: [],
};
const gridDeal = {
  id: 7,
  active_quote: {
    id: 200,
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
    economics: gridEconomics,
  },
} as unknown as Deal;
// Derived per-line margin: (120 − 100) / 120 = 16.67% → toFixed(0) = 17%.
const gridItem = {
  id: 1,
  product: 1,
  product_name: 'Рельс Р65',
  product_sku: 'SKU-1',
  quantity: 1,
  frozen_base_price: '100',
  frozen_currency: 'UZS',
  customs_duty: '0',
  discount_percent: '0',
  lead_time_days: 0,
  hs_code: '',
  margin_percent: '0',
  landed_cost: '100',
  final_price_excl_vat: '120',
  offer_supplier_name: 'ООО Поставщик',
} as unknown as QuoteItem;

describe('WP-7 truthful margin display', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    [
      useChangeDealStage,
      useApproveQuote,
      useRejectQuote,
      useSendQuoteToClient,
      useUpdateRequestMeta,
      usePreflightCheck,
      useQuoteRequestDiff,
      useUpdateQuoteItem,
      useBulkUpdateQuoteItems,
      useCreateQuoteItem,
      useDeleteQuoteItem,
      useSetQuoteDeliveryBasis,
      useClaimDeal,
    ].forEach((hook) => setHook(hook, mkMutation()));
  });

  describe('RequestDetailPage — seller margin column', () => {
    beforeEach(() => {
      setHook(useDeal, { data: pageDeal, isLoading: false, isError: false, refetch: vi.fn() });
    });

    it('renders «—» instead of a false «0.0%» when the endpoint carries no real per-line margin', () => {
      renderWithProviders(<RequestDetailPage dealId={42} onBack={() => {}} />);

      // The bug rendered «0%» (or «0.0%») for the zero-valued line — neither may appear.
      expect(screen.queryByText('0%')).toBeNull();
      expect(screen.queryByText('0.0%')).toBeNull();
      // The zero-margin line shows a truthful em-dash placeholder instead.
      expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    });

    it('still renders a genuine non-zero per-line margin as a percentage', () => {
      renderWithProviders(<RequestDetailPage dealId={42} onBack={() => {}} />);

      expect(screen.getByText('18.5%')).toBeInTheDocument();
    });
  });

  describe('QuoteBuilderGrid — marginCell is read-only', () => {
    beforeEach(() => {
      setHook(useDeal, { data: gridDeal, isLoading: false });
      setHook(useQuoteItems, { data: [gridItem], isLoading: false });
    });

    it('renders the per-line margin as read-only text (a span with a hint icon), never an input', () => {
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      const marginEl = screen.getByText('17%');
      // Read-only affordance: a <span>, not an editable field, and not wrapped in one.
      expect(marginEl.tagName).toBe('SPAN');
      expect(marginEl.closest('input')).toBeNull();
      // The «Настройки КП» hint icon lives inside the cell (icon-подсказка).
      expect(marginEl.querySelector('svg')).not.toBeNull();
    });

    it('does not accept input for the margin while editable fields (quantity) remain inputs', () => {
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      // No input element holds the margin value — it is purely derived/displayed…
      expect(screen.queryByDisplayValue('17')).toBeNull();
      // …while genuinely editable fields (quantity) are still rendered as inputs.
      expect(screen.getByDisplayValue('1')).toBeInTheDocument();
    });
  });
});
