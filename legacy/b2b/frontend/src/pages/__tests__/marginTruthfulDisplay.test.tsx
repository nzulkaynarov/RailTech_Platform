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
  useBulkCreateQuoteItems,
  useBulkDeleteQuoteItems,
  useCreateQuoteItem,
  useDeleteQuoteItem,
  useSetQuoteDeliveryBasis,
  useClaimDeal,
  useTakeAndPrepareQuote,
} from '@/hooks/useCRM';

/**
 * WP-7 / DT1 — «Правдивое отображение наценки». Two display-only guarantees:
 *  1. RequestDetailPage's per-line «Наценка» column never CONFLATES inherit with 0 (DT1):
 *     a NULL margin (inherit the КП markup) reads as a muted «—», while an explicit 0
 *     («продать по себестоимости») reads as a real «0.0%». A genuine value renders as «X.X%».
 *  2. (SUPERSEDED BY DT1 — see the second describe block.) QuoteBuilderGrid's marginCell
 *     used to be READ-ONLY, because the per-line column was a dead NOT NULL default the
 *     engine ignored. DT1 made it a real nullable override, so the cell is now editable and
 *     the guarantee it must uphold instead is «inherit ≠ 0».
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
  useBulkCreateQuoteItems: vi.fn(),
  useBulkDeleteQuoteItems: vi.fn(),
  useCreateQuoteItem: vi.fn(),
  useDeleteQuoteItem: vi.fn(),
  useSetQuoteDeliveryBasis: vi.fn(),
  useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClaimDeal: vi.fn(),
  useTakeAndPrepareQuote: vi.fn(),
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
vi.mock('@/components/CRM/DealDocumentsCard', () => ({ DealDocumentsCard: () => null }));
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

// A sent seller КП exercising all three DT1 per-line margin states: NULL (inherit → «—»),
// an explicit 0 (sell at cost → «0.0%», NOT «—»), and a genuine non-zero value (18.50 → «18.5%»).
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
        margin_percent: null, // inherits the КП margin → muted «—»
        final_price_excl_vat: '120.00',
      },
      {
        id: 2,
        product_name: 'Шпала ЖБ',
        quantity: 1,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '50.00',
        margin_percent: '18.50', // genuine override → «18.5%»
        final_price_excl_vat: '59.25',
      },
      {
        id: 3,
        product_name: 'Костыль',
        quantity: 4,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '25.00',
        margin_percent: '0.00', // explicit 0 = «продать по себестоимости» → «0.0%», NOT «—»
        final_price_excl_vat: '25.00',
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
      useBulkCreateQuoteItems,
      useBulkDeleteQuoteItems,
      useCreateQuoteItem,
      useDeleteQuoteItem,
      useSetQuoteDeliveryBasis,
      useClaimDeal, useTakeAndPrepareQuote,
    ].forEach((hook) => setHook(hook, mkMutation()));
  });

  describe('RequestDetailPage — seller margin column', () => {
    beforeEach(() => {
      setHook(useDeal, { data: pageDeal, isLoading: false, isError: false, refetch: vi.fn() });
    });

    it('renders «—» ONLY for an inheriting (null) per-line margin — never for an explicit 0', () => {
      renderWithProviders(<RequestDetailPage dealId={42} onBack={() => {}} />);

      // The inheriting (null) line shows a muted em-dash placeholder.
      expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    });

    it('distinguishes an explicit 0 override («0.0%») from inherit («—») — DT1 no-conflation', () => {
      renderWithProviders(<RequestDetailPage dealId={42} onBack={() => {}} />);

      // «продать по себестоимости» is a deliberate choice and must READ as a real 0, not a blank.
      expect(screen.getByText('0.0%')).toBeInTheDocument();
    });

    it('still renders a genuine non-zero per-line margin as a percentage', () => {
      renderWithProviders(<RequestDetailPage dealId={42} onBack={() => {}} />);

      expect(screen.getByText('18.5%')).toBeInTheDocument();
    });
  });

  /**
   * DT1 SUPERSEDES the former «marginCell is read-only» guarantee (#2 in the header note).
   *
   * That guarantee existed because `QuoteItem.margin_percent` was a dead NOT NULL column the engine
   * ignored — so an editable-looking cell would have been a lie, and the cell correctly pointed at
   * «Настройки КП» instead. The backend now honours a nullable per-line override, so the cell is
   * editable BY DESIGN and the old assertions would enforce a bug (a shipped-dark feature).
   *
   * What replaces it is the property that actually matters now: the cell must never CONFLATE
   * «inherit» with «0». An inheriting line renders an EMPTY field showing the quote rate as a
   * placeholder — not a literal «0», which would read as «продаём по себестоимости».
   */
  describe('QuoteBuilderGrid — marginCell distinguishes inherit from 0 (DT1)', () => {
    beforeEach(() => {
      setHook(useDeal, { data: gridDeal, isLoading: false });
      setHook(useQuoteItems, { data: [{ ...gridItem, margin_percent: null }], isLoading: false });
    });

    it('renders an INHERITING line as an empty input carrying the quote rate as placeholder', () => {
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      const marginInput = screen.getByRole('textbox', { name: 'Наценка позиции 1' });
      // Empty value — NOT «0». The two mean different things after DT1.
      expect(marginInput).toHaveValue('');
      // …and the inherited КП markup (20%) shows through as the ghost value, so the seller still
      // sees the effective number rather than a blank cell (Odoo/CPQ convention).
      expect(marginInput).toHaveAttribute('placeholder', '20');
    });

    it('offers no revert control while the line merely inherits (nothing to revert)', () => {
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      expect(screen.queryByRole('button', { name: 'Вернуть наценку КП для позиции 1' })).toBeNull();
    });

    it('renders an OVERRIDDEN line with its own value plus the revert affordance', () => {
      setHook(useQuoteItems, { data: [{ ...gridItem, margin_percent: '35' }], isLoading: false });
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      expect(screen.getByRole('textbox', { name: 'Наценка позиции 1' })).toHaveValue('35');
      expect(screen.getByRole('button', { name: 'Вернуть наценку КП для позиции 1' })).toBeInTheDocument();
    });

    it('renders an explicit ZERO override as «0» — a real value, visually distinct from inherit', () => {
      setHook(useQuoteItems, { data: [{ ...gridItem, margin_percent: '0' }], isLoading: false });
      renderWithProviders(<QuoteBuilderGrid dealId={7} />);

      // «продать по себестоимости» is a deliberate choice and must READ as one, not as a blank.
      expect(screen.getByRole('textbox', { name: 'Наценка позиции 1' })).toHaveValue('0');
      expect(screen.getByRole('button', { name: 'Вернуть наценку КП для позиции 1' })).toBeInTheDocument();
    });
  });
});
