import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { RejectQuoteDialog } from '../RejectQuoteDialog';
import { renderWithProviders } from '@/test/renderWithProviders';

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}));

beforeEach(() => {
  toastError.mockReset();
});

describe('RejectQuoteDialog (Wave A2 cabinet reject-with-reason guard)', () => {
  it('blocks confirm on an empty/whitespace reason and never calls onConfirm', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <RejectQuoteDialog quoteId={9} open onOpenChange={vi.fn()} onConfirm={onConfirm} />,
    );

    const textarea = await screen.findByLabelText('Причина');
    // Whitespace-only must be treated as empty.
    fireEvent.change(textarea, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('passes the trimmed reason to onConfirm and closes on success', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const onOpenChange = vi.fn();
    renderWithProviders(
      <RejectQuoteDialog quoteId={9} open onOpenChange={onOpenChange} onConfirm={onConfirm} />,
    );

    const textarea = await screen.findByLabelText('Причина');
    fireEvent.change(textarea, { target: { value: '  цена выше бюджета  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith('цена выше бюджета'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(toastError).not.toHaveBeenCalled();
  });
});
