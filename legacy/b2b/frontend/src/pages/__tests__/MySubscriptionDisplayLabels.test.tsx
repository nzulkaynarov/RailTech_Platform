import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { MySubscriptionPage } from '../MySubscriptionPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { Subscription } from '@/api/accountsApi';

vi.mock('@/hooks/useAccounts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useAccounts')>();
  return { ...actual, useMySubscription: vi.fn() };
});

const { useMySubscription } = await import('@/hooks/useAccounts');

/**
 * Sentinel `*_display` values. The backend really sends Russian `get_FOO_display()`
 * output here; using an obviously-fake marker instead means that if the page ever
 * regresses to rendering the server string, the sentinel shows up in the DOM and the
 * `not.toBeInTheDocument` assertions fail loudly rather than passing by coincidence
 * (the test i18n instance is Russian, so a real RU string would be indistinguishable
 * from the correctly-localized label).
 */
const PLAN_SENTINEL = 'DB-NAME-PLAN-СЕРВЕРНАЯ-СТРОКА';
const STATUS_SENTINEL = 'DB-NAME-STATUS-СЕРВЕРНАЯ-СТРОКА';

function makeSubscription(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: 1,
    company: 7,
    company_name: 'ООО Тест',
    company_inn: '123456789',
    plan: 'PREMIUM',
    plan_display: PLAN_SENTINEL,
    status: 'PAST_DUE',
    status_display: STATUS_SENTINEL,
    monthly_rate: '1000000.00',
    currency: 1,
    currency_code: 'UZS',
    valid_from: '2026-01-01',
    valid_until: '2026-12-31',
    last_payment_date: null,
    next_payment_date: null,
    notes: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function mockSubscription(sub: Subscription | null) {
  vi.mocked(useMySubscription).mockReturnValue({
    data: sub,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useMySubscription>);
}

describe('MySubscriptionPage — localized plan/status labels (DT5b)', () => {
  beforeEach(() => {
    vi.mocked(useMySubscription).mockReset();
  });

  it('renders the localized label for the plan/status CODE, not the server display string', () => {
    mockSubscription(makeSubscription());
    renderWithProviders(<MySubscriptionPage />);

    // ru.json: subscriptionPlans.premium / subscriptionStatuses.pastDue
    expect(screen.getByText('Премиум')).toBeInTheDocument();
    expect(screen.getByText('Просрочена')).toBeInTheDocument();

    // The Russian-only `*_display` fields must never reach the DOM.
    expect(screen.queryByText(PLAN_SENTINEL)).not.toBeInTheDocument();
    expect(screen.queryByText(STATUS_SENTINEL)).not.toBeInTheDocument();
  });

  it('falls back to the server display string when the CODE is unknown', () => {
    // A backend that gains a new choice must degrade to the server label, not blank out.
    mockSubscription(
      makeSubscription({ plan: 'ENTERPRISE_FUTURE', status: 'SOME_NEW_STATE' }),
    );
    renderWithProviders(<MySubscriptionPage />);

    expect(screen.getByText(PLAN_SENTINEL)).toBeInTheDocument();
    expect(screen.getByText(STATUS_SENTINEL)).toBeInTheDocument();
  });
});
