import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import { TELEGRAM_BANNER_SNOOZE_KEY, TELEGRAM_BANNER_SNOOZE_MS, telegramStepState } from '@/onboarding/telegramStep';
import { MOCK_TELEGRAM_START, TELEGRAM_LINK_TTL_MS } from '@/mocks/fixtures';
import { setMockTelegram } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { asMiniApp, renderApp, signedIn } from '@/test/render';

/** Привязка Telegram самим контактом (ADR-0023 п. 3, NOTIFY-1): плашка после входа и Профиль → «Уведомления». */

const BANNER = 'Уведомления в Telegram';

async function notificationsCard() {
  const heading = await screen.findByRole('heading', { level: 2, name: 'Уведомления' });
  const card = heading.closest<HTMLElement>('#notifications');
  if (!card) throw new Error('нет карточки #notifications');
  return card;
}

/** Запросы к `/me/telegram*` — метод и путь, по порядку. */
function recordTelegramCalls(): string[] {
  const calls: string[] = [];
  portalServer.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname;
    if (path.includes('/me/telegram')) calls.push(`${request.method} ${path.replace('/api/portal/v1', '')}`);
  });
  return calls;
}

describe('плашка «Подключите Telegram»', () => {
  it('видна в вебе, пока Telegram не привязан; «Подключить» ведёт в Профиль и сразу выпускает ссылку', async () => {
    signedIn();
    const user = userEvent.setup();
    const { container, router } = renderApp('/requests');
    const banner = await screen.findByRole('region', { name: BANNER });
    expect(within(banner).getByText('Подключите Telegram — уведомления мгновенно')).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);

    await user.click(within(banner).getByRole('button', { name: 'Подключить' }));
    expect(router.state.location.pathname).toBe('/profile');
    expect(router.state.location.hash).toBe('#notifications');
    const card = await notificationsCard();
    expect(await within(card).findByRole('img', { name: 'QR-код ссылки на бот' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
  });

  it('«Позже» прячет плашку на 14 дней в этом браузере', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests');
    const banner = await screen.findByRole('region', { name: BANNER });
    await user.click(within(banner).getByRole('button', { name: 'Позже' }));
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
    expect(Number(window.localStorage.getItem(TELEGRAM_BANNER_SNOOZE_KEY))).toBe(Date.now() + TELEGRAM_BANNER_SNOOZE_MS);
  });

  it('не показывается после «Позже» до истечения срока', async () => {
    window.localStorage.setItem(TELEGRAM_BANNER_SNOOZE_KEY, String(Date.now() + 60_000));
    signedIn();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
  });

  it('не показывается, если Telegram уже привязан', async () => {
    setMockTelegram({ linked: true });
    signedIn();
    const calls = recordTelegramCalls();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    await vi.waitFor(() => expect(calls).toContain('GET /me/telegram'));
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
  });

  it('не показывается, если подключить нельзя (контакт не в CRM)', async () => {
    setMockTelegram({ available: false });
    signedIn();
    const calls = recordTelegramCalls();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    await vi.waitFor(() => expect(calls).toContain('GET /me/telegram'));
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
  });

  it('в Telegram Mini App не показывается и статус не запрашивает', async () => {
    asMiniApp();
    const calls = recordTelegramCalls();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();
    expect(calls).toEqual([]);
  });
});

describe('Профиль → «Уведомления»', () => {
  it('«Подключить»: QR и кнопка на бот, срок ссылки; опрос переводит в «подключён»', async () => {
    signedIn();
    const user = userEvent.setup();
    const { container } = renderApp('/profile#notifications');
    const card = await notificationsCard();
    expect(await within(card).findByText('Telegram не подключён')).toBeInTheDocument();
    // Плашки на самом Профиле нет — здесь та же кнопка
    expect(screen.queryByRole('region', { name: BANNER })).not.toBeInTheDocument();

    await user.click(within(card).getByRole('button', { name: 'Подключить Telegram' }));
    expect(await within(card).findByRole('img', { name: 'QR-код ссылки на бот' })).toBeInTheDocument();
    const open = within(card).getByRole('link', { name: 'Открыть Telegram' });
    expect(open).toHaveAttribute('href', `https://t.me/example_bot?start=${MOCK_TELEGRAM_START}`);
    expect(open).toHaveAttribute('target', '_blank');
    expect(within(card).getByText(/Ссылка действует до 12:15/)).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);

    setMockTelegram({ linked: true }); // бот привязал Telegram, проекция пришла в ERP
    expect(await within(card).findByText('Telegram подключён')).toBeInTheDocument();
    expect(within(card).queryByRole('img', { name: 'QR-код ссылки на бот' })).not.toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Отвязать' })).toBeInTheDocument();
  });

  it('ссылка истекла — «Выпустить новую ссылку»', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/profile');
    const card = await notificationsCard();
    await user.click(await within(card).findByRole('button', { name: 'Подключить Telegram' }));
    await within(card).findByRole('img', { name: 'QR-код ссылки на бот' });

    vi.setSystemTime(Date.now() + TELEGRAM_LINK_TTL_MS + 1000);
    expect(await within(card).findByText('Ссылка истекла.')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Выпустить новую ссылку' })).toBeInTheDocument();
    expect(within(card).queryByRole('img', { name: 'QR-код ссылки на бот' })).not.toBeInTheDocument();
  });

  it('в Mini App — кнопка на бот без QR', async () => {
    const webApp = asMiniApp();
    const user = userEvent.setup();
    renderApp('/profile');
    const card = await notificationsCard();
    await user.click(await within(card).findByRole('button', { name: 'Подключить Telegram' }));
    const open = await within(card).findByRole('link', { name: 'Открыть Telegram' });
    expect(within(card).queryByRole('img', { name: 'QR-код ссылки на бот' })).not.toBeInTheDocument();
    await user.click(open);
    expect(webApp.openTelegramLink).toHaveBeenCalledWith(`https://t.me/example_bot?start=${MOCK_TELEGRAM_START}`);
  });

  it('«Отвязать» — подтверждение по месту с «Что произойдёт», затем DELETE и опрос до «не подключён»', async () => {
    setMockTelegram({ linked: true });
    signedIn();
    const user = userEvent.setup();
    const calls = recordTelegramCalls();
    const { container } = renderApp('/profile');
    const card = await notificationsCard();
    await user.click(await within(card).findByRole('button', { name: 'Отвязать' }));

    const confirm = within(card).getByRole('region', { name: 'Отключить Telegram?' });
    expect(within(confirm).getByRole('note')).toHaveTextContent('Вход в кабинет из Telegram закроется');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
    expect(calls).not.toContain('DELETE /me/telegram');

    await user.click(within(confirm).getByRole('button', { name: 'Отключить Telegram' }));
    expect(await within(card).findByText('Telegram не подключён')).toBeInTheDocument();
    expect(calls).toContain('DELETE /me/telegram');
  });

  it('«Отмена» в подтверждении ничего не отправляет', async () => {
    setMockTelegram({ linked: true });
    signedIn();
    const user = userEvent.setup();
    const calls = recordTelegramCalls();
    renderApp('/profile');
    const card = await notificationsCard();
    await user.click(await within(card).findByRole('button', { name: 'Отвязать' }));
    await user.click(within(card).getByRole('button', { name: 'Отмена' }));
    expect(within(card).getByRole('button', { name: 'Отвязать' })).toBeInTheDocument();
    expect(calls).not.toContain('DELETE /me/telegram');
  });

  it('контакт не в CRM — подсказка написать менеджеру, кнопки нет', async () => {
    setMockTelegram({ available: false });
    signedIn();
    renderApp('/profile');
    const card = await notificationsCard();
    expect(await within(card).findByText(/после того, как менеджер добавит вас в систему/)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Подключить Telegram' })).not.toBeInTheDocument();
  });

  it('ошибка выпуска ссылки — текст по коду контракта', async () => {
    portalServer.use(
      http.post('*/api/portal/v1/me/telegram-link', () =>
        HttpResponse.json({ detail: 'TELEGRAM_LINK_UNAVAILABLE' }, { status: 503 }),
      ),
    );
    signedIn();
    const user = userEvent.setup();
    renderApp('/profile');
    const card = await notificationsCard();
    await user.click(await within(card).findByRole('button', { name: 'Подключить Telegram' }));
    expect(await screen.findByText('Подключение Telegram сейчас недоступно. Попробуйте позже.')).toBeInTheDocument();
    expect(within(card).queryByRole('img', { name: 'QR-код ссылки на бот' })).not.toBeInTheDocument();
  });
});

describe('проверочное сообщение в Telegram', () => {
  it('только при привязанном Telegram; POST уходит, ответ — «проверьте Telegram»', async () => {
    setMockTelegram({ linked: true });
    signedIn();
    const user = userEvent.setup();
    const calls = recordTelegramCalls();
    const { container } = renderApp('/profile');
    const card = await notificationsCard();
    expect(await within(card).findByText('Telegram привязан')).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Отправить проверочное сообщение' }));
    expect(await screen.findByText('Сообщение отправлено — проверьте Telegram')).toBeInTheDocument();
    expect(calls).toContain('POST /me/telegram/test');
    expect((await axe(container)).violations).toEqual([]);
  });

  it('не привязан — кнопки нет', async () => {
    signedIn();
    renderApp('/profile');
    const card = await notificationsCard();
    await within(card).findByText('Telegram не подключён');
    expect(within(card).queryByRole('button', { name: 'Отправить проверочное сообщение' })).not.toBeInTheDocument();
  });

  it('чаще раза в минуту — «через N с», кнопка недоступна до истечения', async () => {
    setMockTelegram({ linked: true, lastTestAt: Date.now() - 20_000 });
    signedIn();
    const user = userEvent.setup();
    renderApp('/profile');
    const card = await notificationsCard();
    const button = await within(card).findByRole('button', { name: 'Отправить проверочное сообщение' });
    await user.click(button);
    expect(await within(card).findByText('Можно повторить через 40 с')).toBeInTheDocument();
    expect(button).toBeDisabled();

    vi.setSystemTime(Date.now() + 41_000);
    await vi.waitFor(() => expect(button).toBeEnabled(), { timeout: 3000 });
    expect(within(card).queryByText(/Можно повторить через/)).not.toBeInTheDocument();
  });

  it('409 TELEGRAM_NOT_LINKED — статус перечитывается', async () => {
    setMockTelegram({ linked: true });
    signedIn();
    const user = userEvent.setup();
    renderApp('/profile');
    const card = await notificationsCard();
    const button = await within(card).findByRole('button', { name: 'Отправить проверочное сообщение' });
    setMockTelegram({ linked: false }); // Telegram отвязали в другом окне — проекция уже пришла
    await user.click(button);
    expect(await screen.findByText('Telegram не привязан. Подключите его ещё раз.')).toBeInTheDocument();
    expect(await within(card).findByText('Telegram не подключён')).toBeInTheDocument();
  });
});

describe('шаг «Подключить Telegram» (логика без вида)', () => {
  const status = (linked: boolean, available = true) => ({ linked, available });

  it.each([
    ['web', false, status(false), 'todo'],
    ['web', false, status(true), 'done'],
    ['web', true, status(true), 'done'],
    ['web', true, status(false), 'snoozed'],
    ['web', true, undefined, 'snoozed'],
    ['web', false, undefined, 'loading'],
    ['web', false, status(false, false), 'hidden'],
    ['miniapp', false, status(false), 'hidden'],
  ] as const)('%s, «позже»=%s, статус %j → %s', (mode, snoozed, st, expected) => {
    expect(telegramStepState({ mode, snoozed, status: st })).toBe(expected);
  });
});

describe('ссылка из письма на Профиль → «Уведомления» без сессии', () => {
  it('после входа возвращает на /profile#notifications, один раз', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/profile#notifications');
    await screen.findByRole('heading', { level: 1, name: 'Вход в кабинет' });

    await user.type(screen.getByLabelText('E-mail'), 'a.karimov@toshlog.example');
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    const form = await screen.findByRole('form', { name: 'Вход по коду из письма' });
    await user.type(within(form).getByLabelText('Код из письма'), '429173');
    await user.click(within(form).getByRole('button', { name: 'Войти' }));

    await notificationsCard();
    expect(router.state.location.pathname).toBe('/profile');
    expect(router.state.location.hash).toBe('#notifications');

    await router.navigate('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
  });
});
