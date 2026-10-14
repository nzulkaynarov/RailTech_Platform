import { render } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';

import { App } from '@/app/App';
import { createQueryClient } from '@/app/queryClient';
import { routes } from '@/app/routes';
import { setMockSession } from '@/mocks/handlers';
import { initialPath } from '@/telegram/start-param';
import { getStartParam, isMiniApp, type TelegramWebApp } from '@/telegram/webapp';

/** Приложение целиком на memory-router: маршруты, guards и сессия — настоящие, HTTP — мок. */
export function renderApp(path = '/') {
  // Как main.tsx: в Mini App deep-link `start_param` разрешается до создания маршрутизатора.
  const start = isMiniApp() ? initialPath(path, getStartParam()) : path;
  const router = createMemoryRouter(routes, { initialEntries: [start] });
  const queryClient = createQueryClient();
  const view = render(<App router={router} queryClient={queryClient} />);
  return { ...view, router, queryClient };
}

/** Сессия портала «уже есть» (cookie) — как после входа по magic-link. */
export function signedIn(role: 'actor' | 'viewer' = 'actor') {
  setMockSession({ role, auth_method: 'magic_link' });
}

/** Открыть как Mini App: SDK Telegram с подписанным `initData`. */
export function asMiniApp(overrides: Partial<TelegramWebApp> & { startParam?: string } = {}) {
  const { startParam, ...rest } = overrides;
  const backButton = { isVisible: false, show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() };
  const webApp: TelegramWebApp = {
    initData: 'query_id=AAE&user=%7B%22id%22%3A42%7D&auth_date=1760400000&hash=signed',
    initDataUnsafe: { start_param: startParam, user: { id: 42, language_code: 'ru' } },
    colorScheme: 'light',
    themeParams: {},
    BackButton: backButton,
    ready: vi.fn(),
    expand: vi.fn(),
    openTelegramLink: vi.fn(),
    onEvent: vi.fn(),
    offEvent: vi.fn(),
    ...rest,
  };
  window.Telegram = { WebApp: webApp };
  return webApp;
}
