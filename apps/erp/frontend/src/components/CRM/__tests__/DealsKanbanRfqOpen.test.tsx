import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { toast } from 'sonner';

import { DealsKanban } from '../DealsKanban';
import { crmApi, type Deal } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';

/* WP-3 (P1-1) regression guard — «Открытый RFQ» в Канбане + достижимый claim.
 * The RFQ_OPEN column is built from the `stages` prop (backend deal-stages list,
 * which includes RFQ_OPEN); a fresh routed заявка (assigned_to == null) lands in it
 * and MUST carry a reachable claim ("взять в работу") button. Mocks the API client
 * layer, never the network — the real useClaimDeal mutation drives crmApi.claimDeal. */

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
  return { created_at: '2026-07-08T10:00:00Z', ...overrides };
}

// Backend deal-stages order (DealStageViewSet → sort_order); RFQ_OPEN is present.
const STAGES = [
  { code: 'RFQ_OPEN', name: 'Открытый RFQ' },
  { code: 'SOURCING', name: 'Проработка' },
];

const RFQ_OPEN_COLUMN = '.w-72';

// One freshly-routed unclaimed RFQ (id 1) + one already-claimed RFQ (id 2) in the same column.
const DEALS: Deal[] = [
  makeDeal({ id: 1, title: 'Свежая заявка Р65', stage_code: 'RFQ_OPEN', assigned_to: null }),
  makeDeal({ id: 2, title: 'Уже в работе', stage_code: 'RFQ_OPEN', assigned_to: 9, assigned_to_name: 'Продавец' }),
];

describe('DealsKanban — RFQ_OPEN column + reachable claim (WP-3)', () => {
  beforeEach(() => {
    // Кнопки взять / вернуть — по праву deal.manage из /me (D-03, FIX-58).
    useUserStore.setState({ capabilities: { permissions: ['deal.manage'] } });
    vi.mocked(crmApi.claimDeal).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it('renders the RFQ_OPEN column when stages include it', () => {
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);
    expect(screen.getByText('Заявка открыта')).toBeInTheDocument();
  });

  it('shows a claim button only on the fresh unassigned RFQ_OPEN card', () => {
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);

    const column = screen.getByText('Заявка открыта').closest(RFQ_OPEN_COLUMN);
    if (!column) throw new Error('RFQ_OPEN column not found');

    // Exactly one claimable card in the column — the unclaimed one (id 1).
    const claimButtons = within(column as HTMLElement).getAllByRole('button', { name: 'Взять в работу' });
    expect(claimButtons).toHaveLength(1);
    // The claimed card (id 2) surfaces its owner instead of a claim button.
    expect(within(column as HTMLElement).getByText('Продавец')).toBeInTheDocument();
  });

  it('claim is reachable from the funnel — clicking it calls claimDeal for the fresh RFQ', async () => {
    vi.mocked(crmApi.claimDeal).mockResolvedValue(makeDeal({ id: 1, assigned_to: 5 }));
    const onOpen = vi.fn();
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole('button', { name: 'Взять в работу' }));

    await waitFor(() => expect(crmApi.claimDeal).toHaveBeenCalledWith(1));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Заявка взята в работу'));
    // stopPropagation: taking ownership from the queue must not open the deal.
    expect(onOpen).not.toHaveBeenCalled();
  });
});
