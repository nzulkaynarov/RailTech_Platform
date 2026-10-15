import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MasterDataSettings } from '@/components/Settings/MasterDataSettings';
import { renderWithProviders } from '@/test/renderWithProviders';

const {
  mockCurrencies,
  mockUnits,
  mockCountries,
  mockDeliveryBases,
  createLookupMock,
  updateLookupMock,
  deleteLookupMock,
} = vi.hoisted(() => ({
  mockCurrencies: [
    { code: 'USD', name: 'Доллар США', symbol: '$', sort_order: 1, is_active: true },
    { code: 'UZS', name: 'Узбекский сум', symbol: 'soʻm', sort_order: 2, is_active: true },
  ],
  mockUnits: [
    { code: 'PCE', name: 'Штука', sort_order: 1, is_active: true },
  ],
  mockCountries: [
    { code: 'UZ', name: 'Узбекистан', iso_numeric: '860', sort_order: 1, is_active: true },
  ],
  mockDeliveryBases: [
    { code: 'DAP', name: 'Поставка до пункта', sort_order: 1, is_active: true },
  ],
  createLookupMock: vi.fn(),
  updateLookupMock: vi.fn(),
  deleteLookupMock: vi.fn(),
}));

vi.mock('@/hooks/useMasterData', () => ({
  useCurrencies: () => ({ data: mockCurrencies, isLoading: false, isError: false }),
  useUnits: () => ({ data: mockUnits, isLoading: false, isError: false }),
  useCountries: () => ({ data: mockCountries, isLoading: false, isError: false }),
  useDeliveryBases: () => ({ data: mockDeliveryBases, isLoading: false, isError: false }),
  useCreateLookup: () => ({ mutateAsync: createLookupMock, isPending: false }),
  useUpdateLookup: () => ({ mutateAsync: updateLookupMock, isPending: false }),
  useDeleteLookup: () => ({ mutateAsync: deleteLookupMock, isPending: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('MasterDataSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('рендерит заголовок и вкладку валют по умолчанию', () => {
    renderWithProviders(<MasterDataSettings />);

    expect(screen.getByText('Справочники')).toBeInTheDocument();
    expect(screen.getByText('USD')).toBeInTheDocument();
    expect(screen.getByText('UZS')).toBeInTheDocument();
  });

  it('переключает вкладки на единицы измерения', async () => {
    const user = userEvent.setup();
    renderWithProviders(<MasterDataSettings />);

    const unitsTab = screen.getByRole('tab', { name: /Единицы измерения/i });
    await user.click(unitsTab);

    await waitFor(() => {
      expect(screen.getByText('PCE')).toBeInTheDocument();
      expect(screen.getByText('Штука')).toBeInTheDocument();
    });
  });

  it('открывает диалог добавления новой записи', async () => {
    const user = userEvent.setup();
    renderWithProviders(<MasterDataSettings />);

    await user.click(screen.getByRole('button', { name: /Добавить запись/i }));

    await waitFor(() => {
      expect(screen.getByText('Создание записи')).toBeInTheDocument();
    });
  });
});
