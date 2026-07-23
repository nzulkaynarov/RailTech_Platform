import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { DocumentCreateWizard } from '@/components/Documents/DocumentCreateWizard';

/**
 * WP-G2 — «Создать инвойс с нуля». The wizard's «Инвойс» type is a real create step (was a
 * dead-end hint routing to contracts): pick a deal, optionally import lines from a КП, create a
 * DRAFT invoice, and land on the invoice's DRAFT editor via `#invoices?open=<id>`.
 */

const inv = vi.hoisted(() => ({
  mutateAsync: vi.fn(async () => ({ id: 777, deal: 42, status: 'DRAFT' })),
}));

vi.mock('@/hooks/useDocuments', () => ({
  useDocumentTemplates: () => ({ data: [], isLoading: false }),
  useGenerateDocument: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useCRM', () => ({
  useDeals: () => ({ data: [{ id: 42, title: 'Сделка 42' }] }),
  useContacts: () => ({ data: [] }),
  useDeal: () => ({
    data: { id: 42, title: 'Сделка 42', quotes: [{ id: 9, version: 1, items: [{ id: 1 }] }] },
  }),
}));

vi.mock('@/hooks/useBilling', () => ({
  useCreateInvoiceDraft: () => ({ mutateAsync: inv.mutateAsync, isPending: false }),
}));

vi.mock('@/store/userStore', () => ({
  useUserStore: (selector: (s: { capabilities: { can_sell: boolean; can_buy: boolean } }) => unknown) =>
    selector({ capabilities: { can_sell: true, can_buy: false } }),
}));

// The КП and payment hand-off dialogs pull in their own hook trees — stub them out.
vi.mock('@/components/CRM/NewQuoteDialog', () => ({ NewQuoteDialog: () => null }));
vi.mock('@/components/Billing/RecordPaymentDialog', () => ({ RecordPaymentDialog: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
});

describe('DocumentCreateWizard — «Создать инвойс»', () => {
  it('creates a DRAFT invoice for the deal and lands on its editor via a deep link', async () => {
    // defaultDealId locks the deal so the create button is enabled without touching the Select.
    renderWithProviders(
      <DocumentCreateWizard open onOpenChange={vi.fn()} defaultDealId={42} />,
    );

    // Step 1 → pick the «Инвойс» type.
    fireEvent.click(screen.getByRole('button', { name: /Инвойс/ }));

    // Step 2 → create.
    const createBtn = await screen.findByRole('button', { name: 'Создать инвойс' });
    fireEvent.click(createBtn);

    await waitFor(() => expect(inv.mutateAsync).toHaveBeenCalledTimes(1));
    // Payload shape: the selected deal, no imported source КП by default.
    expect(inv.mutateAsync).toHaveBeenCalledWith({ deal: 42, source_quote: undefined });
    // DRAFT landing: deep link opens the new invoice's editor on the Invoices page.
    await waitFor(() => expect(window.location.hash).toBe('#invoices?open=777'));
  });
});
