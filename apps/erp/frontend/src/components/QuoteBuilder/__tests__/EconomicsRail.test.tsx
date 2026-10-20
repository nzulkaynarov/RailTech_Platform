import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Quote, DeliveryBasis } from '@/api/crmApi';
import { EconomicsRail } from '../EconomicsRail';
import { QuoteBuilderGridProvider, type QuoteBuilderGridContextValue } from '../QuoteBuilderGridContext';

/**
 * EconomicsRail delivery-basis chip (S2 consolidation). The Incoterm picker moved into
 * «Настройки КП»; the rail now shows a read-only chip of the current basis whose click opens
 * the settings dialog (via the shared `setShowSettings` callback). A frozen КП renders a plain,
 * non-interactive badge instead.
 */

// The document export block isn't under test here — stub it to keep the render lean.
vi.mock('@/components/Shared/DocumentActions', () => ({ DocumentActions: () => null }));

const EXW_BASIS: DeliveryBasis = {
  id: 3,
  code: 'EXW',
  name: 'Ex Works',
  seller_pays_freight: false,
  seller_pays_insurance: false,
  seller_pays_import: false,
  seller_pays_delivery: false,
};

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: 100,
    deal: 42,
    version: 1,
    status: 1,
    status_code: 'DRAFT',
    status_name: 'Черновик',
    quote_currency: 'UZS',
    vat_rate: '12',
    margin_percent: '0',
    items: [],
    charges: [],
    subtotal_excl_vat: '1000',
    charges_total: '0',
    vat_amount: '120',
    total_incl_vat: '1120',
    frozen_at: null,
    created_at: '2026-07-01T00:00:00Z',
    ...overrides,
  } as Quote;
}

function buildContext(
  activeQuote: Quote,
  setShowSettings: (value: boolean) => void,
): QuoteBuilderGridContextValue {
  return {
    activeQuote,
    econ: null,
    presentationCurrency: 'UZS',
    vatRate: '12',
    effectiveLeadTime: 0,
    mirrorTotals: {
      isDraft: false,
      computable: true,
      subtotalExclVat: '1000',
      chargesTotal: '0',
      vatAmount: '120',
      totalInclVat: '1120',
      grossMarginPercent: null,
    },
    setShowSettings,
    toggleRail: vi.fn(),
    railAsSheet: false,
    railOpen: true,
    railSheetOpen: false,
    setRailSheetOpen: vi.fn(),
  } as unknown as QuoteBuilderGridContextValue;
}

describe('EconomicsRail — delivery-basis chip (S2)', () => {
  it('renders the current basis code and opens settings on click', async () => {
    const setShowSettings = vi.fn();
    const quote = makeQuote({
      delivery_basis: 3,
      delivery_basis_data: EXW_BASIS,
    });
    renderWithProviders(
      <QuoteBuilderGridProvider value={buildContext(quote, setShowSettings)}>
        <EconomicsRail />
      </QuoteBuilderGridProvider>,
    );

    const chip = screen.getByRole('button', { name: /Изменить базис поставки/ });
    expect(chip).toHaveTextContent('EXW');

    await userEvent.click(chip);
    expect(setShowSettings).toHaveBeenCalledWith(true);
  });

  it('shows a «basis not set» chip when the КП has no delivery basis', () => {
    const quote = makeQuote({ delivery_basis: null, delivery_basis_data: null });
    renderWithProviders(
      <QuoteBuilderGridProvider value={buildContext(quote, vi.fn())}>
        <EconomicsRail />
      </QuoteBuilderGridProvider>,
    );

    expect(screen.getByRole('button', { name: /Изменить базис поставки/ })).toHaveTextContent(
      'Базис не выбран',
    );
  });

  it('renders a non-interactive badge (no edit button) for a frozen КП', () => {
    const quote = makeQuote({
      frozen_at: '2026-07-02T00:00:00Z',
      delivery_basis: 3,
      delivery_basis_data: EXW_BASIS,
    });
    renderWithProviders(
      <QuoteBuilderGridProvider value={buildContext(quote, vi.fn())}>
        <EconomicsRail />
      </QuoteBuilderGridProvider>,
    );

    // Frozen: the basis is shown but not clickable, and the «Настройки КП» entry is hidden.
    expect(screen.queryByRole('button', { name: /Изменить базис поставки/ })).not.toBeInTheDocument();
    expect(screen.getByText('EXW')).toBeInTheDocument();
  });
});
