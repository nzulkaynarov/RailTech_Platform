import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminLeadsPage from '../AdminLeadsPage';
import { crmApi, type Lead } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer — the real useLeads / useRouteLead react-query hooks execute
// against these mocks (never the network).
//
// Механика изменилась: площадка НАЗНАЧАЕТ лид компании, сделку создаёт принимающая сторона
// (Salesforce Lead Queue + Take Ownership). Прежнее «Конвертировать в сделку» совмещало оба
// действия в одном вызове, который у штатного оператора отказывал всегда.
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, listLeads: vi.fn(), routeLead: vi.fn(), rejectLead: vi.fn() },
  };
});
vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      getCompanies: vi.fn().mockResolvedValue([{ id: 7, name: 'ООО Получатель', inn: '900000007' }]),
    },
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

  it('назначает лид компании — с выбранной компанией и обоснованием', async () => {
    const user = userEvent.setup();
    (crmApi.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 1 });
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('New Lead')).toBeInTheDocument());

    // open the first row's kebab (userEvent dispatches the pointer sequence Radix needs)
    await user.click(screen.getAllByRole('button', { name: 'Действия' })[0]);
    await user.click(await screen.findByText('Назначить компании'));

    const dialog = await screen.findByRole('dialog');
    // Причина обязательна: назначение — операторское действие над чужой работой.
    expect(within(dialog).getByRole('button', { name: 'Назначить' })).toBeDisabled();

    await user.click(within(dialog).getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: 'ООО Получатель' }));
    await user.type(within(dialog).getByRole('textbox'), 'профиль совпал');
    await user.click(within(dialog).getByRole('button', { name: 'Назначить' }));

    await waitFor(() => expect(crmApi.routeLead).toHaveBeenCalledWith(1, 7, 'профиль совпал'));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it('обработанный лид назначить нельзя — действие недоступно', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('Done Lead')).toBeInTheDocument());

    const row = screen.getByText('Done Lead').closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Действия' }));

    expect(await screen.findByRole('menuitem', { name: /Назначить компании/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('отклонение закрывает лид с причиной и без создания сделки', async () => {
    const user = userEvent.setup();
    (crmApi.rejectLead as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 1 });
    renderWithProviders(<AdminLeadsPage />);
    await waitFor(() => expect(screen.getByText('New Lead')).toBeInTheDocument());

    await user.click(screen.getAllByRole('button', { name: 'Действия' })[0]);
    await user.click(await screen.findByText(/Отклонить/));

    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'спам');
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(crmApi.rejectLead).toHaveBeenCalledWith(1, 'спам'));
  });
});
