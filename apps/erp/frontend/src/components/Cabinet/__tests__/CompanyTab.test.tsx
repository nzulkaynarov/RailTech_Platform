import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { CompanyTab } from '@/components/Cabinet/CompanyTab';
import { accountsApi } from '@/api/accountsApi';

/**
 * Settings Hub PR 3 — CompanyTab regrouped into three cards (requisites / bank /
 * KYC documents) with UNCHANGED logic: same single-PATCH save, same OWNER gating,
 * same INN lock after KYC verification. These tests pin both the grouping and
 * the preserved behaviour.
 */

// ── Mutable store state fed to the mocked stores (hoisted so the vi.mock
//    factories below can close over it; each test resets via makeUserState). ──
type Entry = { status: 'BUYER' | 'SELLER'; verification: 'verified' | 'pending' | 'rejected' };
type MockUserState = {
  company: {
    id: number | null;
    name: string;
    inn: string;
    kycStatus: 'verified' | 'pending' | 'not_started';
    logoUrl: string | null;
    statusEntries: Entry[];
  };
  activeStatus: 'BUYER' | 'SELLER';
  updateCompany: ReturnType<typeof vi.fn>;
  isViewerMode: boolean;
  capabilities: { permissions: string[] };
};
const userStoreRef = vi.hoisted(() => ({ state: null as unknown as MockUserState }));
const authStoreRef = vi.hoisted(() => ({ workspaceRole: 'OWNER' as string | null }));

vi.mock('@/store/userStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/store/userStore')>();
  return {
    ...actual,
    useUserStore: (selector?: (s: MockUserState) => unknown) =>
      selector ? selector(userStoreRef.state) : userStoreRef.state,
  };
});

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (s: { user: { workspace_role: string | null } }) => unknown) =>
    selector({ user: { workspace_role: authStoreRef.workspaceRole } }),
}));

vi.mock('@/hooks/useMasterData', () => ({
  useCountries: () => ({ data: [{ id: 1, name: 'Узбекистан' }] }),
}));

vi.mock('@/api/accountsApi', () => ({
  accountsApi: {
    getCompanyDetail: vi.fn(),
    updateCompany: vi.fn(),
    uploadCompanyLogo: vi.fn(),
    deleteCompanyLogo: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

function makeUserState(
  overrides: Partial<MockUserState['company']> = {},
  permissions: string[] = [],
): MockUserState {
  return {
    company: {
      id: 7,
      name: 'Рельсы',
      inn: '123456789',
      kycStatus: 'pending',
      logoUrl: null,
      statusEntries: [{ status: 'SELLER', verification: 'verified' }],
      ...overrides,
    },
    activeStatus: 'SELLER',
    updateCompany: vi.fn(),
    isViewerMode: false,
    capabilities: { permissions },
  };
}

const detailResponse = {
  id: 7,
  name: 'ООО Рельсы',
  inn: '123456789',
  contact_person: 'Иван Иванов',
  phone: '+998901234567',
  email: 'info@relsy.uz',
  website: '',
  legal_address: 'Ташкент, ул. Вокзальная 1',
  bank_account: '20208000900000000001',
  mfo: '00014',
  country: 1,
  has_iso9001: false,
  kyc_documents: [],
  verification_status: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  userStoreRef.state = makeUserState();
  authStoreRef.workspaceRole = 'OWNER';
  vi.mocked(accountsApi.getCompanyDetail).mockResolvedValue(detailResponse);
  vi.mocked(accountsApi.updateCompany).mockResolvedValue(detailResponse);
});

describe('CompanyTab (settings hub PR 3 grouping)', () => {
  it('renders the three group cards and populates fields from the full company record', async () => {
    renderWithProviders(<CompanyTab />);

    // Three cards of the regrouped form.
    expect(screen.getByText('Реквизиты компании')).toBeInTheDocument();
    expect(screen.getByText('Банковские реквизиты')).toBeInTheDocument();
    expect(screen.getByText('KYC-документы')).toBeInTheDocument();

    // Fields hydrate from getCompanyDetail (not the lightweight /me projection).
    await waitFor(() => {
      expect(screen.getByDisplayValue('20208000900000000001')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('ООО Рельсы')).toBeInTheDocument();
    expect(screen.getByDisplayValue('00014')).toBeInTheDocument();
    expect(accountsApi.getCompanyDetail).toHaveBeenCalledWith(7);

    // OWNER sees the save action; INN editable while KYC is not verified.
    expect(screen.getByRole('button', { name: /Сохранить данные/ })).toBeInTheDocument();
    expect(screen.getByDisplayValue('123456789')).toBeEnabled();
  });

  it('locks INN after KYC verification and omits it from the save payload', async () => {
    userStoreRef.state = makeUserState({ kycStatus: 'verified' });
    renderWithProviders(<CompanyTab />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('ООО Рельсы')).toBeInTheDocument();
    });
    // INN is a checked legal identifier once verified — disabled even for OWNER.
    expect(screen.getByDisplayValue('123456789')).toBeDisabled();
    expect(screen.getByDisplayValue('ООО Рельсы')).toBeEnabled();

    await userEvent.click(screen.getByRole('button', { name: /Сохранить данные/ }));
    await waitFor(() => {
      expect(accountsApi.updateCompany).toHaveBeenCalledTimes(1);
    });
    const [calledId, payload] = vi.mocked(accountsApi.updateCompany).mock.calls[0];
    expect(calledId).toBe(7);
    expect(payload).toEqual(expect.objectContaining({ name: 'ООО Рельсы', mfo: '00014' }));
    expect(payload).not.toHaveProperty('inn');
  });

  it('renders read-only for a plain non-OWNER member (no save, inputs disabled, hint shown)', async () => {
    authStoreRef.workspaceRole = 'SALES_MANAGER';
    renderWithProviders(<CompanyTab />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('ООО Рельсы')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('ООО Рельсы')).toBeDisabled();
    expect(screen.getByDisplayValue('20208000900000000001')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Сохранить данные/ })).not.toBeInTheDocument();
    expect(
      screen.getByText('Для изменения данных компании обратитесь к администратору'),
    ).toBeInTheDocument();
  });

  // ADR-0005 U2 — a delegated «Администратор компании» (non-OWNER WorkspaceRole holding the
  // CompanyRole settings.edit permission) passed the section gate; the form must be editable,
  // not a dead read-only shell. Mirrors the backend member_has_permission('settings.edit') grant.
  it('lets a delegated admin (non-OWNER with settings.edit) edit and save', async () => {
    authStoreRef.workspaceRole = 'SALES_MANAGER';
    userStoreRef.state = makeUserState({}, ['settings.edit']);
    renderWithProviders(<CompanyTab />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('ООО Рельсы')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('ООО Рельсы')).toBeEnabled();
    expect(screen.getByDisplayValue('20208000900000000001')).toBeEnabled();
    expect(
      screen.queryByText('Для изменения данных компании обратитесь к администратору'),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Сохранить данные/ }));
    await waitFor(() => {
      expect(accountsApi.updateCompany).toHaveBeenCalledTimes(1);
    });
  });
});
