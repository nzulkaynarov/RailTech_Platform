import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LoginPage } from '@/components/Auth/LoginPage';
import { renderWithProviders } from '@/test/renderWithProviders';

const login = vi.hoisted(() => vi.fn());

vi.mock('@/store/authStore', () => ({
  useAuthStore: Object.assign(() => ({ login, isLoading: false }), { getState: () => ({}) }),
}));

/**
 * Пароль верен, но участник компании-клиента — не сотрудник (FIX-13): сервер отвечает 403 `STAFF_ONLY`,
 * экран входа говорит, что клиенты работают в личном кабинете, а не печатает сырой код.
 */
describe('LoginPage', () => {
  it('показывает понятное сообщение на STAFF_ONLY', async () => {
    login.mockRejectedValueOnce(new Error('STAFF_ONLY'));
    renderWithProviders(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText('user@company.com'), 'client@example.com');
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'secret-pass');
    await userEvent.click(screen.getByRole('button', { name: 'Войти в кабинет' }));

    await waitFor(() =>
      expect(screen.getByText(/Вход в ERP доступен только сотрудникам/)).toBeInTheDocument(),
    );
    expect(screen.queryByText('STAFF_ONLY')).not.toBeInTheDocument();
  });
});
