import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Quote } from '@/api/crmApi';
import { QuoteSentPanel } from '@/components/CRM/QuoteSentPanel';

/**
 * WP-G1 — «Дублировать КП» (Odoo Duplicate). The post-send panel's «Дублировать» action
 * deep-copies the КП and, on success, drops the seller straight into the new draft's builder
 * (`#deal-quote/{dealId}`). One click, no confirm modal (Odoo pattern).
 */

// Hoisted mutate spy: the mock invokes options.onSuccess with the duplicated quote so the
// redirect side-effect can be asserted.
const dup = vi.hoisted(() => ({
  mutate: vi.fn((_id: number, opts?: { onSuccess?: (q: Quote) => void }) => {
    opts?.onSuccess?.({ id: 200, deal: 42, version: 2, status_code: 'DRAFT' } as Quote);
  }),
}));

vi.mock('@/hooks/useCRM', () => ({
  useRevokePublicLink: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateQuote: () => ({ mutate: vi.fn(), isPending: false }),
  useDuplicateQuote: () => ({ mutate: dup.mutate, isPending: false }),
}));

const makeQuote = (over: Partial<Quote> = {}): Quote => ({
  id: 100, deal: 42, version: 1, status: 1, status_code: 'SENT', status_name: '',
  items: [], subtotal_excl_vat: '0', vat_amount: '0', total_incl_vat: '0',
  frozen_at: '2026-07-21T14:02:00Z', created_at: '', ...over,
} as Quote);

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '';
});

describe('QuoteSentPanel — «Создать новую версию»', () => {
  it('показывает ОДНУ операцию переиздания — «Дублировать» больше нет', () => {
    renderWithProviders(<QuoteSentPanel quote={makeQuote()} />);
    expect(screen.getByText('Создать новую версию')).toBeInTheDocument();
    expect(screen.queryByText('Дублировать')).not.toBeInTheDocument();
  });

  it('зовёт глубокую копию с id ИСХОДНОГО КП и уводит в билдер копии', () => {
    renderWithProviders(<QuoteSentPanel quote={makeQuote()} />);
    fireEvent.click(screen.getByText('Создать новую версию'));
    fireEvent.click(screen.getByRole('button', { name: 'Создать новую версию' }));
    expect(dup.mutate).toHaveBeenCalledTimes(1);
    expect(dup.mutate.mock.calls[0][0]).toBe(100); // source quote id
    // Redirect uses the NEW quote's deal id returned by the mutation.
    expect(window.location.hash).toBe('#deal-quote/42');
  });
});
