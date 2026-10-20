import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { RequestDetailPage } from '@/pages/RequestDetailPage';

/**
 * FIX-58 / D-03 — «Наблюдатель» видит карточку сделки, но не кнопки действий: сервер ответит 403,
 * значит кнопка, которая не сработает, — шум. Кнопки прячутся по `capabilities.permissions` (тем же
 * кодам, что проверяет сервер), «Открыть КП» (просмотр) остаётся.
 */
const ref = vi.hoisted(() => ({ quoteStatus: 'DRAFT' as string, assignedTo: null as number | null, permissions: [] as string[] }));
const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false });

vi.mock('@/hooks/useCRM', () => ({
  useDealDocuments: vi.fn(() => ({ data: undefined, isLoading: false })),
  useDeal: () => ({
    data: {
      id: 7, title: 'Заявка №7', stage_code: 'CALCULATING', stage_name: 'Расчёт', assigned_to: ref.assignedTo,
      notes: '', client_name: 'ООО Клиент', company_name: 'ООО Клиент',
      active_quote: {
        id: 55, deal: 7, version: 1, status_code: ref.quoteStatus, status_name: ref.quoteStatus,
        items: [{ id: 1, imported_raw_name: 'Болт', quantity: 1, final_price_excl_vat: '100' }],
        subtotal_excl_vat: '100', vat_amount: '12', charges_total: '0', vat_rate: '12', total_incl_vat: '112',
        notes: '', created_at: '2026-07-01T10:00:00Z',
      },
      quotes: [],
    },
    isLoading: false, isError: false, refetch: vi.fn(),
  }),
  useChangeDealStage: () => mutation(),
  useSendQuoteToClient: () => mutation(),
  useClaimDeal: () => mutation(),
  useReleaseDeal: () => mutation(),
  useTakeAndPrepareQuote: () => mutation(),
  useSubmitQuoteForReview: () => mutation(),
}));
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (s: { capabilities: { permissions: string[] } }) => unknown) =>
    selector({ capabilities: { permissions: ref.permissions } }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (s: { format: (v: number) => string }) => unknown) =>
    selector({ format: (v: number) => String(v) }),
}));
vi.mock('@/components/CRM/DealTimeline', () => ({ DealTimeline: () => null }));
vi.mock('@/components/CRM/DealDocumentsCard', () => ({ DealDocumentsCard: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/Shared/ConfirmActionDialog', () => ({ ConfirmActionDialog: () => null }));

describe('RequestDetailPage — действия по правам (D-03)', () => {
  beforeEach(() => {
    ref.quoteStatus = 'DRAFT';
    ref.assignedTo = null;
    ref.permissions = [];
  });

  it('Наблюдатель: ни «Взять в работу», ни «Отправить на согласование», зато «Открыть КП» есть', () => {
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'На согласование' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть КП' })).toBeInTheDocument();
  });

  it('Наблюдатель: КП готово к отправке — кнопки «Отправить КП» нет', () => {
    ref.quoteStatus = 'READY_TO_SEND';
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Отправить КП' })).not.toBeInTheDocument();
  });

  it('контроль: расчётчик с правами видит те же кнопки', () => {
    ref.permissions = ['deal.manage', 'quote.build', 'quote.send', 'quote.edit_pricing'];
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Взять в работу' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'На согласование' })).toBeInTheDocument();
  });

  it('контроль: право quote.send возвращает «Отправить КП»', () => {
    ref.quoteStatus = 'READY_TO_SEND';
    ref.assignedTo = 3;
    ref.permissions = ['quote.send'];
    renderWithProviders(<RequestDetailPage dealId={7} onBack={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Отправить КП' })).toBeInTheDocument();
  });
});
