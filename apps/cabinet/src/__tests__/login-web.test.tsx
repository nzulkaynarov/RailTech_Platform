import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import i18n from '@/i18n';
import indexHtml from '../../index.html?raw';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, requestLog } from '@/test/screens';

afterEach(() => {
  delete (window as unknown as { Telegram?: unknown }).Telegram;
  delete (window as unknown as { __cabinetMagicToken?: string }).__cabinetMagicToken;
});

describe('вход с веба', () => {
  it('без сессии кабинет ведёт на страницу входа с двумя путями', async () => {
    const { router } = renderApp('/quotes');

    expect(await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
    expect(screen.getByRole('button', { name: 'Войти' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Я новый клиент' })).toHaveAttribute('href', '/new-client');
  });

  it('«Войти»: magic-link → «Письмо отправлено»', async () => {
    const user = userEvent.setup();
    let sentBody: unknown;
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/auth/magic-link')) sentBody = await request.clone().json();
    });
    const { router } = renderApp('/login');

    await user.type(await screen.findByLabelText('E-mail'), 'a.karimov@toshlog.uz');
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Письмо отправлено' })).toBeInTheDocument();
    expect(screen.getByText(/a\.karimov@toshlog\.uz/)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login/sent');
    expect(sentBody).toEqual({ email: 'a.karimov@toshlog.uz' });
    portalServer.events.removeAllListeners();
  });

  it('ошибка API показывается текстом из словаря по коду detail', async () => {
    portalServer.use(
      http.post('*/api/portal/v1/auth/magic-link', () => HttpResponse.json({ detail: 'VALIDATION_ERROR' }, { status: 422 })),
    );
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(await screen.findByLabelText('E-mail'), 'x@y.uz');
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    expect(await screen.findByText('Проверьте заполненные поля.')).toBeInTheDocument();
  });

  it('ссылка из письма: /auth/magic#token=… → POST /auth/magic {token} → сессия → кабинет', async () => {
    const log = requestLog();
    const body = captureBody('/auth/magic');
    const { router } = renderApp('/auth/magic#token=demo-token');
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
    expect(body.current).toEqual({ token: 'demo-token' });
    // Токен не в пути и не в GET: старый обмен `GET /auth/magic/{token}` Cabinet не использует.
    expect(log).toContain('POST /auth/magic');
    expect(log.filter((entry) => entry.startsWith('GET /auth/magic'))).toEqual([]);
  });

  it('POST /auth/magic по контракту FIX-15: Idempotency-Key, JSON, cookie сессии, в теле ровно {token}', async () => {
    let seen: { key: string | null; type: string | null; credentials: string; body: unknown } | null = null;
    portalServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/auth/magic') && request.method === 'POST') {
        seen = {
          key: request.headers.get('Idempotency-Key'),
          type: request.headers.get('Content-Type'),
          credentials: request.credentials,
          body: await request.clone().json(),
        };
      }
    });
    renderApp('/auth/magic#token=demo-token');
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(seen).toEqual({
      key: expect.stringMatching(/^[\w-]{8,}$/),
      type: 'application/json',
      credentials: 'include',
      body: { token: 'demo-token' },
    });
  });

  it('422 VALIDATION_ERROR (обрезанная или битая ссылка) — «Ссылка не действует» и путь запросить новую, а не «проверьте поля»', async () => {
    portalServer.use(http.post('*/api/portal/v1/auth/magic', () => HttpResponse.json({ detail: 'VALIDATION_ERROR' }, { status: 422 })));
    renderApp('/auth/magic#token=bad');
    expect(await screen.findByRole('heading', { level: 1, name: 'Ссылка не действует' })).toBeInTheDocument();
    expect(screen.queryByText('Проверьте заполненные поля.')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Запросить новую ссылку' })).toHaveAttribute('href', '/login');
  });

  it('тексты ошибок входа есть на uz и en', async () => {
    window.localStorage.setItem('cabinet.language', 'uz');
    await i18n.changeLanguage('uz');
    const uz = renderApp('/auth/magic#token=forbidden');
    expect(await screen.findByText('Kirish yopilgan, menejerga murojaat qiling.')).toBeInTheDocument();
    uz.unmount();
    await i18n.changeLanguage('en');
    renderApp('/auth/magic#token=throttled');
    expect(await screen.findByText('Too many requests, try again in an hour.')).toBeInTheDocument();
  });

  describe('токен входа не остаётся в SDK Telegram', () => {
    const STORE_KEY = '__telegram__initParams';
    const seed = () => {
      // Telegram SDK при загрузке разбирает весь location.hash в sessionStorage и в память WebView.initParams.
      window.sessionStorage.setItem(STORE_KEY, JSON.stringify({ token: 'secret-token-1', tgWebAppPlatform: 'web' }));
      (window as unknown as { Telegram: unknown }).Telegram = { WebView: { initParams: { token: 'secret-token-1', tgWebAppPlatform: 'web' } } };
    };
    const leaks = () => {
      const stored = window.sessionStorage.getItem(STORE_KEY) ?? '';
      const memory = JSON.stringify((window as unknown as { Telegram?: unknown }).Telegram ?? {});
      return { stored, memory, found: /secret-token-1|throttled|demo-token/.test(stored + memory) };
    };

    it('после успешного входа токена нет ни в sessionStorage, ни в window.Telegram; прочие параметры SDK целы', async () => {
      seed();
      renderApp('/auth/magic#token=demo-token');
      expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
      expect(leaks().found).toBe(false);
      expect(JSON.parse(window.sessionStorage.getItem(STORE_KEY) ?? '{}')).toEqual({ tgWebAppPlatform: 'web' });
      expect((window as unknown as { Telegram: { WebView: { initParams: object } } }).Telegram.WebView.initParams).toEqual({ tgWebAppPlatform: 'web' });
    });

    it('токен снят ещё до первого запроса и после неудачного обмена (429)', async () => {
      seed();
      let atRequest: ReturnType<typeof leaks> | null = null;
      portalServer.events.on('request:start', ({ request }) => {
        if (new URL(request.url).pathname.endsWith('/auth/magic') && request.method === 'POST') atRequest = leaks();
      });
      renderApp('/auth/magic#token=throttled');
      expect(await screen.findByRole('heading', { level: 1, name: 'Не удалось войти' })).toBeInTheDocument();
      expect(atRequest).not.toBeNull();
      expect(atRequest!.found).toBe(false);
      expect(leaks().found).toBe(false);
    });

    it('токен, пойманный до запуска SPA (index.html убирает фрагмент до SDK), обменивается и не остаётся в window', async () => {
      (window as unknown as { __cabinetMagicToken?: string }).__cabinetMagicToken = 'demo-token';
      const body = captureBody('/auth/magic');
      renderApp('/auth/magic');
      expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
      expect(body.current).toEqual({ token: 'demo-token' });
      expect((window as unknown as { __cabinetMagicToken?: string }).__cabinetMagicToken).toBeUndefined();
    });

    it('index.html: сохраняющий токен скрипт стоит раньше Telegram SDK и сразу убирает фрагмент', () => {
      const sdk = indexHtml.indexOf('telegram-web-app.js');
      const guard = indexHtml.indexOf('__cabinetMagicToken');
      expect(guard).toBeGreaterThan(-1);
      expect(guard).toBeLessThan(sdk);
      expect(indexHtml).toMatch(/history\.replaceState\([^)]*location\.pathname \+ location\.search/);
    });
  });

  it('старая ссылка с токеном в пути только перенаправляет на фрагмент и обменивается через POST', async () => {
    const log = requestLog();
    const body = captureBody('/auth/magic');
    const { router } = renderApp('/auth/magic/legacy-token');
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
    expect(body.current).toEqual({ token: 'legacy-token' });
    expect(log.filter((entry) => entry.includes('legacy-token'))).toEqual([]);
  });

  it('просроченная ссылка (410) — «Ссылка не действует», фрагмент убран из адреса, путь к новой', async () => {
    const { router } = renderApp('/auth/magic#token=expired');
    expect(await screen.findByRole('heading', { level: 1, name: 'Ссылка не действует' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Запросить новую ссылку' })).toHaveAttribute('href', '/login');
    expect(router.state.location.hash).toBe('');
  });

  it('ссылка без токена — «Ссылка не действует», запросов нет', async () => {
    const log = requestLog();
    renderApp('/auth/magic');
    expect(await screen.findByRole('heading', { level: 1, name: 'Ссылка не действует' })).toBeInTheDocument();
    expect(log.filter((entry) => entry.startsWith('POST /auth/magic'))).toEqual([]);
  });

  it('403 FORBIDDEN (компания в архиве) — «Доступ закрыт, обратитесь к менеджеру»', async () => {
    renderApp('/auth/magic#token=forbidden');
    expect(await screen.findByRole('heading', { level: 1, name: 'Доступ закрыт' })).toBeInTheDocument();
    expect(screen.getByText('Доступ закрыт, обратитесь к менеджеру.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Запросить новую ссылку' })).not.toBeInTheDocument();
  });

  it('429 на обмене токена — «Слишком много запросов, попробуйте через час»', async () => {
    renderApp('/auth/magic#token=throttled');
    expect(await screen.findByRole('heading', { level: 1, name: 'Не удалось войти' })).toBeInTheDocument();
    expect(screen.getByText('Слишком много запросов, попробуйте через час.')).toBeInTheDocument();
  });

  it.each([
    [429, 'TOO_MANY_REQUESTS', 'Слишком много запросов, попробуйте через час.'],
    [403, 'FORBIDDEN', 'Доступ закрыт, обратитесь к менеджеру.'],
  ])('«Войти»: %i %s — понятный текст под полем', async (status, code, text) => {
    portalServer.use(http.post('*/api/portal/v1/auth/magic-link', () => HttpResponse.json({ detail: code }, { status })));
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(await screen.findByLabelText('E-mail'), 'x@y.uz');
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it('«Я новый клиент»: форма запроса и рядом «Написать в Telegram» с меткой web (форма — new-client.test)', async () => {
    renderApp('/new-client');
    expect(await screen.findByRole('heading', { level: 1, name: 'Я новый клиент' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отправить запрос' })).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Написать в Telegram' });
    expect(link.getAttribute('href')).toMatch(/^https:\/\/t\.me\/[^/?]+\?start=web$/);
  });

  it('выход: POST /auth/logout → страница входа', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/profile');
    await user.click(await screen.findByRole('button', { name: 'Выйти из кабинета' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' })).toBeInTheDocument();
  });

  it('axe: страница входа и «Я новый клиент» без нарушений', async () => {
    const { container, router } = renderApp('/login');
    await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' });
    expect((await axe(container)).violations).toEqual([]);

    await router.navigate('/new-client');
    await screen.findByRole('heading', { level: 1, name: 'Я новый клиент' });
    expect((await axe(container)).violations).toEqual([]);
  });
});
