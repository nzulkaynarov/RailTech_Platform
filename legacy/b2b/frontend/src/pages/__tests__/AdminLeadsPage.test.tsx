import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminLeadsPage from '../AdminLeadsPage';
import { crmApi, type Lead } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer — the real useLeads / useConvertLead react-query
// hooks execute against these mocks (never the network).
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, listLeads: vi.fn(), convertLead: vi.fn() },
  };
});

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function makeLead(overrides: Partial<Lead> & { id: number }): Lead {
  return {
    name: 'Ivan Petrov',
    company: 'ООО Ромашка',
    email: 'ivan@romashka.uz',
    phone: '+998901112233',
    message: 'Нужны тормозные колодки',
    is_processed: false,
    ...overrides,
  };
}

describe('AdminLeadsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (crmApi.listLeads as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeLead({ id: 1, name: 'New Lead', is_processed: false }),
      makeLead({ id: 2, name: 'Done Lead', is_processed: true, email: 'done@x.uz' }),
    ]);
  });

  it('renders leads from the API with localized columns', async () => {
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('New Lead')).toBeInTheDocument());
    expect(screen.getByText('Done Lead')).toBeInTheDocument();
    expect(screen.getByText('Лиды')).toBeInTheDocument(); // localized title resolves
  });

  it('shows the localized empty state when there are no leads', async () => {
    (crmApi.listLeads as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('Лидов пока нет')).toBeInTheDocument());
  });

  it('converts a lead through the real useConvertLead mutation and toasts the deal id', async () => {
    const user = userEvent.setup();
    (crmApi.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({ deal_id: 42, stage: 'DRAFT' });
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('New Lead')).toBeInTheDocument());

    // open the first row's kebab (userEvent dispatches the pointer sequence Radix needs)
    await user.click(screen.getAllByRole('button', { name: 'Действия' })[0]);
    await user.click(await screen.findByText('Конвертировать в сделку'));

    await waitFor(() => expect(crmApi.convertLead).toHaveBeenCalledWith(1, undefined));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it('surfaces a mapped error toast when convert fails (no matching company)', async () => {
    const user = userEvent.setup();
    (crmApi.convertLead as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'LEAD_NO_CLIENT_COMPANY' } },
    });
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('New Lead')).toBeInTheDocument());
    await user.click(screen.getAllByRole('button', { name: 'Действия' })[0]);
    await user.click(await screen.findByText('Конвертировать в сделку'));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
