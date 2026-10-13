import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { BuyerAcceptedPanel } from '../BuyerAcceptedPanel';
import { contractsApi, type Contract, type ContractStatus } from '@/api/contractsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// The panel's real react-query hook (useContracts) runs against this mocked api module.
vi.mock('@/api/contractsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/contractsApi')>();
  return {
    ...actual,
    contractsApi: { ...actual.contractsApi, list: vi.fn() },
  };
});

function makeContract(id: number, status: ContractStatus, number: string, createdAt: string): Contract {
  return {
    id,
    deal: 42,
    quote: id,
    number,
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
    viewer_can_sign_client: true,
    viewer_can_sign_manager: false,
    valid_from: null,
    valid_until: null,
    invoice_id: null,
  wording_selections: {},
    notes: '',
    created_at: createdAt,
    updated_at: createdAt,
  };
}

beforeEach(() => {
  vi.mocked(contractsApi.list).mockReset().mockResolvedValue([]);
  window.location.hash = '';
});

describe('BuyerAcceptedPanel (Wave A2 post-accept next step)', () => {
  it('surfaces the REAL contract number awaiting the buyer signature and deep-links to it', async () => {
    // Two contracts for the deal — the CANCELLED one must be ignored, newest live one wins.
    vi.mocked(contractsApi.list).mockResolvedValue([
      makeContract(5, 'CANCELLED', 'CT-2026-00001', '2026-07-01T09:00:00Z'),
      makeContract(7, 'PENDING_CLIENT', 'CT-2026-00002', '2026-07-02T09:00:00Z'),
    ]);

    renderWithProviders(<BuyerAcceptedPanel dealId={42} />);

    // The real contract number is read from the API, never fabricated.
    expect(await screen.findByText('Договор № CT-2026-00002 готов к подписанию')).toBeInTheDocument();
    expect(contractsApi.list).toHaveBeenCalledWith({ deal: 42 });

    const cta = screen.getByRole('button', { name: /Перейти к договору/ });
    await waitFor(() => expect(cta).toBeEnabled());
    fireEvent.click(cta);
    // Deep-link carries the specific contract id (ContractsPage opens its sheet).
    expect(window.location.hash).toBe('#contracts?open=7');
  });

  it('falls back to the contracts list when no live contract has resolved yet', async () => {
    vi.mocked(contractsApi.list).mockResolvedValue([]);

    renderWithProviders(<BuyerAcceptedPanel dealId={42} />);

    // Waits for the query to settle to the empty state.
    await waitFor(() => expect(contractsApi.list).toHaveBeenCalled());
    const cta = await screen.findByRole('button', { name: /Перейти к договору/ });
    await waitFor(() => expect(cta).toBeEnabled());
    fireEvent.click(cta);
    expect(window.location.hash).toBe('#contracts');
  });
});
