import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal } from '@/api/crmApi';
import { RequestDetailPage } from '../index';

/**
 * FIX-67 — кнопки создания КП на карточке заявки, каждая комбинация прав и строк.
 *
 * Дефект прода: «Создать КП» прятали при праве на цены, а «Взять в работу и подготовить» показывали на
 * любой заявке без КП (на заявке без строк она кончалась отказом). Правило теперь:
 *  • «Создать КП» — всегда, пока КП не начато и есть право `quote.edit_pricing`;
 *  • «Взять в работу и подготовить КП» — только если у заявки есть строки;
 *  • нет права — нет ни одной из двух.
 */
let permissions: string[] = [];
let deal: Deal;

const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

vi.mock('@/hooks/useCapabilities', () => ({
  useIsSoloTeam: () => false,
  useHasCompanyPermission: (code: string) => permissions.includes(code),
}));
vi.mock('@/hooks/useCRM', () => ({
  useDeal: () => ({ data: deal, isLoading: false, isError: false, refetch: vi.fn() }),
  useChangeDealStage: () => idle,
  useSendQuoteToClient: () => idle,
  useClaimDeal: () => idle,
  useReleaseDeal: () => idle,
  useTakeAndPrepareQuote: () => idle,
  useSubmitQuoteForReview: () => idle,
}));
vi.mock('../RequestHeader', () => ({ RequestHeader: () => null }));
vi.mock('../QuoteView', () => ({ QuoteView: () => null }));
vi.mock('@/components/Sourcing/DealAttachmentsPanel', () => ({ DealAttachmentsPanel: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/DealTimeline', () => ({ DealTimeline: () => null }));
vi.mock('@/components/CRM/DealDocumentsCard', () => ({ DealDocumentsCard: () => null }));
vi.mock('@/components/CRM/DealChainCard', () => ({ DealChainCard: () => null }));
vi.mock('@/components/CRM/DealMarginDeviationCard', () => ({ DealMarginDeviationCard: () => null }));

const CREATE = { name: 'Создать КП' };
const TAKE_AND_PREPARE = { name: 'Взять в работу и подготовить КП' };
const CLAIM = { name: 'Взять в работу' };

function makeDeal(overrides: Partial<Deal>): Deal {
  return {
    id: 7,
    stage_code: 'SOURCING',
    assigned_to: null,
    active_quote: null,
    quotes: [],
    notes: '',
    request_lines_count: 0,
    created_at: '2026-10-21T08:00:00Z',
    ...overrides,
  } as Deal;
}

function renderPage() {
  return renderWithProviders(<RequestDetailPage dealId={7} onBack={() => undefined} />);
}

describe('карточка заявки — кнопки создания КП', () => {
  beforeEach(() => {
    permissions = ['deal.manage', 'quote.edit_pricing', 'quote.build'];
  });

  it.each([
    // [право на цены, строк в заявке, «Создать КП», «Взять в работу и подготовить»]
    [true, 0, true, false],
    [true, 3, true, true],
    [false, 0, false, false],
    [false, 3, false, false],
  ])('право на цены=%s, строк=%i → «Создать КП»=%s, «Взять и подготовить»=%s', (
    canPrice, lines, create, takeAndPrepare,
  ) => {
    permissions = canPrice ? ['deal.manage', 'quote.edit_pricing', 'quote.build'] : ['deal.manage'];
    deal = makeDeal({ request_lines_count: lines });
    renderPage();

    expect(!!screen.queryByRole('button', CREATE)).toBe(create);
    expect(!!screen.queryByRole('button', TAKE_AND_PREPARE)).toBe(takeAndPrepare);
  });

  it.each(['RFQ_OPEN', 'SOURCING', 'CALCULATING'])('«Создать КП» есть на стадии %s, пока КП не начато', (stage) => {
    deal = makeDeal({ stage_code: stage, request_lines_count: 0 });
    renderPage();
    expect(screen.getByRole('button', CREATE)).toBeInTheDocument();
  });

  it('заявка словами: «Взять в работу» и «Создать КП», без «Взять в работу и подготовить»', () => {
    deal = makeDeal({ notes: 'Нужны рельсы Р65, 500 тонн', request_text: 'Нужны рельсы Р65, 500 тонн', request_lines_count: 0 });
    renderPage();

    expect(screen.getByRole('button', CLAIM)).toBeInTheDocument();
    expect(screen.getByRole('button', CREATE)).toBeInTheDocument();
    expect(screen.queryByRole('button', TAKE_AND_PREPARE)).not.toBeInTheDocument();
    expect(screen.getByText('Нужны рельсы Р65, 500 тонн')).toBeInTheDocument();
  });

  it('КП уже собирают (черновик с суммой) — кнопок создания нет', () => {
    deal = makeDeal({
      request_lines_count: 2,
      active_quote: { id: 3, status_code: 'DRAFT', total_incl_vat: '1500.00', items: [] } as unknown as Deal['active_quote'],
    });
    renderPage();

    expect(screen.queryByRole('button', CREATE)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', TAKE_AND_PREPARE)).not.toBeInTheDocument();
  });

  it('заявка на стадии «Черновик» — сначала «К подбору», кнопок создания КП нет', () => {
    deal = makeDeal({ stage_code: 'DRAFT', request_lines_count: 2 });
    renderPage();

    expect(screen.getByRole('button', { name: 'К подбору' })).toBeInTheDocument();
    expect(screen.queryByRole('button', CREATE)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', TAKE_AND_PREPARE)).not.toBeInTheDocument();
  });
});
