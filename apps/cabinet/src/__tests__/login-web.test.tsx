import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';

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

  it('ссылка из письма: /auth/magic/:token → сессия → кабинет', async () => {
    const { router } = renderApp('/auth/magic/demo-token');
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
  });

  it('просроченная ссылка (410) — «Ссылка не действует» и путь к новой', async () => {
    renderApp('/auth/magic/expired');
    expect(await screen.findByRole('heading', { level: 1, name: 'Ссылка не действует' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Запросить новую ссылку' })).toHaveAttribute('href', '/login');
  });

  it('«Я новый клиент»: заглушка формы и «Написать в Telegram» с меткой web', async () => {
    renderApp('/new-client');
    expect(await screen.findByRole('heading', { level: 1, name: 'Я новый клиент' })).toBeInTheDocument();
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
