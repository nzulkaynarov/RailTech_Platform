import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote } from '@/api/crmApi';
import { QuoteSentPanel } from '@/components/CRM/QuoteSentPanel';

/**
 * Wave B2 — the post-send tracking panel (PandaDoc pattern). Pins the status line
 * (Отправлено → Просмотрено → Решение) and the graceful degradation of the link actions:
 * copy/revoke appear only once the backend exposes a live public share token.
 */

vi.mock('@/hooks/useCRM', () => ({
  useRevokePublicLink: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateQuote: () => ({ mutate: vi.fn(), isPending: false }),
  useDuplicateQuote: () => ({ mutate: vi.fn(), isPending: false }),
}));

const deal = { id: 42, created_at: '' } as Deal;
const makeQuote = (over: Partial<Quote>): Quote => ({
  id: 100, deal: 42, version: 1, status: 1, status_code: 'SENT', status_name: '',
  items: [], subtotal_excl_vat: '0', vat_amount: '0', total_incl_vat: '0',
  frozen_at: '2026-07-21T14:02:00Z', created_at: '', ...over,
} as Quote);

beforeEach(() => vi.clearAllMocks());

describe('QuoteSentPanel — status line', () => {
  it('renders the three tracking stages', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({})} />);
    expect(screen.getByText('Отправлено')).toBeInTheDocument();
    expect(screen.getByText('Просмотрено')).toBeInTheDocument();
    expect(screen.getByText('Решение')).toBeInTheDocument();
  });

  it('shows «—» for viewed + decision on a fresh SENT КП (not yet opened / decided)', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({ first_viewed_at: null })} />);
    // Both the «Просмотрено» and «Решение» values fall back to the em-dash placeholder.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('reflects a client view and an accepted decision', () => {
    renderWithProviders(
      <QuoteSentPanel deal={deal} quote={makeQuote({ first_viewed_at: '2026-07-21T15:00:00Z', status_code: 'APPROVED' })} />,
    );
    expect(screen.getByText('Принято')).toBeInTheDocument();
  });

  it('reflects a rejected decision', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({ status_code: 'REJECTED' })} />);
    expect(screen.getByText('Отклонено')).toBeInTheDocument();
  });
});

describe('QuoteSentPanel — public link actions (graceful degradation)', () => {
  it('hides copy/revoke when no share token is exposed yet', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({ public_access_token: null })} />);
    expect(screen.queryByText('Копировать ссылку')).not.toBeInTheDocument();
    expect(screen.queryByText('Отозвать ссылку')).not.toBeInTheDocument();
    // «Создать новую версию» is always available.
    expect(screen.getByText('Создать новую версию')).toBeInTheDocument();
  });

  it('shows copy + revoke once a live token is exposed', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({ public_access_token: 'tok', public_token_revoked: false })} />);
    expect(screen.getByText('Копировать ссылку')).toBeInTheDocument();
    expect(screen.getByText('Отозвать ссылку')).toBeInTheDocument();
  });

  it('shows a revoked note (not the copy/revoke buttons) when the token is revoked', () => {
    renderWithProviders(<QuoteSentPanel deal={deal} quote={makeQuote({ public_access_token: 'tok', public_token_revoked: true })} />);
    expect(screen.queryByText('Копировать ссылку')).not.toBeInTheDocument();
    expect(screen.getByText('Ссылка отозвана')).toBeInTheDocument();
  });
});
