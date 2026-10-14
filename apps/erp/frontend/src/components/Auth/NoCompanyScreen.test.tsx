import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NoCompanyScreen } from '@/components/Auth/NoCompanyScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

const logout = vi.hoisted(() => vi.fn(() => Promise.resolve()));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (s: { logout: () => Promise<void> }) => unknown) => selector({ logout }),
}));

/**
 * Учётная запись без компании. Раньше здесь была форма саморегистрации компании; в ERP её нет
 * (M1-ERP-02), поэтому экран не предлагает создать компанию, а говорит, к кому идти, и даёт выйти.
 */
describe('NoCompanyScreen', () => {
  it('объясняет, что компанию привязывает администратор, и не предлагает её создать', () => {
    renderWithProviders(<NoCompanyScreen />);

    expect(screen.getByText('Учётная запись не привязана к компании')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('выход завершает сессию', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, assign });
    renderWithProviders(<NoCompanyScreen />);

    await userEvent.click(screen.getByRole('button', { name: 'Выйти' }));

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    expect(assign).toHaveBeenCalledWith('/');
    vi.unstubAllGlobals();
  });
});
