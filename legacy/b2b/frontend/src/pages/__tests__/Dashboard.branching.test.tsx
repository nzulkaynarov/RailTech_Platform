import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { Dashboard } from '@/pages/Dashboard';
import { dashboardApi, type DashboardStats } from '@/api/dashboardApi';

/**
 * WP-2 — «Продавец видит продавцовский дашборд».
 *
 * The pre-auth context default is BUYER (ADR-0005), so a seller-capable / dual company
 * used to land on BuyerDashboard → the buyer onboarding («Начните за 3 шага») even
 * though its real inbound work lives on the seller side. The Dashboard now routes any
 * seller-capable company (verified SELLER context + can_sell) to the SellerDashboard
 * without flipping the global activeStatus default. These tests pin the branching:
 *   • seller-capable (single-side)   → seller content, never BuyerWelcome
 *   • dual buyer+seller (BUYER active default) → seller content, never BuyerWelcome
 *   • pure buyer, verified, no activity        → BuyerWelcome (unchanged behaviour)
 */

// ── Mutable store state fed to the mocked useUserStore (hoisted so the vi.mock
//    factory below can close over it; each test sets `storeRef.state`). ──
type Entry = { status: 'BUYER' | 'SELLER'; verification: 'verified' | 'pending' | 'rejected' };
type MockState = {
  activeStatus: 'BUYER' | 'SELLER';
  profile: { firstName: string };
  company: { name: string; inn: string; kycStatus: string; statusEntries: Entry[] };
};
const storeRef = vi.hoisted(() => ({ state: null as unknown as MockState }));

// Keep the REAL selectIsSellerCapable — the branching heuristic itself is under test.
vi.mock('@/store/userStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/store/userStore')>();
  return {
    ...actual,
    useUserStore: (selector?: (s: MockState) => unknown) =>
      selector ? selector(storeRef.state) : storeRef.state,
  };
});

// Stats come through useQuery(dashboardApi.getStats) — control it directly.
vi.mock('@/api/dashboardApi', () => ({ dashboardApi: { getStats: vi.fn() } }));

// Heavy dashboard children are irrelevant to the branch under test → identifiable stubs.
vi.mock('@/components/Dashboard/DashboardWidgets', () => ({
  SellerAttentionStrip: () => <div>SELLER_ATTENTION_STRIP</div>,
  BuyerAttentionStrip: () => <div>BUYER_ATTENTION_STRIP</div>,
  // F3: полоса «деньги и поставка» — здесь не предмет проверки (ветвление дашборда).
  PostContractStrip: () => null,
  PipelineFunnel: () => null,
  MetricStrip: () => null,
}));
vi.mock('@/components/CRM/QuoteApprovalQueue', () => ({
  QuoteApprovalQueue: () => <div>QUOTE_APPROVAL_QUEUE</div>,
}));
vi.mock('@/components/Shared/OnboardingChecklist', () => ({ OnboardingChecklist: () => null }));

// Data hooks used by the internal seller/buyer cards — return quiet, empty results.
vi.mock('@/hooks/useCRM', () => ({
  useDeals: () => ({ data: [], isError: false, refetch: vi.fn() }),
  useTimeToFirstQuote: () => ({ data: null }),
}));
vi.mock('@/store/currencyStore', () => ({
  useCurrencyStore: (selector: (s: { format: (v: number) => string }) => unknown) =>
    selector({ format: (v: number) => String(v) }),
}));

/** All-zero stats → BuyerDashboard's `isEmpty` gate fires (used for the pure-buyer case). */
function zeroStats(): DashboardStats {
  return {
    deals_volume: 0, deals_volume_change: 0,
    active_requests: 0, active_requests_change: 0,
    catalog_items: 0, catalog_items_change: 0,
    clients_count: 0, clients_count_change: 0,
    deals_by_month: [], activity_by_day: [], top_products: [],
    counterparties: { manufacturers: 0, buyers: 0, intermediaries: 0 },
    request_completion: 0, request_completion_goal: 0,
    deals_in_progress: 0, quotes_received: 0, deals_completed: 0,
  };
}

beforeEach(() => {
  vi.mocked(dashboardApi.getStats).mockReset().mockResolvedValue(zeroStats());
});

describe('Dashboard — context-aware landing (WP-2)', () => {
  it('renders the seller inbox for a seller-capable company (never the buyer onboarding)', async () => {
    storeRef.state = {
      activeStatus: 'SELLER',
      profile: { firstName: 'Diana' },
      company: { name: 'ООО Продавец', inn: '1', kycStatus: 'verified', statusEntries: [{ status: 'SELLER', verification: 'verified' }] },
    };

    renderWithProviders(<Dashboard onNavigate={vi.fn()} />);

    expect(await screen.findByText('SELLER_ATTENTION_STRIP')).toBeInTheDocument();
    expect(screen.getByText('QUOTE_APPROVAL_QUEUE')).toBeInTheDocument();
    // The buyer onboarding must NOT be the landing.
    expect(screen.queryByText('Начните работу на платформе за 3 простых шага')).toBeNull();
    expect(screen.queryByText('BUYER_ATTENTION_STRIP')).toBeNull();
  });

  it('routes a DUAL buyer+seller company (BUYER active by default) to the seller inbox, not «Начните за 3 шага»', async () => {
    // Reproduces diana/aziz: dual company whose default context resolves to BUYER.
    storeRef.state = {
      activeStatus: 'BUYER',
      profile: { firstName: 'Aziz' },
      company: {
        name: 'ООО Дуал', inn: '2', kycStatus: 'verified',
        statusEntries: [
          { status: 'BUYER', verification: 'verified' },
          { status: 'SELLER', verification: 'verified' },
        ],
      },
    };

    renderWithProviders(<Dashboard onNavigate={vi.fn()} />);

    expect(await screen.findByText('SELLER_ATTENTION_STRIP')).toBeInTheDocument();
    expect(screen.getByText('QUOTE_APPROVAL_QUEUE')).toBeInTheDocument();
    // The regression: a dual seller-capable user must not see the buyer onboarding.
    expect(screen.queryByText('Начните работу на платформе за 3 простых шага')).toBeNull();
  });

  it('keeps the unchanged BuyerWelcome onboarding for a pure buyer (verified, no activity)', async () => {
    storeRef.state = {
      activeStatus: 'BUYER',
      profile: { firstName: 'Boris' },
      company: { name: 'ООО Покупатель', inn: '3', kycStatus: 'verified', statusEntries: [{ status: 'BUYER', verification: 'verified' }] },
    };

    renderWithProviders(<Dashboard onNavigate={vi.fn()} />);

    // BuyerWelcome (real ru.json strings) is the landing for pure buyers with no activity.
    expect(await screen.findByText('Начните работу на платформе за 3 простых шага')).toBeInTheDocument();
    expect(screen.getByText('Изучите каталог')).toBeInTheDocument();
    // Seller surface is absent for a pure buyer.
    expect(screen.queryByText('SELLER_ATTENTION_STRIP')).toBeNull();
    expect(screen.queryByText('QUOTE_APPROVAL_QUEUE')).toBeNull();
  });

  it('does NOT treat an unverified SELLER context as seller-capable (verification gate)', async () => {
    // A pending SELLER entry must not flip the landing — mirrors App.tsx / AppShell gating.
    storeRef.state = {
      activeStatus: 'BUYER',
      profile: { firstName: 'Nadia' },
      company: {
        name: 'ООО Ожидание', inn: '4', kycStatus: 'verified',
        statusEntries: [
          { status: 'BUYER', verification: 'verified' },
          { status: 'SELLER', verification: 'pending' },
        ],
      },
    };

    renderWithProviders(<Dashboard onNavigate={vi.fn()} />);

    expect(await screen.findByText('Начните работу на платформе за 3 простых шага')).toBeInTheDocument();
    expect(screen.queryByText('SELLER_ATTENTION_STRIP')).toBeNull();
  });

  it('shows the KYC pending banner (not the seller strip) for a seller-capable company below KYC L2', async () => {
    storeRef.state = {
      activeStatus: 'SELLER',
      profile: { firstName: 'Diana' },
      company: { name: 'ООО Продавец', inn: '5', kycStatus: 'pending', statusEntries: [{ status: 'SELLER', verification: 'verified' }] },
    };

    renderWithProviders(<Dashboard onNavigate={vi.fn()} />);

    // KYC gate wins over the seller inbox until verified (SellerDashboard's own guard).
    await waitFor(() => expect(dashboardApi.getStats).toHaveBeenCalled());
    expect(await screen.findByText('Статус верификации')).toBeInTheDocument();
    expect(screen.queryByText('SELLER_ATTENTION_STRIP')).toBeNull();
    expect(screen.queryByText('Начните работу на платформе за 3 простых шага')).toBeNull();
  });
});
