import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AdminMasterDataPage } from '../AdminMasterDataPage';
import { masterDataApi, type LookupItem } from '@/api/masterDataApi';
import { renderWithProviders } from '@/test/renderWithProviders';
import i18n from '@/i18n';

// Отключённая строка справочника исчезала из списка НАВСЕГДА: вернуть её через интерфейс
// было нельзя, хотя гасил её тот же оператор. Эталон (Odoo Archive, Stripe Archived) держит
// такие записи за фильтром, а не прячет. Плюс: отказ удаления обязан называть причину —
// раньше приходила пятисотка и общий тост «Не удалось удалить».
vi.mock('@/api/masterDataApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/masterDataApi')>();
  return {
    ...actual,
    masterDataApi: {
      ...actual.masterDataApi,
      getCountries: vi.fn(),
      getCurrencies: vi.fn(),
      getUnits: vi.fn(),
      getDeliveryBases: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
    },
  };
});

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const activeUnit: LookupItem = { id: 1, code: 'H87', name: 'шт.', sort_order: 10, is_active: true };
const offUnit: LookupItem = { id: 2, code: 'SBX_OFF', name: 'Отключённая', sort_order: 20, is_active: false };

function mockLists(includeInactiveRows: boolean) {
  const rows = includeInactiveRows ? [activeUnit, offUnit] : [activeUnit];
  (masterDataApi.getUnits as ReturnType<typeof vi.fn>).mockImplementation((includeInactive?: boolean) =>
    Promise.resolve(includeInactive ? [activeUnit, offUnit] : rows.filter((row) => row.is_active)),
  );
}

async function openUnitsTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: 'Единицы измерения' }));
}

describe('Справочники: отказ с причиной и путь назад для отключённой строки', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (masterDataApi.getCountries as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (masterDataApi.getCurrencies as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (masterDataApi.getDeliveryBases as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (masterDataApi.update as ReturnType<typeof vi.fn>).mockResolvedValue({});
    mockLists(false);
  });

  it('отказ удаления называет причину, а не «не удалось»', async () => {
    const user = userEvent.setup();
    (masterDataApi.remove as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'LOOKUP_IN_USE:Товар' } },
    });
    renderWithProviders(<AdminMasterDataPage />);
    await openUnitsTab(user);
    await waitFor(() => expect(screen.getByText('H87')).toBeInTheDocument());

    const row = screen.getByText('H87').closest('tr') as HTMLElement;
    await user.click(within(row).getAllByRole('button')[1]);

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(i18n.t('apiErrors.LOOKUP_IN_USE')));
    expect(toast.error).not.toHaveBeenCalledWith('Не удалось удалить');
  });

  it('переключатель показывает отключённые строки, и их видно как отключённые', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminMasterDataPage />);
    await openUnitsTab(user);
    await waitFor(() => expect(screen.getByText('H87')).toBeInTheDocument());
    expect(screen.queryByText('SBX_OFF')).not.toBeInTheDocument();

    await user.click(screen.getByRole('switch'));

    await waitFor(() => expect(screen.getByText('SBX_OFF')).toBeInTheDocument());
    const row = screen.getByText('SBX_OFF').closest('tr') as HTMLElement;
    expect(within(row).getByText('Отключена')).toBeInTheDocument();
  });

  it('отключённую строку можно включить обратно одной кнопкой', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminMasterDataPage />);
    await openUnitsTab(user);
    await user.click(screen.getByRole('switch'));
    await waitFor(() => expect(screen.getByText('SBX_OFF')).toBeInTheDocument());

    const row = screen.getByText('SBX_OFF').closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Включить обратно' }));

    await waitFor(() =>
      expect(masterDataApi.update).toHaveBeenCalledWith('units', 2, { is_active: true }),
    );
  });

  it('у активной строки кнопки возврата нет — она бессмысленна', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminMasterDataPage />);
    await openUnitsTab(user);
    await waitFor(() => expect(screen.getByText('H87')).toBeInTheDocument());

    const row = screen.getByText('H87').closest('tr') as HTMLElement;
    expect(within(row).queryByRole('button', { name: 'Включить обратно' })).not.toBeInTheDocument();
  });
});
