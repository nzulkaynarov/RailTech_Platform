import { afterEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { QuoteSendGateBanner } from '@/components/CRM/QuoteSendGateBanner';
import { useUserStore, type Capabilities } from '@/store/userStore';
import { renderWithProviders } from '@/test/renderWithProviders';

/** A fully-populated Capabilities object; tests override only the fields under test. */
function caps(overrides: Partial<Capabilities>): Capabilities {
  return {
    can_buy: true,
    can_sell: true,
    subscription_active: false,
    can_send_quotes: false,
    quote_send_is_demo: false,
    permissions: [],
    ...overrides,
  };
}

function setUser(capabilities: Capabilities, activeStatus: 'SELLER' | 'BUYER' = 'SELLER') {
  useUserStore.setState({ activeStatus, capabilities });
}

describe('QuoteSendGateBanner', () => {
  afterEach(() => {
    // Reset to a neutral seller with no blocker so tests don't leak state.
    setUser(caps({ can_send_quotes: true }));
  });

  it('shows the subscription banner when quote.send is not entitled', () => {
    setUser(caps({ can_send_quotes: false, quote_send_is_demo: false }));
    renderWithProviders(<QuoteSendGateBanner />);
    expect(screen.getByText(/требует активной подписки/i)).toBeInTheDocument();
  });

  it('shows the DEMO watermark banner for a demo grant', () => {
    setUser(caps({ can_send_quotes: false, quote_send_is_demo: true }));
    renderWithProviders(<QuoteSendGateBanner />);
    expect(screen.getByText(/водяным знаком DEMO/i)).toBeInTheDocument();
  });

  it('renders nothing when the seller can send (entitlement)', () => {
    setUser(caps({ can_send_quotes: true }));
    const { container } = renderWithProviders(<QuoteSendGateBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing on the buyer side even when send preconditions are unmet', () => {
    setUser(caps({ can_send_quotes: false }), 'BUYER');
    const { container } = renderWithProviders(<QuoteSendGateBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the CTA only when onNavigate is provided', () => {
    setUser(caps({ can_send_quotes: false }));
    renderWithProviders(<QuoteSendGateBanner onNavigate={() => {}} />);
    expect(screen.getByRole('button', { name: /оформить подписку/i })).toBeInTheDocument();
  });
});
