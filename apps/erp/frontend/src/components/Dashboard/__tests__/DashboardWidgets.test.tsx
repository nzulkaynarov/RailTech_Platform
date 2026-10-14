import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import {
  AttentionStrip,
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
    viewer_can_sign_manager: false,
    valid_from: null,
    valid_until: null,
    invoice_id: null,
  wording_selections: {},
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

describe('AttentionStrip', () => {
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

    renderWithProviders(<AttentionStrip onNavigate={vi.fn()} />);

    // Labels resolve from the real ru.json; counts are code-derived.
    await waitFor(async () =>
      expect(within(await findTile('Заявки без КП')).getByText('3')).toBeInTheDocument(),
    );
    expect(within(await findTile('Истёкшие КП')).getByText('2')).toBeInTheDocument();
    expect(within(await findTile('КП на утверждении')).getByText('2')).toBeInTheDocument();
    expect(within(await findTile('Договоры на подписи')).getByText('1')).toBeInTheDocument();
    // The strip asks for contracts pending the MANAGER (back-office) signature (code, not name).
    expect(contractsApi.list).toHaveBeenCalledWith({ status: 'PENDING_MANAGER' });
  });

  it('navigates to the owning page when an active tile is clicked', async () => {
    vi.mocked(crmApi.getDeals).mockResolvedValue([makeDeal(1, 'RFQ_OPEN')]);
    const onNavigate = vi.fn();
    renderWithProviders(<AttentionStrip onNavigate={onNavigate} />);

    const tile = await findTile('Заявки без КП');
    await waitFor(() => expect(tile).toBeEnabled());
    fireEvent.click(tile);
    expect(onNavigate).toHaveBeenCalledWith('crm-deals');
  });

  it('disables tiles with a zero count so they cannot navigate', async () => {
    const onNavigate = vi.fn();
    renderWithProviders(<AttentionStrip onNavigate={onNavigate} />);

    const tile = await findTile('Заявки без КП');
    expect(tile).toBeDisabled();
    fireEvent.click(tile);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

describe('PipelineFunnel', () => {
  it('renders stages in backend order, omits empty stages, and drills into deals', async () => {
    // DT5: the DB `name` is translated-at-rest (RU-only), so the funnel must label by
    // CODE via DEAL_STAGE_LABEL_KEY. Sentinel names below deliberately differ from the
    // real ru.json labels — if one of them renders, the raw-name bug is back.
    vi.mocked(crmApi.getDealStages).mockResolvedValue([
      { code: 'RFQ_OPEN', name: 'DB-NAME-RFQ' },
      { code: 'SOURCING', name: 'DB-NAME-SOURCING' },
      { code: 'CALCULATING', name: 'DB-NAME-CALCULATING' },
      { code: 'QUOTE_SENT', name: 'DB-NAME-QUOTE-SENT' },
    ]);
    vi.mocked(crmApi.getDeals).mockResolvedValue([
      makeDeal(1, 'RFQ_OPEN'),
      makeDeal(2, 'RFQ_OPEN'),
      makeDeal(3, 'SOURCING'),
      makeDeal(4, 'QUOTE_SENT'),
    ]);
    const onNavigate = vi.fn();

    const { container } = renderWithProviders(<PipelineFunnel onNavigate={onNavigate} />);

    // Ждём именно данные, а не заголовок: карточка держит заголовок и на скелете, чтобы
    // не прыгать при загрузке (U2).
    expect(await screen.findByText('Заявка открыта')).toBeInTheDocument();
    // Zero-count stage is filtered out entirely (CALCULATING has no deals).
    expect(screen.queryByText('Расчёт')).not.toBeInTheDocument();
    const text = container.textContent ?? '';
    // DT5: labels come from ru.json by code — the RU-only DB names never reach the DOM.
    expect(text).not.toMatch(/DB-NAME-/);
    // Server (sort_order) ordering is preserved.
    expect(text.indexOf('Заявка открыта')).toBeLessThan(text.indexOf('Закупка'));
    expect(text.indexOf('Закупка')).toBeLessThan(text.indexOf('КП отправлено'));

    const legendEntry = screen.getByText('Заявка открыта').closest('button');
    if (!legendEntry) throw new Error('no legend button');
    expect(within(legendEntry).getByText('2')).toBeInTheDocument();
    fireEvent.click(legendEntry);
    // Клик по сегменту ведёт в очередь сделок бэк-офиса.
    expect(onNavigate).toHaveBeenCalledWith('crm-deals');
  });

  it('renders nothing when there are no deals', async () => {
    vi.mocked(crmApi.getDealStages).mockResolvedValue([
      { code: 'RFQ_OPEN', name: 'Заявка открыта' },
    ]);
    vi.mocked(crmApi.getDeals).mockResolvedValue([]);
    const { container } = renderWithProviders(<PipelineFunnel onNavigate={vi.fn()} />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('при сбое загрузки говорит об ошибке и предлагает повтор, а не «сделок нет»', async () => {
    // Пустая воронка означает «сделок нет». Пока сбой выглядел так же, руководитель читал
    // недоступный API как факт отсутствия работы (аудит UI, U2).
    vi.mocked(crmApi.getDealStages).mockRejectedValue(new Error('boom'));
    vi.mocked(crmApi.getDeals).mockRejectedValue(new Error('boom'));

    renderWithProviders(<PipelineFunnel onNavigate={vi.fn()} />);

    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
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

  it('shows the back-office metric set with localized labels', () => {
    renderWithProviders(<MetricStrip stats={stats} />);

    expect(screen.getByText('Объём сделок')).toBeInTheDocument();
    const activeRequestsMetric = screen.getByText('Активные заявки').parentElement;
    if (!activeRequestsMetric) throw new Error('no metric wrapper');
    expect(within(activeRequestsMetric).getByText('4')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument(); // catalog items
    expect(screen.getByText('7')).toBeInTheDocument(); // clients
    // The former buyer-only metric is gone together with the buyer dashboard (M1-ERP-02 wave 3).
    expect(screen.queryByText('КП получено')).not.toBeInTheDocument();
  });

  it('renders zeros when stats have not loaded yet', () => {
    renderWithProviders(<MetricStrip stats={null} />);

    // Three count metrics fall back to 0 (the volume metric renders as money).
    expect(screen.getAllByText('0')).toHaveLength(3);
  });
});
