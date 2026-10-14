import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LANGUAGE_STORAGE_KEY } from '@/i18n/locales';
import { renderApp, signedIn } from '@/test/render';

describe('смена языка', () => {
  it('в профиле: uz и en переключают интерфейс, выбор запоминается и меняет <html lang>', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/profile');
    await screen.findByRole('heading', { level: 1, name: 'Профиль' });

    await user.click(screen.getByRole('button', { name: 'Oʻzbekcha' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Profil' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Asosiy boʻlimlar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Oʻzbekcha' })).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('uz');
    expect(document.documentElement.lang).toBe('uz');

    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Profile' })).toBeInTheDocument();
  });

  it('на странице входа переключатель доступен до входа', async () => {
    const user = userEvent.setup();
    renderApp('/login');
    await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' });
    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in to the cabinet' })).toBeInTheDocument();
  });

  it('язык контакта из /me применяется, если человек не выбирал язык сам', async () => {
    signedIn('viewer'); // у контакта-наблюдателя в фикстурах язык uz
    renderApp('/requests');
    expect(await screen.findByRole('heading', { level: 1, name: 'Soʻrovlar' })).toBeInTheDocument();
  });
});
