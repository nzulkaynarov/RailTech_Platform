import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { CounterpartiesPage } from '../CounterpartiesPage';
import { crmApi, type Relationship } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useRelationships / useCompanyTimeline
// react-query hooks run against these mocks (never the network).
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, getRelationships: vi.fn(), getTimeline: vi.fn() },
  };
});

function makeEdge(overrides: Partial<Relationship> & { id: number }): Relationship {
  return {
    direction: 'CLIENT',
    stage: 'ACTIVE',
    source: 'OFFLINE_CREATED',
    counterparty: { id: overrides.id * 10, name: 'X', inn: null, stated_inn: '', is_registered: true },
    owner_member: null,
    owner_member_name: '',
    contacts_count: 0,
    first_interaction_at: '2026-07-01T10:00:00Z',
    last_interaction_at: '2026-07-05T10:00:00Z',
    deals_count: 0,
    won_count: 0,
    gmv: '0',
    created_at: '2026-07-01T10:00:00Z',
    ...overrides,
  };
}

const EDGES: Relationship[] = [
  makeEdge({
    id: 1,
    counterparty: { id: 10, name: 'ООО Магистраль', inn: '300123456', stated_inn: '', is_registered: true },
    deals_count: 3,
    won_count: 1,
  }),
  makeEdge({
    id: 2,
    counterparty: { id: 20, name: 'Оффлайн Клиент', inn: null, stated_inn: '301999888', is_registered: false },
    stage: 'PROSPECT',
  }),
];

describe('CounterpartiesPage', () => {
  beforeEach(() => {
    vi.mocked(crmApi.getRelationships).mockResolvedValue(EDGES);
    vi.mocked(crmApi.getTimeline).mockResolvedValue([]);
  });

  // ResponsiveDataTable renders BOTH a desktop table and a mobile stacked list
  // (CSS-hidden, both in the DOM) — row content appears twice, so query with *All*.

  it('renders the client book rows with the offline badge', async () => {
    renderWithProviders(<CounterpartiesPage direction="CLIENT" />);
    expect((await screen.findAllByText('ООО Магистраль')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Оффлайн Клиент').length).toBeGreaterThanOrEqual(1);
    // The unregistered counterparty is flagged «Оффлайн».
    expect(screen.getAllByText('Оффлайн').length).toBeGreaterThanOrEqual(1);
  });

  it('offers «Новый клиент» only in the client book', async () => {
    renderWithProviders(<CounterpartiesPage direction="CLIENT" />);
    await screen.findAllByText('ООО Магистраль');
    expect(screen.getByRole('button', { name: /Новый клиент/ })).toBeInTheDocument();
  });

  it('hides «Новый клиент» in the supplier book', async () => {
    renderWithProviders(<CounterpartiesPage direction="SUPPLIER" />);
    await screen.findAllByText('ООО Магистраль');
    expect(screen.queryByRole('button', { name: /Новый клиент/ })).not.toBeInTheDocument();
  });

  it('opens the counterparty detail sheet on row click', async () => {
    renderWithProviders(<CounterpartiesPage direction="CLIENT" />);
    fireEvent.click((await screen.findAllByText('ООО Магистраль'))[0]);
    // The sheet shows the source label — proof the detail panel rendered.
    await waitFor(() => expect(screen.getByText('Заведён вручную')).toBeInTheDocument());
  });
});
