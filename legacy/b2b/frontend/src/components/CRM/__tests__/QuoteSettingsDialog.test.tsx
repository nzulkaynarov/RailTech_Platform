import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';

import { QuoteSettingsDialog } from '../QuoteSettingsDialog';
import { crmApi, type Quote } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useUpdateQuoteSettings react-query mutation
// runs against this mocked crmApi.updateQuoteSettings (same pattern as the sibling
// GenerateQuoteDialog test — never intercept the network).
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, updateQuoteSettings: vi.fn(), setQuoteDeliveryBasis: vi.fn() },
  };
});

// The dialog fetches countries/currencies for its Selects — stub them so the test
// doesn't hit the network; empty lists are enough (we only exercise the margin input).
vi.mock('@/hooks/useMasterData', () => ({
  useCountries: () => ({ data: [] }),
  useCurrencies: () => ({ data: [] }),
}));

// Stub the delivery-basis picker (S2: relocated into this dialog) with a trivial button so
// the test can assert its onChange wiring without driving a Radix Select in jsdom.
vi.mock('../DeliveryBasisSelect', () => ({
  DeliveryBasisSelect: ({
    value,
    onChange,
    disabled,
  }: {
    value?: number | null;
    onChange: (id: number) => void;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      data-testid="delivery-basis-select"
      data-value={value ?? ''}
      disabled={disabled}
      onClick={() => onChange(5)}
    >
      basis
    </button>
  ),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: 7,
    deal: 42,
    version: 1,
    status: 1,
    status_code: 'DRAFT',
    status_name: 'Черновик',
    items: [],
    subtotal_excl_vat: '0',
    vat_amount: '0',
    total_incl_vat: '0',
    created_at: '2026-07-01T10:00:00Z',
    margin_percent: '10',
    vat_rate: '12',
    tax_country: null,
    valid_until: null,
    quote_currency: 'UZS',
    cost_currency_default: 'UZS',
    delivery_lead_time_days: null,
    delivery_note: '',
    effective_delivery_lead_time_days: 0,
    fx_snapshot: {},
    fx_manual: {},
    ...overrides,
  };
}

const MARGIN_LABEL = 'Наценка КП (%)';
const SAVE_LABEL = 'Сохранить';

describe('QuoteSettingsDialog', () => {
  beforeEach(() => {
    vi.mocked(crmApi.updateQuoteSettings).mockReset();
    vi.mocked(crmApi.setQuoteDeliveryBasis).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('saves the freshly typed margin on the first Save click (no blur) and toasts success', async () => {
    const quote = makeQuote({ id: 7 });
    vi.mocked(crmApi.updateQuoteSettings).mockResolvedValue(makeQuote({ id: 7, margin_percent: '25' }));
    const onOpenChange = vi.fn();
    renderWithProviders(<QuoteSettingsDialog quote={quote} open onOpenChange={onOpenChange} />);

    const marginInput = screen.getByLabelText(MARGIN_LABEL);
    // Type a new value, then click Save WITHOUT blurring the field first.
    fireEvent.change(marginInput, { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    // The mutation must fire with the value that was in the focused field, not the seed.
    await waitFor(() =>
      expect(crmApi.updateQuoteSettings).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ margin_percent: '25' }),
      ),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Настройки КП сохранены'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('selects the whole value when a numeric field gains focus (select-all)', () => {
    // Spy on the native select() the onFocus handler calls — robust across jsdom's
    // limited selection support for type="number".
    const selectSpy = vi.spyOn(HTMLInputElement.prototype, 'select');
    renderWithProviders(<QuoteSettingsDialog quote={makeQuote()} open onOpenChange={vi.fn()} />);

    fireEvent.focus(screen.getByLabelText(MARGIN_LABEL));

    expect(selectSpy).toHaveBeenCalled();
  });

  it('does not wipe an in-progress edit when a background refetch replaces the quote object', () => {
    // Regression for the silent-save: saving invalidates ['quotes'], so the parent
    // re-renders this dialog with a fresh `quote` object (same id) mid-edit. The seed
    // effect must NOT clobber the value the seller just typed.
    const { rerender } = renderWithProviders(
      <QuoteSettingsDialog quote={makeQuote({ id: 7, margin_percent: '10' })} open onOpenChange={vi.fn()} />,
    );

    const marginInput = screen.getByLabelText(MARGIN_LABEL);
    fireEvent.change(marginInput, { target: { value: '25' } });

    // A new object reference (same КП id) arrives — as a background refetch would deliver.
    rerender(
      <QuoteSettingsDialog quote={makeQuote({ id: 7, margin_percent: '99' })} open onOpenChange={vi.fn()} />,
    );

    expect(screen.getByLabelText(MARGIN_LABEL)).toHaveValue(25);
  });

  it('renders the «Поставка» section with the delivery-basis picker seeded from the КП (S2)', () => {
    vi.mocked(crmApi.setQuoteDeliveryBasis).mockResolvedValue(makeQuote({ id: 7 }));
    renderWithProviders(
      <QuoteSettingsDialog quote={makeQuote({ id: 7, delivery_basis: 3 })} open onOpenChange={vi.fn()} />,
    );

    // Section heading + the relocated basis picker, seeded with the КП's current basis.
    expect(screen.getByText('Поставка')).toBeInTheDocument();
    expect(screen.getByTestId('delivery-basis-select')).toHaveAttribute('data-value', '3');
  });

  it('applies a delivery-basis change immediately via its own endpoint (not the Save button)', async () => {
    vi.mocked(crmApi.setQuoteDeliveryBasis).mockResolvedValue(makeQuote({ id: 7 }));
    renderWithProviders(
      <QuoteSettingsDialog quote={makeQuote({ id: 7 })} open onOpenChange={vi.fn()} />,
    );

    fireEvent.click(screen.getByTestId('delivery-basis-select'));

    // The basis PATCH fires on change (id, basisId) — the Incoterm endpoint, separate from Save.
    await waitFor(() =>
      expect(crmApi.setQuoteDeliveryBasis).toHaveBeenCalledWith(7, 5),
    );
    // Changing the basis must NOT trigger the settings save.
    expect(crmApi.updateQuoteSettings).not.toHaveBeenCalled();
  });

  it('re-seeds the form when the dialog is opened for a different КП', () => {
    const { rerender } = renderWithProviders(
      <QuoteSettingsDialog quote={makeQuote({ id: 7, margin_percent: '10' })} open onOpenChange={vi.fn()} />,
    );
    expect(screen.getByLabelText(MARGIN_LABEL)).toHaveValue(10);

    // Switching to a different КП (new id) must load its own settings.
    rerender(
      <QuoteSettingsDialog quote={makeQuote({ id: 8, margin_percent: '33' })} open onOpenChange={vi.fn()} />,
    );
    expect(screen.getByLabelText(MARGIN_LABEL)).toHaveValue(33);
  });
});
