import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { ChargeTemplatesSettings } from './ChargeTemplatesSettings';
import { crmApi, type ChargeTemplate } from '@/api/crmApi';
import { masterDataApi } from '@/api/masterDataApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useChargeTemplates / useChargeTypes /
// useDeliveryBases react-query hooks run against these mocks (never the network).
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: {
      ...actual.crmApi,
      getChargeTemplates: vi.fn(),
      getChargeTypes: vi.fn(),
      createChargeTemplate: vi.fn(),
      deleteChargeTemplate: vi.fn(),
    },
  };
});

vi.mock('@/api/masterDataApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/masterDataApi')>();
  return {
    ...actual,
    masterDataApi: { ...actual.masterDataApi, getDeliveryBases: vi.fn() },
  };
});

const TEMPLATES: ChargeTemplate[] = [
  {
    id: 1,
    delivery_basis: 'DAP',
    charge_type: 'FREIGHT',
    charge_type_name: 'Фрахт',
    default_amount: '0',
    default_rate_percent: '5.00',
    is_deduction: false,
    sort_order: 0,
    is_active: true,
  },
  {
    id: 2,
    delivery_basis: 'EXW',
    charge_type: 'PACKAGING',
    charge_type_name: 'Упаковка',
    default_amount: '150000',
    default_rate_percent: null,
    is_deduction: true,
    sort_order: 1,
    is_active: true,
  },
];

describe('ChargeTemplatesSettings', () => {
  beforeEach(() => {
    vi.mocked(crmApi.getChargeTemplates).mockResolvedValue(TEMPLATES);
    vi.mocked(crmApi.getChargeTypes).mockResolvedValue([]);
    vi.mocked(masterDataApi.getDeliveryBases).mockResolvedValue([]);
    vi.mocked(crmApi.deleteChargeTemplate).mockResolvedValue(undefined as never);
  });

  // ResponsiveDataTable renders BOTH a desktop table and a mobile stacked list
  // (CSS-hidden, both in the DOM) — row content appears twice, so query with *All*.

  it('renders the template rows with basis, type and default value', async () => {
    renderWithProviders(<ChargeTemplatesSettings />);
    expect((await screen.findAllByText('DAP')).length).toBeGreaterThanOrEqual(1);
    // FREIGHT is a known charge-type code → the localized label replaces the RU-only
    // DB `charge_type_name`. (An unknown code — PACKAGING below — falls back to the raw name.)
    expect(screen.getAllByText('Фрахт / логистика').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('5.00%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('150000').length).toBeGreaterThanOrEqual(1);
    // The deduction row is flagged «Скидка».
    expect(screen.getAllByText('Скидка').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the empty state when the company has no templates', async () => {
    vi.mocked(crmApi.getChargeTemplates).mockResolvedValue([]);
    renderWithProviders(<ChargeTemplatesSettings />);
    expect(
      await screen.findByText('Пока нет своих шаблонов — используются глобальные дефолты.'),
    ).toBeInTheDocument();
  });

  it('deletes a template only after the confirmation dialog is accepted', async () => {
    renderWithProviders(<ChargeTemplatesSettings />);
    await screen.findAllByText('DAP');

    fireEvent.click(screen.getAllByRole('button', { name: 'Удалить' })[0]);

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Удалить шаблон расхода?')).toBeInTheDocument();
    expect(crmApi.deleteChargeTemplate).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    await waitFor(() => expect(crmApi.deleteChargeTemplate).toHaveBeenCalledWith(1));
  });
});
