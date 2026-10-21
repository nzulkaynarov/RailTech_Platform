import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NoCompanyGate } from '@/components/Auth/NoCompanyGate';
import { OwnCompanySetupScreen } from '@/components/Auth/OwnCompanySetupScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

const h = vi.hoisted(() => ({
  logout: vi.fn(() => Promise.resolve()),
  initAuth: vi.fn(() => Promise.resolve()),
  getStatus: vi.fn(),
  createOwnCompany: vi.fn(),
}));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (s: { logout: () => Promise<void>; initAuth: () => Promise<void> }) => unknown) =>
    selector({ logout: h.logout, initAuth: h.initAuth }),
}));
vi.mock('@/api/setupApi', () => ({
  setupApi: { getStatus: h.getStatus, createOwnCompany: h.createOwnCompany },
}));

/** FIX-65: мастер своей компании и выбор между ним и экраном сотрудника. */
describe('OwnCompanySetupScreen', () => {
  beforeEach(() => vi.clearAllMocks());

  it('успех: отправляет реквизиты и перечитывает профиль', async () => {
    h.createOwnCompany.mockResolvedValue({ id: 1, name: 'ООО Рейл' });
    renderWithProviders(<OwnCompanySetupScreen />);

    await userEvent.type(screen.getByLabelText(/Название компании/), 'ООО Рейл');
    await userEvent.type(screen.getByLabelText('ИНН'), '123456789');
    await userEvent.click(screen.getByRole('button', { name: 'Создать компанию' }));

    await waitFor(() => expect(h.initAuth).toHaveBeenCalledTimes(1));
    expect(h.createOwnCompany).toHaveBeenCalledWith({
      name: 'ООО Рейл',
      inn: '123456789',
      legal_address: '',
      phone: '',
      email: '',
    });
  });

  it('без названия не отправляет и показывает ошибку у поля', async () => {
    renderWithProviders(<OwnCompanySetupScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'Создать компанию' }));

    expect(await screen.findByText('Укажите название компании.')).toBeInTheDocument();
    expect(h.createOwnCompany).not.toHaveBeenCalled();
  });

  it('422 по ИНН показывается у поля ИНН, форма остаётся', async () => {
    h.createOwnCompany.mockRejectedValue(
      Object.assign(new Error('422'), {
        isAxiosError: true,
        response: { status: 422, data: { inn: ['Некорректный формат ИНН.'] } },
      }),
    );
    renderWithProviders(<OwnCompanySetupScreen />);

    await userEvent.type(screen.getByLabelText(/Название компании/), 'ООО Рейл');
    await userEvent.type(screen.getByLabelText('ИНН'), '12');
    await userEvent.click(screen.getByRole('button', { name: 'Создать компанию' }));

    const error = await screen.findByText('Некорректный формат ИНН.');
    expect(screen.getByLabelText('ИНН')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('ИНН')).toHaveAccessibleDescription(error.textContent ?? '');
    expect(h.initAuth).not.toHaveBeenCalled();
  });
});

describe('NoCompanyGate', () => {
  beforeEach(() => vi.clearAllMocks());

  it('администратор при незавершённой настройке видит мастер, а не тупик', async () => {
    h.getStatus.mockResolvedValue({ setup_required: true, can_setup: true });
    renderWithProviders(<NoCompanyGate />);

    expect(await screen.findByRole('heading', { name: 'Настройка ERP: ваша компания' })).toBeInTheDocument();
  });

  it('сотрудник при незавершённой настройке читает, что администратор ещё не закончил', async () => {
    h.getStatus.mockResolvedValue({ setup_required: true, can_setup: false });
    renderWithProviders(<NoCompanyGate />);

    expect(await screen.findByText(/Администратор ещё не завершил первоначальную настройку ERP/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('настройка сделана, но сотрудник не привязан — прежний текст', async () => {
    h.getStatus.mockResolvedValue({ setup_required: false, can_setup: false });
    renderWithProviders(<NoCompanyGate />);

    expect(await screen.findByText(/Доступ к бэк-офису выдаёт администратор/)).toBeInTheDocument();
  });

  it('статус недоступен — прежний экран, мастер не показывается', async () => {
    h.getStatus.mockRejectedValue(new Error('network'));
    renderWithProviders(<NoCompanyGate />);

    expect(await screen.findByText(/Доступ к бэк-офису выдаёт администратор/)).toBeInTheDocument();
  });
});
