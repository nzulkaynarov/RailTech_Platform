/**
 * Вторая половина цикла заявок на роль компании.
 *
 * Операторская страница модерации работала, а подать заявку было неоткуда: компания, желающая
 * начать продавать, не могла об этом попросить (аудит UI 2026-07-30, §3.2).
 *
 * Проверяется не форма, а то, ради чего эталоны B2B-маркетплейсов её так строят: заявитель
 * видит собственную заявку «на рассмотрении» и понимает, кого ждёт, а роль, которая у него уже
 * есть или уже запрошена, ему повторно не предлагают.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { CompanyRoleSection } from './CompanyRoleSection';
import { accountsApi, type RoleApplication } from '@/api/accountsApi';
import { useUserStore } from '@/store/userStore';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      getCompanyTypes: vi.fn(),
      getRoleApplications: vi.fn(),
      createRoleApplication: vi.fn(),
    },
  };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const TYPES = [
  { id: 1, code: 'CLIENT', name: 'Покупатель' },
  { id: 2, code: 'SUPPLIER', name: 'Поставщик' },
  { id: 3, code: 'MANUFACTURER', name: 'Производитель' },
];

function makeApplication(overrides: Partial<RoleApplication> & { id: number }): RoleApplication {
  return {
    company: 10,
    company_name: 'ООО Тест',
    company_inn: '123',
    requested_type: 2,
    requested_type_name: 'Поставщик',
    requested_type_code: 'SUPPLIER',
    status: 'PENDING',
    status_display: 'На рассмотрении',
    submitted_by: 1,
    submitted_by_email: 'owner@test.uz',
    contract_file: null,
    nda_file: null,
    partnership_agreement: null,
    reviewed_by: null,
    reviewed_by_email: null,
    review_notes: '',
    reviewed_at: null,
    created_at: '2026-07-30T10:00:00Z',
    updated_at: '2026-07-30T10:00:00Z',
    ...overrides,
  };
}

describe('роль компании на платформе', () => {
  beforeEach(() => {
    vi.mocked(accountsApi.getCompanyTypes).mockReset().mockResolvedValue(TYPES);
    vi.mocked(accountsApi.getRoleApplications).mockReset().mockResolvedValue([]);
    vi.mocked(accountsApi.createRoleApplication).mockReset().mockResolvedValue(makeApplication({ id: 1 }) as never);
    // Компания-покупатель: продавцом ещё не является.
    useUserStore.setState({
      company: {
        ...useUserStore.getState().company,
        id: 10,
        statusEntries: [{ status: 'BUYER', verification: 'verified' }],
      },
    });
  });

  it('покупателю предлагает запросить роль, которой у него нет', async () => {
    renderWithProviders(<CompanyRoleSection />);

    // Ждём именно форму: до прихода справочника ролей секция не должна ничего утверждать.
    expect(await screen.findByRole('button', { name: /Подать заявку/ })).toBeInTheDocument();
    expect(screen.getAllByText('Покупатель')[0]).toBeInTheDocument();
  });

  it('отправляет заявку по выбранной роли', async () => {
    renderWithProviders(<CompanyRoleSection />);

    fireEvent.click(await screen.findByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: 'Поставщик' }));
    fireEvent.click(screen.getByRole('button', { name: /Подать заявку/ }));

    await waitFor(() =>
      expect(accountsApi.createRoleApplication).toHaveBeenCalledWith({ company: 10, requested_type: 2 }),
    );
  });

  it('поданная заявка видна заявителю — он понимает, кого ждёт', async () => {
    vi.mocked(accountsApi.getRoleApplications).mockResolvedValue([makeApplication({ id: 1 })]);
    renderWithProviders(<CompanyRoleSection />);

    expect(await screen.findByText(/на рассмотрении/i)).toBeInTheDocument();
    expect(screen.getByText(/Оператор платформы рассмотрит/)).toBeInTheDocument();
  });

  it('роль, которая у компании уже есть, повторно не предлагается', async () => {
    useUserStore.setState({
      company: {
        ...useUserStore.getState().company,
        id: 10,
        statusEntries: [
          { status: 'BUYER', verification: 'verified' },
          { status: 'SELLER', verification: 'verified' },
        ],
      },
    });
    renderWithProviders(<CompanyRoleSection />);

    fireEvent.click(await screen.findByRole('combobox'));
    expect(screen.queryByRole('option', { name: 'Поставщик' })).not.toBeInTheDocument();
    expect(await screen.findByRole('option', { name: 'Производитель' })).toBeInTheDocument();
  });

  it('отклонённая заявка объясняет причину, а не молчит', async () => {
    vi.mocked(accountsApi.getRoleApplications).mockResolvedValue([
      makeApplication({ id: 1, status: 'REJECTED', review_notes: 'не приложен договор' }),
    ]);
    renderWithProviders(<CompanyRoleSection />);

    expect(await screen.findByText(/не приложен договор/)).toBeInTheDocument();
  });
});


describe('состояние загрузки не выдаётся за ответ', () => {
  it('пока справочник ролей не приехал, «все роли выданы» не утверждается', async () => {
    // Утверждение о состоянии компании нельзя делать, пока данных о нём нет (класс волны U2).
    vi.mocked(accountsApi.getCompanyTypes).mockReset().mockImplementation(() => new Promise(() => {}));
    vi.mocked(accountsApi.getRoleApplications).mockResolvedValue([]);
    renderWithProviders(<CompanyRoleSection />);

    await waitFor(() => expect(accountsApi.getRoleApplications).toHaveBeenCalled());
    expect(screen.queryByText('Все доступные роли уже выданы')).not.toBeInTheDocument();
  });
});
