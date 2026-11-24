import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { setMockLegal } from '@/mocks/handlers';
import { LEGAL_PRIVACY_ID, LEGAL_TERMS_ID } from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations } from '@/test/screens';

/**
 * ДВ-5 · оферта и политика Кабинета: без принятия действующей редакции кабинет не открывается — ни разделы, ни ссылки на
 * документы, ни вход из Telegram; принятие записывается на сервере (редакции и язык), повторно — только при новой редакции.
 */
const gateTitle = () => screen.findByRole('heading', { level: 1, name: 'Условия работы в кабинете' });

describe('оферта и политика Кабинета (ДВ-5)', () => {
  it('пока ничего не опубликовано, кабинет открыт как раньше', async () => {
    signedIn();
    renderApp('/requests');
    expect(await screen.findByRole('heading', { level: 1, name: 'Заявки' })).toBeInTheDocument();
    expect(screen.queryByText('Условия работы в кабинете')).not.toBeInTheDocument();
  });

  it('опубликована и не принята: вместо раздела — экран принятия, адрес прежний, данные не запрашиваются', async () => {
    signedIn();
    setMockLegal({ published: true, accepted: false });
    const seen: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void seen.push(new URL(request.url).pathname));
    const { router } = renderApp('/quotes/57');

    await gateTitle();
    expect(router.state.location.pathname).toBe('/quotes/57');
    expect(screen.queryByRole('navigation', { name: 'Разделы кабинета' })).not.toBeInTheDocument();
    expect(seen.some((path) => /\/(quotes|requests|company)/.test(path))).toBe(false);
    expect(screen.getByRole('button', { name: 'Принимаю' })).toBeEnabled();
    await expectNoAxeViolations();
  });

  it('оба документа читаются, язык переключается; «Принимаю» отправляет те редакции и язык, которые видел контакт', async () => {
    signedIn();
    setMockLegal({ published: true, accepted: false });
    const user = userEvent.setup();
    let sent: unknown;
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/legal/accept')) sent = await request.clone().json();
    });
    const { router } = renderApp('/quotes/57');
    await gateTitle();

    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getByRole('heading', { name: 'Условия использования Кабинета (оферта)' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Политика персональных данных' }));
    expect(within(screen.getByRole('tabpanel')).getByRole('heading', { name: /Политика обработки персональных данных/ })).toBeInTheDocument();
    // список «— …» выводится списком
    expect(within(screen.getByRole('tabpanel')).getAllByRole('listitem').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(await screen.findByRole('button', { name: 'I accept' })).toBeInTheDocument();
    expect(within(screen.getByRole('tabpanel')).getByRole('heading', { name: 'Personal data processing policy for the Cabinet' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'I accept' }));
    await waitFor(() => expect(screen.queryByText('Terms for using the account')).not.toBeInTheDocument());
    expect(sent).toEqual({ edition_ids: [LEGAL_TERMS_ID, LEGAL_PRIVACY_ID], language: 'en' });
    // после принятия человек там, куда шёл
    expect(router.state.location.pathname).toBe('/quotes/57');
    expect((await screen.findAllByRole('navigation')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'I accept' })).not.toBeInTheDocument();
  });

  it('принятый контакт кабинет открывает без экрана; новая редакция — экран снова', async () => {
    signedIn();
    setMockLegal({ published: true, accepted: true });
    const first = renderApp('/requests');
    expect(await first.findByRole('heading', { level: 1, name: 'Заявки' })).toBeInTheDocument();
    first.unmount();

    setMockLegal({ published: true, accepted: false }); // вышла новая редакция
    renderApp('/requests');
    await gateTitle();
  });

  it('сервер закрыл кабинет посреди сессии (403 LEGAL_ACCEPTANCE_REQUIRED) — открывается экран принятия', async () => {
    signedIn();
    const { queryClient } = renderApp('/requests');
    expect(await screen.findByRole('heading', { level: 1, name: 'Заявки' })).toBeInTheDocument();

    // Пока контакт работал, вышла новая редакция: следующий запрос раздела получает 403, `/me` перечитывается
    setMockLegal({ published: true, accepted: false });
    await act(() => queryClient.refetchQueries({ queryKey: ['requests'] }));

    await gateTitle();
  });

  it('отказ — выход с объяснением на экране входа; сессия закрыта', async () => {
    signedIn();
    setMockLegal({ published: true, accepted: false });
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await gateTitle();

    await user.click(screen.getByRole('button', { name: 'Не принимаю' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(await screen.findByText(/Вы не приняли условия и политику/)).toBeInTheDocument();
  });

  it('в Mini App отказ показывает объяснение, кабинет остаётся закрытым', async () => {
    const { asMiniApp } = await import('@/test/render');
    asMiniApp();
    setMockLegal({ published: true, accepted: false });
    const user = userEvent.setup();
    renderApp('/');
    await gateTitle();

    await user.click(screen.getByRole('button', { name: 'Не принимаю' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Без принятия кабинет не открыть' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Вернуться к тексту' }));
    await gateTitle();
    delete (window as unknown as { Telegram?: unknown }).Telegram;
  });

  it('ссылка на политику — на экране входа, пока политика опубликована; ведёт на публичный текст', async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp('/login');
    expect(await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Политика обработки персональных данных' })).not.toBeInTheDocument();
    unmount();

    setMockLegal({ published: true, accepted: false });
    const { router } = renderApp('/login');
    const link = await screen.findByRole('link', { name: 'Политика обработки персональных данных' });
    expect(link).toHaveAttribute('href', '/privacy');
    await user.click(link);
    expect(await screen.findByRole('heading', { level: 1, name: 'Политика обработки персональных данных в Кабинете' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/privacy');
    await expectNoAxeViolations();
  });

  it('новая редакция вышла, пока контакт читал: принять старое нельзя, экран перечитывает действующие', async () => {
    signedIn();
    setMockLegal({ published: true, accepted: false });
    portalServer.use(http.post('*/api/portal/v1/legal/accept', () => HttpResponse.json({ detail: 'LEGAL_EDITION_CHANGED' }, { status: 409 })));
    const user = userEvent.setup();
    renderApp('/requests');
    await gateTitle();

    await user.click(screen.getByRole('button', { name: 'Принимаю' }));

    expect(await screen.findByText('Вышла новая редакция — текст обновлён. Прочитайте и примите её.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Принимаю' })).toBeEnabled();
  });
});
