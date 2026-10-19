import { screen, waitFor } from '@testing-library/react';
import { axe } from 'vitest-axe';

import { applyTelegramTheme } from '@/telegram/theme';
import { asMiniApp, renderApp } from '@/test/render';
import { portalServer } from '@/mocks/server';

describe('Mini App', () => {
  it('входит сам по initData — без страницы входа и без шапки сайта', async () => {
    const webApp = asMiniApp();
    const bodies: unknown[] = [];
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/auth/telegram')) bodies.push(await request.clone().json());
    });
    const { router } = renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
    expect(bodies).toEqual([{ init_data: webApp.initData }]);
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
    expect(screen.queryByText('Вход в кабинет')).not.toBeInTheDocument();
    portalServer.events.removeAllListeners();
  });

  it('страницы входа в Mini App нет: /login ведёт в кабинет', async () => {
    asMiniApp();
    const { router } = renderApp('/login');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(router.state.location.pathname).toBe('/requests');
  });

  it('start_param=deal_<id> открывает сделку, на вложенном экране — «Назад» Telegram', async () => {
    const webApp = asMiniApp({ startParam: 'deal_42' });
    const { router } = renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Сделка № D-42' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/deals/42');
    await waitFor(() => expect(webApp.BackButton?.show).toHaveBeenCalled());
  });

  it('неверный initData (401) — экран «Не удалось войти» с повтором', async () => {
    asMiniApp({ initData: 'user=1&hash=bad' });
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Не удалось войти' })).toBeInTheDocument();
    expect(screen.getByText(/Telegram не подтвердил вход/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Попробовать снова' })).toBeInTheDocument();
  });

  it('тема Telegram ложится на переменные shadcn, тёмная схема включает .dark', () => {
    const webApp = asMiniApp({
      colorScheme: 'dark',
      themeParams: { bg_color: '#17212b', text_color: '#f5f5f5', button_color: '#5288c1', button_text_color: '#ffffff' },
    });
    applyTelegramTheme(webApp);
    const style = document.documentElement.style;
    expect(style.getPropertyValue('--background')).toBe('#17212b');
    expect(style.getPropertyValue('--foreground')).toBe('#f5f5f5');
    expect(style.getPropertyValue('--primary')).toBe('#5288c1');
    expect(style.getPropertyValue('--primary-foreground')).toBe('#ffffff');
    expect(document.documentElement).toHaveClass('dark');
  });

  it('axe: оболочка Mini App без нарушений', async () => {
    asMiniApp();
    const { container } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect((await axe(container)).violations).toEqual([]);
  });
});
