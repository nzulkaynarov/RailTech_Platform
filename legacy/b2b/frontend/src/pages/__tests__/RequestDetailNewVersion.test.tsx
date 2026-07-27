import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { RequestDetailPage } from '@/pages/RequestDetailPage';

/**
 * WP-B2 — after the buyer rejects the КП the seller was stuck in a тупик: an
 * active_quote existed so the build button was hidden and no «new version»
 * action existed anywhere. These tests pin the fix: the primary «Создать новую
 * версию» button shows for a seller when active_quote is REJECTED, and stays
 * hidden while the КП is merely SENT.
 */

// Mutable deal state fed to the mocked useDeal (hoisted so the vi.mock factory
// can close over it; each test sets `dealRef.quoteStatus`).
const dealRef = vi.hoisted(() => ({ quoteStatus: 'REJECTED' as string }));

function mutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };
}

vi.mock('@/hooks/useCRM', () => ({
  useDeal: () => ({
    data: {
      id: 7,
      title: 'Заявка №7',
      stage_code: 'QUOTE_SENT',
      stage_name: 'КП отправлено',
      can_edit_request: false,
      assigned_to: 1,
      target_sellers_data: [],
      notes: '',
      client_name: 'ООО Клиент',
      company_name: 'ООО Клиент',
      active_quote: {
        id: 55,
        deal: 7,
        version: 1,
        status_code: dealRef.quoteStatus,
        status_name: dealRef.quoteStatus,
        items: [],
        subtotal_excl_vat: '100',
        vat_amount: '12',
        charges_total: '0',
        vat_rate: '12',
        total_incl_vat: '112',
        notes: '',
        created_at: '2026-07-01T10:00:00Z',
      },
      quotes: [],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useChangeDealStage: () => mutation(),
  useApproveQuote: () => mutation(),
  useRejectQuote: () => mutation(),
  useSendQuoteToClient: () => mutation(),
  useUpdateRequestMeta: () => mutation(),
  usePreflightCheck: () => mutation(),
  useQuoteRequestDiff: () => mutation(),
  useClaimDeal: () => mutation(),
  useTakeAndPrepareQuote: () => mutation(),
}));

vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (s: { activeStatus: string }) => unknown) =>
    selector({ activeStatus: 'SELLER' }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (s: { format: (v: number) => string }) => unknown) =>
    selector({ format: (v: number) => String(v) }),
}));
vi.mock('@/hooks/useViewerMode', () => ({ useIsViewerMode: () => false }));

// Heavy children irrelevant to the button under test → inert stubs.
vi.mock('@/components/Sourcing/DealChatPanel', () => ({ DealChatPanel: () => null }));
vi.mock('@/components/CRM/DealTimeline', () => ({ DealTimeline: () => null }));
vi.mock('@/components/CRM/DealDocumentsCard', () => ({ DealDocumentsCard: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/RejectQuoteDialog', () => ({ RejectQuoteDialog: () => null }));
vi.mock('@/components/Admin/ConfirmActionDialog', () => ({ ConfirmActionDialog: () => null }));
vi.mock('@/components/CRM/RequestItemsEditor', () => ({ RequestItemsEditor: () => null }));
vi.mock('@/components/CRM/PreflightWarnings', () => ({ PreflightWarnings: () => null }));
vi.mock('@/components/CRM/CoverageCheck', () => ({ CoverageCheck: () => null }));

describe('RequestDetailPage — new КП version after rejection', () => {
  beforeEach(() => {
    dealRef.quoteStatus = 'REJECTED';
  });

  it('shows the «new version» button for a seller when the КП is REJECTED', () => {
    dealRef.quoteStatus = 'REJECTED';
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);

    expect(
      screen.getByRole('button', { name: 'Создать новую версию' }),
    ).toBeInTheDocument();
  });

  it('hides the «new version» button while the КП is only SENT', () => {
    dealRef.quoteStatus = 'SENT';
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);

    expect(
      screen.queryByRole('button', { name: 'Создать новую версию' }),
    ).not.toBeInTheDocument();
  });
});
