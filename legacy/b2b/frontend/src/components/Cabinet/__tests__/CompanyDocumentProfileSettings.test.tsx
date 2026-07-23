import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { CompanyDocumentProfileSettings } from '@/components/Cabinet/CompanyDocumentProfileSettings';
import { accountsApi, type CompanyDocumentProfile } from '@/api/accountsApi';

/**
 * Settings Hub PR 3 — Documents section locked-state (§2.5): while «use company
 * defaults» is ON, the inherited fields are DISABLED with a Lock + tooltip hint
 * («Данные наследуются из профиля компании») instead of the old
 * opacity-50/pointer-events-none hack; own fields (accent color, footer) stay
 * editable. Also pins the side-by-side form/preview layout contract (iframe present).
 */

const canEditRef = vi.hoisted(() => ({ value: true }));

vi.mock('@/hooks/useCapabilities', () => ({
  useHasCompanyPermission: () => canEditRef.value,
}));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (s: { user: { company: { id: number } } }) => unknown) =>
    selector({ user: { company: { id: 7 } } }),
}));

vi.mock('@/api/accountsApi', () => ({
  accountsApi: {
    getCompanyDocumentProfile: vi.fn(),
    previewCompanyDocumentProfile: vi.fn(),
    updateCompanyDocumentProfile: vi.fn(),
    uploadCompanyDocumentLogo: vi.fn(),
  },
}));

const INHERITED_HINT = 'Данные наследуются из профиля компании';

function makeProfile(overrides: Partial<CompanyDocumentProfile> = {}): CompanyDocumentProfile {
  return {
    id: 1,
    company: 7,
    logo_url: null,
    legal_name: 'ООО Документы',
    inn: '987654321',
    legal_address: 'Ташкент, ул. Договорная 2',
    bank_details: 'р/с 20208, МФО 00014',
    signatory_name: 'Директоров Д.Д.',
    signatory_position: 'Директор',
    footer_text: 'Спасибо за сотрудничество',
    accent_color: '',
    use_company_defaults: true,
    show_logo: true,
    show_lead_time: true,
    show_fx_note: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  canEditRef.value = true;
  vi.mocked(accountsApi.getCompanyDocumentProfile).mockResolvedValue(makeProfile());
  vi.mocked(accountsApi.previewCompanyDocumentProfile).mockResolvedValue(
    '<html><body>PREVIEW</body></html>',
  );
});

describe('CompanyDocumentProfileSettings (settings hub PR 3 locked-state)', () => {
  it('disables inherited fields and shows Lock hints while company defaults are on', async () => {
    renderWithProviders(<CompanyDocumentProfileSettings />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('ООО Документы')).toBeInTheDocument();
    });

    // Inherited fields: disabled, per §2.5 — no pointer-events/opacity hack.
    expect(screen.getByDisplayValue('ООО Документы')).toBeDisabled();
    expect(screen.getByDisplayValue('987654321')).toBeDisabled();
    expect(screen.getByDisplayValue('Ташкент, ул. Договорная 2')).toBeDisabled();
    expect(screen.getByDisplayValue('р/с 20208, МФО 00014')).toBeDisabled();
    expect(screen.getByDisplayValue('Директоров Д.Д.')).toBeDisabled();
    expect(screen.getByDisplayValue('Директор')).toBeDisabled();

    // Own (non-inherited) document fields stay editable.
    expect(screen.getByDisplayValue('Спасибо за сотрудничество')).toBeEnabled();

    // One Lock hint per inherited control: logo + 6 fields.
    expect(screen.getAllByText(INHERITED_HINT)).toHaveLength(7);
  });

  it('enables the fields and hides Lock hints when company defaults are off', async () => {
    vi.mocked(accountsApi.getCompanyDocumentProfile).mockResolvedValue(
      makeProfile({ use_company_defaults: false }),
    );
    renderWithProviders(<CompanyDocumentProfileSettings />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('ООО Документы')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('ООО Документы')).toBeEnabled();
    expect(screen.getByDisplayValue('987654321')).toBeEnabled();
    expect(screen.queryByText(INHERITED_HINT)).not.toBeInTheDocument();
  });

  it('renders the live A4 preview iframe next to the form', async () => {
    renderWithProviders(<CompanyDocumentProfileSettings />);

    await waitFor(() => {
      expect(screen.getByTitle('Предпросмотр')).toBeInTheDocument();
    });
    expect(screen.getByTitle('Предпросмотр')).toHaveAttribute(
      'srcdoc',
      expect.stringContaining('PREVIEW'),
    );
  });

  it('shows the owner-only notice without the settings.edit permission', () => {
    canEditRef.value = false;
    renderWithProviders(<CompanyDocumentProfileSettings />);

    expect(
      screen.getByText(
        'Редактировать профиль документов может только администратор компании (владелец).',
      ),
    ).toBeInTheDocument();
    expect(accountsApi.getCompanyDocumentProfile).not.toHaveBeenCalled();
  });
});
