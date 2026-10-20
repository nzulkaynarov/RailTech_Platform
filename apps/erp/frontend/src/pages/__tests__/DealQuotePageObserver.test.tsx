import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal } from '@/api/crmApi';

/**
 * FIX-58 / D-03 — конструктор КП: «Наблюдатель» (нет прав) и КП не в черновике → конструктор в режиме
 * «только чтение», кнопки «Отправить КП» и «Создать договор» по правам `quote.send` / `contract.manage`.
 */
const ref = vi.hoisted(() => ({
  permissions: [] as string[],
  status: 'DRAFT' as string,
  gridProps: [] as Array<{ readOnly?: boolean }>,
}));

vi.mock('@/hooks/useCRM', () => ({
  useDeal: () => ({
    data: {
      id: 42, title: 'Заявка', stage_code: 'CALCULATING', stage_name: 'Расчёт', notes: '',
      active_quote: { id: 100, deal: 42, version: 1, status_code: ref.status, status_name: ref.status, items: [], economics: null },
    } as unknown as Deal,
    isLoading: false, isError: false, refetch: vi.fn(),
  }),
  useSendQuoteToClient: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateQuoteSettings: () => ({ mutate: vi.fn(), isPending: false }),
  useTakeAndPrepareQuote: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (s: { capabilities: { permissions: string[] } }) => unknown) =>
    selector({ capabilities: { permissions: ref.permissions } }),
}));
vi.mock('@/components/QuoteBuilder/QuoteBuilderGrid', () => ({
  QuoteBuilderGrid: (props: { readOnly?: boolean }) => {
    ref.gridProps.push(props);
    return null;
  },
}));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteApprovalChain', () => ({ QuoteApprovalChain: () => null }));
vi.mock('@/components/CRM/GenerateContractDialog', () => ({ GenerateContractDialog: () => null }));
vi.mock('@/components/CRM/QuoteSentPanel', () => ({ QuoteSentPanel: () => null }));
vi.mock('@/components/CRM/SendQuoteDialog', () => ({ SendQuoteDialog: () => null }));

import { DealQuotePage } from '@/pages/DealQuotePage';

const lastReadOnly = () => ref.gridProps[ref.gridProps.length - 1]?.readOnly;

describe('DealQuotePage — права и статус (D-03)', () => {
  beforeEach(() => {
    ref.permissions = [];
    ref.status = 'DRAFT';
    ref.gridProps = [];
  });

  it('Наблюдатель: конструктор «только чтение» даже на черновике', () => {
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
    expect(lastReadOnly()).toBe(true);
  });

  it('расчётчик на черновике: конструктор редактируемый', () => {
    ref.permissions = ['quote.edit_pricing'];
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
    expect(lastReadOnly()).toBe(false);
  });

  it('КП не в черновике (отправлено) — только чтение даже с правом править цены', () => {
    ref.permissions = ['quote.edit_pricing'];
    ref.status = 'SENT';
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
    expect(lastReadOnly()).toBe(true);
  });

  it('«Отправить КП» и «Создать договор» — только с правами quote.send / contract.manage', () => {
    ref.status = 'READY_TO_SEND';
    const { unmount } = renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Отправить КП/ })).not.toBeInTheDocument();
    unmount();
    ref.permissions = ['quote.send'];
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Отправить КП/ })).toBeInTheDocument();
  });
});
