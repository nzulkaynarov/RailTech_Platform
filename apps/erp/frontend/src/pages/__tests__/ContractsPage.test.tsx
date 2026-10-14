import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { ContractsPage } from '../ContractsPage';
import { contractsApi, type Contract } from '@/api/contractsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useContracts / useSignContractManager
// react-query hooks run against these mocks (never the network).
vi.mock('@/api/contractsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/contractsApi')>();
  return {
    ...actual,
    contractsApi: {
      ...actual.contractsApi,
      list: vi.fn(),
      get: vi.fn(),
      signManager: vi.fn(),
      uploadSigned: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

function makeContract(overrides: Partial<Contract> & { id: number }): Contract {
  return {
    deal: 42,
    quote: 7,
    number: 'CT-001',
    status: 'PENDING_MANAGER',
    total_amount: '1000000.00',
    currency: null,
    pdf_file: null,
    pdf_url: null,
    signed_file: null,
    signed_file_url: null,
    client_signer: null,
    client_signer_name: null,
    client_signed_at: null,
    manager_signer: null,
    manager_signer_name: null,
    manager_signed_at: null,
    viewer_can_sign_manager: true,
    valid_from: null,
    valid_until: null,
    invoice_id: null,
  wording_selections: {},
    notes: '',
    created_at: '2026-07-08T10:00:00Z',
    updated_at: '2026-07-08T10:00:00Z',
    ...overrides,
  };
}

const PENDING = makeContract({ id: 1 });
const SIGNED = makeContract({
  id: 1,
  status: 'SIGNED',
  client_signed_at: '2026-07-08T11:00:00Z',
  client_signer_name: 'Иван Клиент',
  manager_signed_at: '2026-07-08T11:30:00Z',
  manager_signer_name: 'Пётр Продавец',
});

describe('ContractsPage', () => {
  // Toggled true once the sign mutation runs, so the LIST refetch returns the
  // signed contract — deterministic regardless of how many times list() is called.
  let signedState = false;

  beforeEach(() => {
    signedState = false;
    vi.mocked(contractsApi.list).mockImplementation(async () => (signedState ? [SIGNED] : [PENDING]));
    vi.mocked(contractsApi.signManager).mockImplementation(async () => {
      signedState = true;
      return SIGNED;
    });
  });

  it('предлагает получить PDF, даже если файл ещё не отрисован', async () => {
    // Сервер сам ставит рендер и отвечает 202 (ARCH-03), а `DocumentActions` опрашивает его.
    // Пока кнопку прятало условие «файл уже есть», документ было НЕ ПОЛУЧИТЬ ровно тогда,
    // когда он готовился, — и без единого объяснения (аудит UI, U3). Фикстура намеренно
    // без `pdf_url`.
    renderWithProviders(<ContractsPage />);
    fireEvent.click((await screen.findAllByText('CT-001'))[0]);

    const dialog = await screen.findByRole('dialog');
    expect(PENDING.pdf_url).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Экспорт' })).toBeInTheDocument();
  });

  it('opens the detail panel on row click', async () => {
    renderWithProviders(<ContractsPage />);
    fireEvent.click((await screen.findAllByText('CT-001'))[0]);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('opens the detail panel when Enter is pressed on a focused row', async () => {
    renderWithProviders(<ContractsPage />);
    const numberCell = (await screen.findAllByText('CT-001'))[0];
    const row = numberCell.closest('tr');
    expect(row).not.toBeNull();
    fireEvent.keyDown(row as HTMLElement, { key: 'Enter' });
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('updates the panel after a sign mutation resolves — no close+reopen', async () => {
    renderWithProviders(<ContractsPage />);
    fireEvent.click((await screen.findAllByText('CT-001'))[0]);

    // Back office on a PENDING_MANAGER contract → the "sign as manager" button is offered.
    const signButton = await screen.findByRole('button', { name: 'Подписать (продавец)' });
    fireEvent.click(signButton);

    // After the mutation resolves the list refetches (signed contract) and the LIVE
    // panel re-derives: the manager signature shows and the sign button disappears.
    await waitFor(() => expect(screen.getByText(/Пётр Продавец/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Подписать (продавец)' })).not.toBeInTheDocument();
  });

  it('не предлагает подписать договор за клиента (клиент подписывает в Cabinet)', async () => {
    renderWithProviders(<ContractsPage />);
    fireEvent.click((await screen.findAllByText('CT-001'))[0]);
    await screen.findByRole('dialog');
    expect(screen.queryByRole('button', { name: 'Подписать (клиент)' })).not.toBeInTheDocument();
  });
});
