import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { QuoteApprovalQueue } from '../QuoteApprovalQueue';
import { crmApi, type Quote } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useMyApprovalQueue react-query hook
// runs against this mocked crmApi.getMyApprovalQueue.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, getMyApprovalQueue: vi.fn() },
  };
});

function makeQueueQuote(id: number, deal: number): Quote {
  return {
    id,
    deal,
    version: 2,
    status: 3,
    status_code: 'PENDING_APPROVAL',
    status_name: 'На согласовании',
    items: [],
    subtotal_excl_vat: '0',
    vat_amount: '0',
    total_incl_vat: '0',
    created_at: '2026-07-01T10:00:00Z',
  };
}

describe('QuoteApprovalQueue', () => {
  beforeEach(() => {
    vi.mocked(crmApi.getMyApprovalQueue).mockReset();
    window.location.hash = '';
  });

  afterEach(() => {
    window.location.hash = '';
  });

  it('deep-links to the specific deal КП builder (deal-quote/{deal}) on row click', async () => {
    vi.mocked(crmApi.getMyApprovalQueue).mockResolvedValue([makeQueueQuote(101, 42)]);
    renderWithProviders(<QuoteApprovalQueue />);

    // Row appears once the async queue resolves.
    const row = await screen.findByRole('button');
    fireEvent.click(row);

    await waitFor(() => expect(window.location.hash).toBe('#deal-quote/42'));
  });

  it('renders nothing when the approval queue is empty', async () => {
    vi.mocked(crmApi.getMyApprovalQueue).mockResolvedValue([]);
    const { container } = renderWithProviders(<QuoteApprovalQueue />);

    // Give the query a tick to settle, then assert the component stays out of the way.
    await waitFor(() => expect(crmApi.getMyApprovalQueue).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
