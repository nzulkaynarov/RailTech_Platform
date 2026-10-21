import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal } from '@/api/crmApi';

/**
 * FIX-67 — заявка словами в конструкторе КП: пустой черновик с текстом заявки рядом (раскрыт, виден при
 * наборе строк) и кнопка «Разобрать текст в строки (ИИ)». Без ИИ — понятный текст, а не ошибка сервера.
 */
const ref = vi.hoisted(() => ({
  permissions: ['quote.edit_pricing'] as string[],
  deal: {} as Record<string, unknown>,
  parse: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock('@/hooks/useCRM', () => ({
  useDeal: () => ({ data: ref.deal as unknown as Deal, isLoading: false, isError: false, refetch: vi.fn() }),
  useSendQuoteToClient: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateQuoteSettings: () => ({ mutate: vi.fn(), isPending: false }),
  useTakeAndPrepareQuote: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (s: { capabilities: { permissions: string[] } }) => unknown) =>
    selector({ capabilities: { permissions: ref.permissions } }),
}));
vi.mock('@/api/crmApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/crmApi')>();
  return { ...original, crmApi: { ...original.crmApi, parseRequestText: ref.parse } };
});
vi.mock('sonner', () => ({ toast: { error: ref.toastError, success: ref.toastSuccess, warning: vi.fn() } }));
vi.mock('@/components/QuoteBuilder/QuoteBuilderGrid', () => ({ QuoteBuilderGrid: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteApprovalChain', () => ({ QuoteApprovalChain: () => null }));
vi.mock('@/components/CRM/GenerateContractDialog', () => ({ GenerateContractDialog: () => null }));
vi.mock('@/components/CRM/QuoteSentPanel', () => ({ QuoteSentPanel: () => null }));
vi.mock('@/components/CRM/SendQuoteDialog', () => ({ SendQuoteDialog: () => null }));

import { DealQuotePage } from '@/pages/DealQuotePage';

const TEXT = 'Нужны рельсы Р65, 500 тонн, и накладки к ним';
const PARSE = { name: 'Разобрать текст в строки (ИИ)' };

function dealWith(overrides: Record<string, unknown>) {
  return {
    id: 42, title: 'Заявка', stage_code: 'CALCULATING', stage_name: 'Расчёт', notes: TEXT, request_text: TEXT,
    request_lines_count: 0,
    active_quote: { id: 100, deal: 42, version: 1, status_code: 'DRAFT', status_name: 'DRAFT', items: [], economics: null },
    ...overrides,
  };
}

describe('конструктор КП — заявка словами', () => {
  beforeEach(() => {
    ref.permissions = ['quote.edit_pricing'];
    ref.deal = dealWith({});
    ref.parse.mockReset();
    ref.toastError.mockReset();
    ref.toastSuccess.mockReset();
  });

  it('текст заявки раскрыт целиком рядом с пустым черновиком, кнопка разбора на месте', () => {
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);

    const text = screen.getByTestId('request-text');
    expect(text).toHaveTextContent(TEXT);
    expect(text.className).not.toMatch(/line-clamp/);
    expect(screen.getByRole('button', PARSE)).toBeInTheDocument();
  });

  it('заявка со строками: текст свёрнут в одну строку, кнопки разбора нет', () => {
    ref.deal = dealWith({ request_lines_count: 3 });
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);

    expect(screen.getByTestId('request-text').className).toMatch(/line-clamp-1/);
    expect(screen.queryByRole('button', PARSE)).not.toBeInTheDocument();
  });

  it('без права на цены кнопки разбора нет', () => {
    ref.permissions = [];
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);

    expect(screen.queryByRole('button', PARSE)).not.toBeInTheDocument();
  });

  it('разбор: сервер вернул строки — радость; ИИ выключен — понятный текст, а не сырой код', async () => {
    const user = userEvent.setup();
    ref.parse.mockResolvedValueOnce({ added: 2, recognized: 2, truncated: false, quote_id: 100 });
    renderWithProviders(<DealQuotePage dealId={42} onBack={vi.fn()} />);

    await user.click(screen.getByRole('button', PARSE));
    await waitFor(() => expect(ref.toastSuccess).toHaveBeenCalledWith('Добавлено 2 строки из текста заявки'));
    expect(ref.parse).toHaveBeenCalledWith(100);

    ref.parse.mockRejectedValueOnce({ response: { status: 503, data: { detail: 'AI_DISABLED' } } });
    await user.click(screen.getByRole('button', PARSE));
    await waitFor(() =>
      expect(ref.toastError).toHaveBeenCalledWith('ИИ сейчас недоступен. Наберите строки вручную по тексту заявки.'),
    );
  });
});
