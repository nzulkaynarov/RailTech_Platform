import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import {
  SellerAttentionStrip,
  BuyerAttentionStrip,
  PipelineFunnel,
  MetricStrip,
} from '../DashboardWidgets';
import { crmApi, type Deal, type Quote } from '@/api/crmApi';
import { contractsApi, type Contract, type ContractStatus } from '@/api/contractsApi';
import type { DashboardStats } from '@/api/dashboardApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the widgets' real react-query hooks
// (useDeals/useQuotes/useMyApprovalQueue/useDealStages/useContracts) run
// against these mocked api modules.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: {
      ...actual.crmApi,
      getDeals: vi.fn(),
      getQuotes: vi.fn(),
      getMyApprovalQueue: vi.fn(),
      getDealStages: vi.fn(),
    },
  };
});

vi.mock('@/api/contractsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/contractsApi')>();
  return {
    ...actual,
    contractsApi: { ...actual.contractsApi, list: vi.fn() },
  };
});

function makeDeal(id: number, stageCode: string): Deal {
  return { id, stage_code: stageCode, created_at: '2026-07-01T10:00:00Z' };
}

function makeQuote(id: number, statusCode: string, validUntil: string | null): Quote {
  return {
    id,
    deal: id,
    version: 1,
    status: 1,
    status_code: statusCode,
    status_name: 'display-only',
    items: [],
    subtotal_excl_vat: '0',
    vat_amount: '0',
    total_incl_vat: '0',
    valid_until: validUntil,
    created_at: '2026-07-01T10:00:00Z',
  };
}

function makeContract(id: number, status: ContractStatus): Contract {
  return {
    id,
    deal: id,
    quote: id,
    number: `C-${id}`,
    status,
    total_amount: '0',
    currency: null,
    pdf_file: null,
    pdf_url: null,
    signed_file: null,
    signed_file_url: null,
    client_signer: null,
    client_signer_name: null,
    client_signed_at: null,
    manager_signer: null,
    manager_signer_name: null,
    manager_signed_at: null,
    valid_from: null,
    valid_until: null,
    notes: '',
    created_at: '2026-07-01T10:00:00Z',
    updated_at: '2026-07-01T10:00:00Z',
  };
}

/** The clickable tile that owns a given attention label. */
async function findTile(label: string): Promise<HTMLElement> {
  const tile = (await screen.findByText(label)).closest('button');
  if (!tile) throw new Error(`no tile button for "${label}"`);
  return tile;
}

beforeEach(() => {
  vi.mocked(crmApi.getDeals).mockReset().mockResolvedValue([]);
  vi.mocked(crmApi.getQuotes).mockReset().mockResolvedValue([]);
  vi.mocked(crmApi.getMyApprovalQueue).mockReset().mockResolvedValue([]);
  vi.mocked(crmApi.getDealStages).mockReset().mockResolvedValue([]);
  vi.mocked(contractsApi.list).mockReset().mockResolvedValue([]);
});

describe('SellerAttentionStrip', () => {
  it('derives urgency counts by stage/status CODE (never by translated name)', async () => {
    // 3 of 5 deals sit in PRE_KP stages (RFQ_OPEN / SOURCING / CALCULATING).
    vi.mocked(crmApi.getDeals).mockResolvedValue([
      makeDeal(1, 'RFQ_OPEN'),
      makeDeal(2, 'SOURCING'),
      makeDeal(3, 'CALCULATING'),
      makeDeal(4, 'QUOTE_SENT'),
      makeDeal(5, 'CLOSED_WON'),
    ]);
    // Expired = ACTIVE status + valid_until in the past. REJECTED and future/None don't count.
    vi.mocked(crmApi.getQuotes).mockResolvedValue([
      makeQuote(10, 'SENT', '2020-01-01'),
      makeQuote(11, 'DRAFT', '2020-01-01'),
      makeQuote(12, 'SENT', '2999-01-01'),
      makeQuote(13, 'REJECTED', '2020-01-01'),
      makeQuote(14, 'SENT', null),
    ]);
    vi.mocked(crmApi.getMyApprovalQueue).mockResolvedValue([
      makeQuote(20, 'PENDING_APPROVAL', null),
      makeQuote(21, 'PENDING_APPROVAL', null),
    ]);
    vi.mocked(contractsApi.list).mockResolvedValue([makeContract(30, 'PENDING_MANAGER')]);

    renderWithProviders(<SellerAttentionStrip onNavigate={vi.fn()} />);

    // Labels resolve from the real ru.json; counts are code-derived.
    await waitFor(async () =>
      expect(within(await findTile('Заявки без КП')).getByText('3')).toBeInTheDocument(),
    );
    expect(within(await findTile('Истёкшие КП')).getByText('2')).toBeInTheDocument();
    expect(within(await findTile('КП на утверждении')).getByText('2')).toBeInTheDocument();
    expect(within(await findTile('Договоры на подписи')).getByText('1')).toBeInTheDocument();
    // Seller strip asks for contracts pending the MANAGER signature (code, not name).
    expect(contractsApi.list).toHaveBeenCalledWith({ status: 'PENDING_MANAGER' });
  });

  it('navigates to the owning page when an active tile is clicked', async () => {
    vi.mocked(crmApi.getDeals).mockResolvedValue([makeDeal(1, 'RFQ_OPEN')]);
    const onNavigate = vi.fn();
    renderWithProviders(<SellerAttentionStrip onNavigate={onNavigate} />);

    const tile = await findTile('Заявки без КП');
    await waitFor(() => expect(tile).toBeEnabled());
    fireEvent.click(tile);
    expect(onNavigate).toHaveBeenCalledWith('crm-deals');
  });

  it('disables tiles with a zero count so they cannot navigate', async () => {
    const onNavigate = vi.fn();
    renderWithProviders(<SellerAttentionStrip onNavigate={onNavigate} />);

    const tile = await findTile('Заявки без КП');
    expect(tile).toBeDisabled();
    fireEvent.click(tile);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

describe('BuyerAttentionStrip', () => {
  it('counts only SENT quotes as "КП к рассмотрению" and asks for PENDING_CLIENT contracts', async () => {
    vi.mocked(crmApi.getQuotes).mockResolvedValue([
      makeQuote(1, 'SENT', null),
      makeQuote(2, 'SENT', null),
      makeQuote(3, 'DRAFT', null),
      makeQuote(4, 'ACCEPTED', null),
    ]);
    vi.mocked(contractsApi.list).mockResolvedValue([makeContract(9, 'PENDING_CLIENT')]);
    const onNavigate = vi.fn();

    renderWithProviders(<BuyerAttentionStrip onNavigate={onNavigate} />);

    await waitFor(async () =>
      expect(within(await findTile('КП к рассмотрению')).getByText('2')).toBeInTheDocument(),
    );
    expect(within(await findTile('Договоры на подписи')).getByText('1')).toBeInTheDocument();
    expect(contractsApi.list).toHaveBeenCalledWith({ status: 'PENDING_CLIENT' });

    fireEvent.click(await findTile('КП к рассмотрению'));
    expect(onNavigate).toHaveBeenCalledWith('my-requests');
  });
});

describe('PipelineFunnel', () => {
  it('renders stages in backend order, omits empty stages, and drills into deals', async () => {
    vi.mocked(crmApi.getDealStages).mockResolvedValue([
      { code: 'RFQ_OPEN', name: 'Заявка открыта' },
      { code: 'SOURCING', name: 'Проработка' },
      { code: 'CALCULATING', name: 'Расчёт' },
      { code: 'QUOTE_SENT', name: 'КП отправлено' },
    ]);
    vi.mocked(crmApi.getDeals).mockResolvedValue([
      makeDeal(1, 'RFQ_OPEN'),
      makeDeal(2, 'RFQ_OPEN'),
      makeDeal(3, 'SOURCING'),
      makeDeal(4, 'QUOTE_SENT'),
    ]);
    const onNavigate = vi.fn();

    const { container } = renderWithProviders(<PipelineFunnel onNavigate={onNavigate} />);

    expect(await screen.findByText('Воронка сделок')).toBeInTheDocument();
    // Zero-count stage is filtered out entirely.
    expect(screen.queryByText('Расчёт')).not.toBeInTheDocument();
    // Server (sort_order) ordering is preserved.
    const text = container.textContent ?? '';
    expect(text.indexOf('Заявка открыта')).toBeLessThan(text.indexOf('Проработка'));
    expect(text.indexOf('Проработка')).toBeLessThan(text.indexOf('КП отправлено'));

    const legendEntry = screen.getByText('Заявка открыта').closest('button');
    if (!legendEntry) throw new Error('no legend button');
    expect(within(legendEntry).getByText('2')).toBeInTheDocument();
    fireEvent.click(legendEntry);
    expect(onNavigate).toHaveBeenCalledWith('crm-deals');
  });

  it('renders nothing when there are no deals', async () => {
    vi.mocked(crmApi.getDealStages).mockResolvedValue([
      { code: 'RFQ_OPEN', name: 'Заявка открыта' },
    ]);
    const { container } = renderWithProviders(<PipelineFunnel onNavigate={vi.fn()} />);

    await waitFor(() => expect(crmApi.getDeals).toHaveBeenCalled());
    expect(screen.queryByText('Воронка сделок')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});

describe('MetricStrip', () => {
  const stats: DashboardStats = {
    deals_volume: 5_000_000,
    deals_volume_change: 0,
    active_requests: 4,
    active_requests_change: 0,
    catalog_items: 120,
    catalog_items_change: 0,
    clients_count: 7,
    clients_count_change: 0,
    deals_by_month: [],
    activity_by_day: [],
    top_products: [],
    counterparties: { manufacturers: 0, buyers: 0, intermediaries: 0 },
    request_completion: 0,
    request_completion_goal: 0,
    deals_in_progress: 2,
    quotes_received: 5,
    deals_completed: 3,
  };

  it('shows the seller metric set with localized labels', () => {
    renderWithProviders(<MetricStrip stats={stats} role="seller" />);

    expect(screen.getByText('Объём сделок')).toBeInTheDocument();
    const activeRequestsMetric = screen.getByText('Активные заявки').parentElement;
    if (!activeRequestsMetric) throw new Error('no metric wrapper');
    expect(within(activeRequestsMetric).getByText('4')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument(); // catalog items
    expect(screen.getByText('7')).toBeInTheDocument(); // clients
    // Buyer-only metric is absent from the seller strip.
    expect(screen.queryByText('КП получено')).not.toBeInTheDocument();
  });

  it('shows the buyer metric set', () => {
    renderWithProviders(<MetricStrip stats={stats} role="buyer" />);

    expect(screen.getByText('Активные заявки')).toBeInTheDocument();
    expect(screen.getByText('КП получено')).toBeInTheDocument();
    expect(screen.getByText('Завершено')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument(); // quotes received
    expect(screen.getByText('3')).toBeInTheDocument(); // completed
    expect(screen.queryByText('Объём сделок')).not.toBeInTheDocument();
  });

  it('renders zeros when stats have not loaded yet', () => {
    renderWithProviders(<MetricStrip stats={null} role="buyer" />);

    // Three buyer metrics, all falling back to 0.
    expect(screen.getAllByText('0')).toHaveLength(3);
  });
});
