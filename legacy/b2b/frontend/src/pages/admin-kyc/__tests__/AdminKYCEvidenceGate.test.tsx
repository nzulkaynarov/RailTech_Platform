import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AdminKYCPage } from '../index';
import { accountsApi, type Company, type KYCDocument } from '@/api/accountsApi';
import { adminApi } from '@/api/adminApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Политика владельца 2026-06-03: выдать L2 без загруженных документов МОЖНО, но это
// «предупреждение + обоснование». До 24-08 её соблюдал один диалог из трёх на этом экране —
// меню строки и массовое действие выдавали уровень молча и с пустым reason в журнале.
vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return { ...actual, accountsApi: { ...actual.accountsApi, getCompanies: vi.fn(), verifyCompany: vi.fn() } };
});
vi.mock('@/api/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/adminApi')>();
  return { ...actual, adminApi: { ...actual.adminApi, bulkVerifyKYC: vi.fn() } };
});

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function makeCompany(over: Partial<Company> & { id: number; name: string }): Company {
  return {
    inn: '900000001',
    verification_status_code: 'PROFILE_SUBMITTED',
    kyc_documents: [],
    created_at: '2026-08-01T10:00:00Z',
    ...over,
  } as Company;
}

const charter = {
  id: 7,
  doc_type: 1,
  doc_type_code: 'CHARTER',
  doc_type_display: 'Устав',
  file: '/media/charter.pdf',
  original_filename: 'charter.pdf',
} as KYCDocument;

const bare = makeCompany({ id: 1, name: 'Без документов' });
const documented = makeCompany({ id: 2, name: 'С документами', inn: '900000002', kyc_documents: [charter] });
const alreadyL1 = makeCompany({ id: 3, name: 'И так в L1', verification_status_code: 'L1_UNVERIFIED' });

async function rowActionItem(user: ReturnType<typeof userEvent.setup>, rowName: string, actionLabel: string) {
  const row = screen.getByText(rowName).closest('tr') as HTMLElement;
  await user.click(within(row).getByRole('button', { name: 'Действия' }));
  return screen.findByRole('menuitem', { name: new RegExp(actionLabel) });
}

describe('Реестр KYC: выдача уровня без доказательств', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (accountsApi.getCompanies as ReturnType<typeof vi.fn>).mockResolvedValue([bare, documented, alreadyL1]);
    (accountsApi.verifyCompany as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 'ok' });
    (adminApi.bulkVerifyKYC as ReturnType<typeof vi.fn>).mockResolvedValue({ approved: 2, skipped: [] });
  });

  it('меню строки: подтверждение компании без документов требует причины', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminKYCPage />);
    await waitFor(() => expect(screen.getByText('Без документов')).toBeInTheDocument());

    await user.click(await rowActionItem(user, 'Без документов', 'Подтвердить KYC'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Компания подтверждается без/)).toBeInTheDocument();

    const confirm = within(dialog).getByRole('button', { name: 'Одобрить' });
    expect(confirm).toBeDisabled();
    expect(accountsApi.verifyCompany).not.toHaveBeenCalled();

    await user.type(within(dialog).getByRole('textbox'), 'сверено по реестру ГНК');
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(accountsApi.verifyCompany).toHaveBeenCalledWith(1, 'L2_VERIFIED', undefined, 'сверено по реестру ГНК'),
    );
  });

  it('меню строки: у компании с документами причина остаётся необязательной', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminKYCPage />);
    await waitFor(() => expect(screen.getByText('С документами')).toBeInTheDocument());

    await user.click(await rowActionItem(user, 'С документами', 'Подтвердить KYC'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/Компания подтверждается без/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Одобрить' })).toBeEnabled();
  });

  it('«Отозвать верификацию» недоступна у компании, которая и так в L1', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminKYCPage />);
    await waitFor(() => expect(screen.getByText('И так в L1')).toBeInTheDocument());

    const disabledItem = await rowActionItem(user, 'И так в L1', 'Отозвать верификацию');
    expect(disabledItem).toHaveAttribute('aria-disabled', 'true');

    await user.keyboard('{Escape}');
    const liveItem = await rowActionItem(user, 'Без документов', 'Отозвать верификацию');
    expect(liveItem).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('массовое действие: называет компании без доказательств и требует причину', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminKYCPage />);
    await waitFor(() => expect(screen.getByText('Без документов')).toBeInTheDocument());

    const bareRow = screen.getByText('Без документов').closest('tr') as HTMLElement;
    const docRow = screen.getByText('С документами').closest('tr') as HTMLElement;
    await user.click(within(bareRow).getByRole('checkbox'));
    await user.click(within(docRow).getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: /Одобрить L2/ }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Без проверенных данных: 1 из выборки \(Без документов\)/)).toBeInTheDocument();
    // Старый текст обещал предохранитель, которого нет: «Пропуски (нет документов) выведутся отдельно».
    expect(within(dialog).queryByText(/выведутся отдельно/)).not.toBeInTheDocument();

    const confirm = within(dialog).getByRole('button', { name: 'Одобрить' });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByRole('textbox'), 'документы придут после регистрации');
    await user.click(confirm);

    await waitFor(() =>
      expect(adminApi.bulkVerifyKYC).toHaveBeenCalledWith([1, 2], 'L2_VERIFIED', 'документы придут после регистрации'),
    );
  });
});
