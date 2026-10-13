import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AdminCompaniesPage } from '../AdminCompaniesPage';
import { accountsApi, type Company } from '@/api/accountsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Компанию с историей не удаляет ни один эталон: Odoo отказывает и предлагает Archive,
// Salesforce не даёт удалить даже пользователя, Stripe не удаляет финансовый факт. Способность
// приходит с сервера ЗАРАНЕЕ (Salesforce `deletable`) — кнопка, которая гарантированно
// откажет, это тот же тупик, только вежливый.
vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      getCompanies: vi.fn(),
      deleteCompany: vi.fn(),
      archiveCompany: vi.fn(),
      unarchiveCompany: vi.fn(),
    },
  };
});

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function makeCompany(over: Partial<Company> & { id: number; name: string }): Company {
  return {
    inn: '900000001',
    verification_status_code: 'L2_VERIFIED',
    company_types: ['CLIENT'],
    is_active: true,
    can_delete: true,
    delete_blocker: null,
    created_at: '2026-08-01T10:00:00Z',
    ...over,
  } as Company;
}

const empty = makeCompany({ id: 1, name: 'Пустая компания' });
const withHistory = makeCompany({
  id: 2,
  name: 'С историей',
  inn: '900000002',
  can_delete: false,
  delete_blocker: 'COMPANY_HAS_HISTORY:deals,members',
});
const archived = makeCompany({ id: 3, name: 'Архивная', inn: '900000003', is_active: false });

async function rowActionItem(user: ReturnType<typeof userEvent.setup>, rowName: string, label: string) {
  const row = screen.getByText(rowName).closest('tr') as HTMLElement;
  await user.click(within(row).getByRole('button', { name: 'Действия' }));
  return screen.findByRole('menuitem', { name: new RegExp(label) });
}

describe('Реестр компаний: архив вместо удаления', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (accountsApi.getCompanies as ReturnType<typeof vi.fn>).mockResolvedValue([empty, withHistory, archived]);
    (accountsApi.archiveCompany as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (accountsApi.unarchiveCompany as ReturnType<typeof vi.fn>).mockResolvedValue({});
  });

  it('«Удалить» недоступно у компании с историей и доступно у пустой', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCompaniesPage />);
    await waitFor(() => expect(screen.getByText('С историей')).toBeInTheDocument());

    const blocked = await rowActionItem(user, 'С историей', 'Удалить');
    expect(blocked).toHaveAttribute('aria-disabled', 'true');

    await user.keyboard('{Escape}');
    const allowed = await rowActionItem(user, 'Пустая компания', 'Удалить');
    expect(allowed).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('архивация требует причины и уходит на сервер вместе с ней', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCompaniesPage />);
    await waitFor(() => expect(screen.getByText('С историей')).toBeInTheDocument());

    await user.click(await rowActionItem(user, 'С историей', 'Архивировать'));

    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Архивировать' });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByRole('textbox'), 'компания закрылась');
    await user.click(confirm);

    await waitFor(() => expect(accountsApi.archiveCompany).toHaveBeenCalledWith(2, 'компания закрылась'));
  });

  it('архивную компанию возвращают в оборот одним действием', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCompaniesPage />);
    await waitFor(() => expect(screen.getByText('Архивная')).toBeInTheDocument());

    await user.click(await rowActionItem(user, 'Архивная', 'Вернуть в оборот'));

    await waitFor(() => expect(accountsApi.unarchiveCompany).toHaveBeenCalledWith(3));
  });

  it('у архивной компании «Архивировать» недоступно, у активной — «Вернуть в оборот»', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCompaniesPage />);
    await waitFor(() => expect(screen.getByText('Архивная')).toBeInTheDocument());

    expect(await rowActionItem(user, 'Архивная', 'Архивировать')).toHaveAttribute('aria-disabled', 'true');
    await user.keyboard('{Escape}');
    expect(await rowActionItem(user, 'Пустая компания', 'Вернуть в оборот')).toHaveAttribute('aria-disabled', 'true');
  });

  it('есть вкладка «Архивные», и она просит у сервера именно архив', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCompaniesPage />);
    await waitFor(() => expect(screen.getByText('Пустая компания')).toBeInTheDocument());

    await user.click(screen.getByRole('tab', { name: 'Архивные' }));

    await waitFor(() =>
      expect(accountsApi.getCompanies).toHaveBeenCalledWith(expect.objectContaining({ is_active: 'false' })),
    );
  });
});
