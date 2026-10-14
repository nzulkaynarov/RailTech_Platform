import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { CounterpartiesPage } from '../CounterpartiesPage';
import { groupContactsByCompany } from '@/lib/clientBook';
import { crmApi, type Contact } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useContacts / useCompanyTimeline react-query hooks
// run against these mocks (never the network). Книга клиентов строится по контактам
// `accounts/contacts/` с M1-ERP-02 волна 3.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, getContacts: vi.fn(), getTimeline: vi.fn() },
  };
});

function contact(overrides: Partial<Contact> & { id: number; company: number }): Contact {
  return {
    company_name: 'X',
    company_is_registered: true,
    name: 'Контакт',
    email: '',
    phone: '',
    position: '',
    is_primary: false,
    created_at: '2026-07-01T10:00:00Z',
    ...overrides,
  };
}

const CONTACTS: Contact[] = [
  contact({ id: 1, company: 10, company_name: 'ООО Магистраль', name: 'Алишер', phone: '+998901112233', is_primary: true }),
  contact({ id: 2, company: 10, company_name: 'ООО Магистраль', name: 'Дилноза', email: 'd@example.com', created_at: '2026-07-02T10:00:00Z' }),
  contact({ id: 3, company: 20, company_name: 'Оффлайн Клиент', company_is_registered: false, name: 'Бахтиёр', phone: '+998907776655' }),
];

describe('groupContactsByCompany', () => {
  it('groups contacts by company and picks the primary contact', () => {
    const rows = groupContactsByCompany(CONTACTS);
    expect(rows).toHaveLength(2);
    const magistral = rows.find((row) => row.id === 10)!;
    expect(magistral.contacts).toHaveLength(2);
    expect(magistral.primary?.name).toBe('Алишер');
    expect(magistral.createdAt).toBe('2026-07-01T10:00:00Z');
  });

  it('falls back to the earliest contact when none is primary', () => {
    const rows = groupContactsByCompany([
      contact({ id: 5, company: 30, name: 'Поздний', created_at: '2026-08-02T10:00:00Z' }),
      contact({ id: 4, company: 30, name: 'Ранний', created_at: '2026-08-01T10:00:00Z' }),
    ]);
    expect(rows[0].primary?.name).toBe('Ранний');
  });
});

describe('CounterpartiesPage', () => {
  beforeEach(() => {
    vi.mocked(crmApi.getContacts).mockResolvedValue(CONTACTS);
    vi.mocked(crmApi.getTimeline).mockResolvedValue([]);
  });

  // ResponsiveDataTable renders BOTH a desktop table and a mobile stacked list
  // (CSS-hidden, both in the DOM) — row content appears twice, so query with *All*.

  it('renders one row per client company with the offline badge', async () => {
    renderWithProviders(<CounterpartiesPage />);
    expect((await screen.findAllByText('ООО Магистраль')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Оффлайн Клиент').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Оффлайн').length).toBeGreaterThanOrEqual(1);
  });

  it('offers «Новый клиент»', async () => {
    renderWithProviders(<CounterpartiesPage />);
    await screen.findAllByText('ООО Магистраль');
    expect(screen.getByRole('button', { name: /Новый клиент/ })).toBeInTheDocument();
  });

  it('opens the client sheet with all contacts on row click', async () => {
    renderWithProviders(<CounterpartiesPage />);
    fireEvent.click((await screen.findAllByText('ООО Магистраль'))[0]);
    await waitFor(() => expect(screen.getByText('Контакты')).toBeInTheDocument());
    expect(screen.getAllByText('Дилноза').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Основной')).toBeInTheDocument();
  });
});
