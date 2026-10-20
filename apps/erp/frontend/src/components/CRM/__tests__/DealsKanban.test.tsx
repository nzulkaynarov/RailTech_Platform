import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { toast } from 'sonner';

import { DealsKanban } from '../DealsKanban';
import { crmApi, type Deal } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';

// Mock at the API-client layer (never at the network): the real useClaimDeal
// react-query mutation runs against this mocked crmApi.claimDeal.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, claimDeal: vi.fn() },
  };
});

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function makeDeal(overrides: Partial<Deal> & { id: number }): Deal {
  return {
    created_at: '2026-07-01T10:00:00Z',
    ...overrides,
  };
}

const STAGES = [
  { code: 'RFQ_OPEN', name: 'Заявка открыта' },
  { code: 'SOURCING', name: 'Проработка' },
  { code: 'QUOTE_SENT', name: 'КП отправлено' },
];

const DEALS: Deal[] = [
  makeDeal({
    id: 1,
    title: 'Рельсы Р65',
    stage_code: 'RFQ_OPEN',
    company_name: 'ООО Магистраль',
    total_value: '1000000',
    assigned_to: null,
  }),
  makeDeal({
    id: 2,
    title: 'Стрелочный перевод',
    stage_code: 'RFQ_OPEN',
    total_value: '500000',
    assigned_to: 9,
    assigned_to_name: 'Алишер Усманов',
  }),
  makeDeal({ id: 7, stage_code: 'SOURCING', assigned_to: 9, assigned_to_name: '' }),
];

describe('DealsKanban', () => {
  beforeEach(() => {
    // Кнопки взять / вернуть — по праву deal.manage из /me (D-03, FIX-58).
    useUserStore.setState({ capabilities: { permissions: ['deal.manage'] } });
    vi.mocked(crmApi.claimDeal).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it('renders one column per stage in backend order with grouped deal counts', () => {
    const { container } = renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    // Stage names come from the lookup (display), order follows the stages array (FSM sort_order).
    const text = container.textContent ?? '';
    expect(text.indexOf('Заявка открыта')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('Заявка открыта')).toBeLessThan(text.indexOf('Закупка'));
    expect(text.indexOf('Закупка')).toBeLessThan(text.indexOf('КП отправлено'));

    // Deals are grouped by stage_code (CODE, not translated name): 2 / 1 / 0.
    const header = (name: string) => {
      const el = screen.getByText(name).parentElement;
      if (!el) throw new Error(`no column header for ${name}`);
      return el;
    };
    expect(within(header('Заявка открыта')).getByText('2')).toBeInTheDocument();
    expect(within(header('Закупка')).getByText('1')).toBeInTheDocument();
    expect(within(header('КП отправлено')).getByText('0')).toBeInTheDocument();
  });

  it('shows the localized empty placeholder in stages without deals', () => {
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);
    // Only the QUOTE_SENT column is empty.
    expect(screen.getAllByText('Нет сделок')).toHaveLength(1);
  });

  it('renders card details and falls back to a localized untitled label', () => {
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    expect(screen.getByText('Рельсы Р65')).toBeInTheDocument();
    expect(screen.getByText('ООО Магистраль')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    // dealsKanban.untitled with {{id}} interpolation from the real ru.json
    expect(screen.getByText('Сделка #7')).toBeInTheDocument();
  });

  it('opens a deal when its card is clicked', () => {
    const onOpen = vi.fn();
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} onOpen={onOpen} />);

    fireEvent.click(screen.getByText('Рельсы Р65'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(DEALS[0]);
  });

  it('shows the assignee badge for claimed deals (falls back by CODE of ownership, not name)', () => {
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    // Named assignee renders the name…
    expect(screen.getByText('Алишер Усманов')).toBeInTheDocument();
    // …blank assignee name (invited member / cross-tenant redaction) still reads
    // as claimed via the localized fallback — because assigned_to (id) is set.
    expect(screen.getByText('Назначено')).toBeInTheDocument();
    // Exactly one card (id=1, assigned_to=null) is claimable.
    expect(screen.getAllByRole('button', { name: 'Взять в работу' })).toHaveLength(1);
  });

  it('Наблюдателю (нет deal.manage) «Взять в работу» не предлагается (D-03, FIX-58)', () => {
    useUserStore.setState({ capabilities: { permissions: [] } });
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument();
    // Карточки при этом видны.
    expect(screen.getByText('Рельсы Р65')).toBeInTheDocument();
  });

  it('claims an unassigned deal from the queue without opening it', async () => {
    vi.mocked(crmApi.claimDeal).mockResolvedValue(makeDeal({ id: 1, assigned_to: 5 }));
    const onOpen = vi.fn();
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole('button', { name: 'Взять в работу' }));

    await waitFor(() => expect(crmApi.claimDeal).toHaveBeenCalledWith(1));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Заявка взята в работу'));
    // stopPropagation: taking ownership must not open the deal sheet.
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('surfaces a claim failure as an error toast', async () => {
    vi.mocked(crmApi.claimDeal).mockRejectedValue('DEAL_ALREADY_CLAIMED');
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    fireEvent.click(screen.getByRole('button', { name: 'Взять в работу' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
