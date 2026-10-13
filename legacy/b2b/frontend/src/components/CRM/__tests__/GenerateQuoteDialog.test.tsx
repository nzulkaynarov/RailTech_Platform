import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';

import { GenerateQuoteDialog } from '../GenerateQuoteDialog';
import { crmApi, type Quote } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useCreateQuote react-query mutation
// runs against this mocked crmApi.createQuote.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, createQuote: vi.fn() },
  };
});

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function makeQuote(id: number): Quote {
  return {
    id,
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
  };
}

function isoDatePlusDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

describe('GenerateQuoteDialog', () => {
  beforeEach(() => {
    vi.mocked(crmApi.createQuote).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it('renders localized title + notes and no longer exposes the valid-until field (S2)', () => {
    renderWithProviders(
      <GenerateQuoteDialog dealId={42} open onOpenChange={vi.fn()} />,
    );

    // Real ru.json keys resolve (a missing key would render the raw key and fail here).
    expect(screen.getByText('Создать коммерческое предложение')).toBeInTheDocument();
    expect(screen.getByText('Что дальше')).toBeInTheDocument();
    expect(screen.getByLabelText('Комментарий')).toBeInTheDocument();

    // valid_until moved to «Настройки КП» (S2) — the creation dialog no longer shows it.
    expect(screen.queryByLabelText('Действительно до')).not.toBeInTheDocument();
  });

  it('creates a quote with the trimmed notes and the silent +14-day validity, then closes', async () => {
    vi.mocked(crmApi.createQuote).mockResolvedValue(makeQuote(101));
    const onOpenChange = vi.fn();
    const onGenerated = vi.fn();
    renderWithProviders(
      <GenerateQuoteDialog dealId={42} open onOpenChange={onOpenChange} onGenerated={onGenerated} />,
    );

    fireEvent.change(screen.getByLabelText('Комментарий'), {
      target: { value: '  Условия поставки — EXW.  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать КП' }));

    // valid_until is pre-filled silently to +14 days (edited later in settings, S2).
    await waitFor(() =>
      expect(crmApi.createQuote).toHaveBeenCalledWith({
        deal: 42,
        notes: 'Условия поставки — EXW.',
        valid_until: isoDatePlusDays(14),
      }),
    );
    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith(101));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(toast.success).toHaveBeenCalledWith('КП создано');
  });

  it('omits notes from the payload when the field is blank', async () => {
    vi.mocked(crmApi.createQuote).mockResolvedValue(makeQuote(102));
    renderWithProviders(
      <GenerateQuoteDialog dealId={42} open onOpenChange={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Создать КП' }));

    await waitFor(() =>
      expect(crmApi.createQuote).toHaveBeenCalledWith({
        deal: 42,
        notes: undefined,
        valid_until: isoDatePlusDays(14),
      }),
    );
  });

  it('keeps the dialog open and shows an error toast when creation fails', async () => {
    vi.mocked(crmApi.createQuote).mockRejectedValue('QUOTE_LIMIT_REACHED');
    const onOpenChange = vi.fn();
    const onGenerated = vi.fn();
    renderWithProviders(
      <GenerateQuoteDialog dealId={42} open onOpenChange={onOpenChange} onGenerated={onGenerated} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Создать КП' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onGenerated).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('disables submit when there is no deal', () => {
    renderWithProviders(
      <GenerateQuoteDialog dealId={null} open onOpenChange={vi.fn()} />,
    );

    expect(screen.getByRole('button', { name: 'Создать КП' })).toBeDisabled();
  });

  it('cancel closes the dialog without creating anything', () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <GenerateQuoteDialog dealId={42} open onOpenChange={onOpenChange} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(crmApi.createQuote).not.toHaveBeenCalled();
  });
});
