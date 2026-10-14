import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal } from '@/api/crmApi';
import { RequestDetailPage } from '@/pages/RequestDetailPage';
import ru from '@/i18n/locales/ru.json';
import {
  useDeal,
  useChangeDealStage,
  useSendQuoteToClient,
  useClaimDeal,
  useReleaseDeal,
  useTakeAndPrepareQuote,
  useSubmitQuoteForReview,
} from '@/hooks/useCRM';

/**
 * Wave H — a SELLER's SOLO deal (calculator draft, `deal.company === null`) is a legitimate state
 * since Wave E / crm.0065. The deal-detail surface must render cleanly for it: no crash on the
 * null counterparty, an explicit «Без клиента (расчёт)» label instead of a blank line, and the
 * блок произвольных документов сделки still present so the seller is never dead-ended on their
 * own deal. Заголовок берётся ИЗ СЛОВАРЯ: блок переименован волной G7 («документы» значили две
 * разные вещи на одном экране), и тест обязан держать ПРИСУТСТВИЕ блока, а не его название.
 *
 * It also pins the DT1 per-line margin distinction in this exact (solo) context: an inheriting
 * (null) line reads «—», an explicit-0 line reads «0.0%».
 */

vi.mock('@/hooks/useCRM', () => ({
  useDeal: vi.fn(),
  // Хаб цепочки документов (F1) монтируется на карточке; в этих тестах он не предмет
  // проверки — отдаём пустой результат, чтобы блок молчал.
  useDealDocuments: vi.fn(() => ({ data: undefined, isLoading: false })),
  useChangeDealStage: vi.fn(),
  useSendQuoteToClient: vi.fn(),
  useClaimDeal: vi.fn(),
  useReleaseDeal: vi.fn(),
  useTakeAndPrepareQuote: vi.fn(),
  useSubmitQuoteForReview: vi.fn(),
}));

// A solo deal has no capabilities.is_solo_team in this fixture (undefined → false).
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (state: { capabilities: { permissions: string[] } }) => unknown) =>
    selector({ capabilities: { permissions: [] } }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (state: { format: (value: number) => string }) => unknown) =>
    selector({ format: (value: number) => `${value} сум` }),
}));

// The documents block is the surface under test — render it for real, but stub its data hook and
// the create wizard so the block shows without pulling in wizard machinery.
vi.mock('@/hooks/useDocuments', () => ({ useGeneratedDocuments: () => ({ data: [], isLoading: false }) }));
vi.mock('@/components/Documents/DocumentCreateWizard', () => ({ DocumentCreateWizard: () => null }));
vi.mock('@/components/Shared/DocumentActions', () => ({ DocumentActions: () => null }));

// Heavy siblings irrelevant to this surface → inert stubs.
vi.mock('@/components/CRM/DealTimeline', () => ({ DealTimeline: () => null }));
vi.mock('@/components/Shared/ConfirmActionDialog', () => ({ ConfirmActionDialog: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));

const setHook = (hook: unknown, value: unknown) => { (hook as Mock).mockReturnValue(value); };
const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });

// SOLO deal: NO buyer company / client / contact — every counterparty field is null.
const soloDeal = {
  id: 99,
  company: null,
  company_name: null,
  client_name: null,
  contact_name: null,
  title: 'Расчёт без клиента',
  stage_code: 'SOURCING',
  stage_name: 'Подбор',
  assigned_to: 7,
  quotes: [],
  active_quote: {
    id: 500,
    version: 1,
    status_code: 'DRAFT',
    status_name: 'Черновик',
    created_at: '2026-07-19T10:00:00Z',
    total_incl_vat: '1150.00',
    subtotal_excl_vat: '1150.00',
    vat_amount: '0.00',
    vat_rate: '0',
    charges_total: '0',
    notes: '',
    items: [
      {
        id: 1,
        imported_raw_name: 'Рельс Р65',
        quantity: 10,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '100.00',
        margin_percent: null, // inherits the КП margin → «—»
        final_price_excl_vat: '115.00',
      },
      {
        id: 2,
        imported_raw_name: 'Костыль',
        quantity: 50,
        unit: 'шт',
        offer_supplier_name: 'ООО Поставщик',
        frozen_base_price: '5.00',
        margin_percent: '0.00', // explicit 0 = продать по себестоимости → «0.0%»
        final_price_excl_vat: '5.00',
      },
    ],
  },
} as unknown as Deal;

describe('RequestDetailPage — seller SOLO deal (company === null)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    [
      useChangeDealStage, useSendQuoteToClient,
      useClaimDeal, useReleaseDeal, useTakeAndPrepareQuote,
      useSubmitQuoteForReview,
    ].forEach((hook) => setHook(hook, mkMutation()));
    setHook(useDeal, { data: soloDeal, isLoading: false, isError: false, refetch: vi.fn() });
  });

  it('renders without crashing and labels the missing counterparty explicitly', () => {
    renderWithProviders(<RequestDetailPage dealId={99} onBack={() => {}} />);

    // The page rendered (title present) and the null buyer reads as an intentional label.
    expect(screen.getByText('Расчёт без клиента')).toBeInTheDocument();
    expect(screen.getByText('Без клиента (расчёт)')).toBeInTheDocument();
  });

  it('still shows the free-form documents block for a solo deal', () => {
    renderWithProviders(<RequestDetailPage dealId={99} onBack={() => {}} />);

    expect(screen.getByText(ru.dealDocuments.title)).toBeInTheDocument();
  });

  it('distinguishes inherit («—») from an explicit-0 margin («0.0%») on the solo КП', () => {
    renderWithProviders(<RequestDetailPage dealId={99} onBack={() => {}} />);

    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('0.0%')).toBeInTheDocument();
  });
});
