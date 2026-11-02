import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';

import { portalServer } from '@/mocks/server';
import { codeDigits, secondsLeft } from '@/pages/auth/loginCode';
import { renderApp } from '@/test/render';
import { captureBody } from '@/test/screens';

/**
 * B-MAIL-1: вход по коду из письма. Письмо может идти несколько минут, ссылка — открыться на другом устройстве;
 * код вводится на экране «Мы отправили письмо» или «Вход по коду» (приглашение), «Отправить ещё раз» — через 60 с.
 */

async function sendLetter(user: ReturnType<typeof userEvent.setup>, address = 'a.karimov@toshlog.example') {
  renderApp('/login');
  await user.type(await screen.findByLabelText('E-mail'), address);
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  return screen.findByRole('heading', { level: 1, name: 'Мы отправили письмо' });
}

function codeForm() {
  return screen.getByRole('form', { name: 'Вход по коду из письма' });
}

describe('вход по коду из письма', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('код из письма: POST /auth/code {email, code} → сессия → кабинет', async () => {
    const user = userEvent.setup();
    const body = captureBody('/auth/code');
    await sendLetter(user);

    const field = within(codeForm()).getByLabelText('Код из письма');
    expect(field).toHaveAttribute('autocomplete', 'one-time-code');
    expect(field).toHaveAttribute('inputmode', 'numeric');
    await user.type(field, '42 91 73');
    expect(field).toHaveValue('429173');
    await user.click(within(codeForm()).getByRole('button', { name: 'Войти' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(body.current).toEqual({ email: 'a.karimov@toshlog.example', code: '429173' });
  });

  it('неверный код — понятный текст, поле остаётся', async () => {
    const user = userEvent.setup();
    await sendLetter(user);
    await user.type(within(codeForm()).getByLabelText('Код из письма'), '000000');
    await user.click(within(codeForm()).getByRole('button', { name: 'Войти' }));

    expect(
      await within(codeForm()).findByText('Код неверный или устарел. Проверьте письмо или отправьте новый код.'),
    ).toBeInTheDocument();
    expect(within(codeForm()).getByLabelText('Код из письма')).toHaveAttribute('aria-invalid', 'true');
  });

  it('пять неверных подряд — блок со своим текстом, не общий «лимит входа»', async () => {
    const user = userEvent.setup();
    await sendLetter(user);
    await user.type(within(codeForm()).getByLabelText('Код из письма'), '111111');
    await user.click(within(codeForm()).getByRole('button', { name: 'Войти' }));

    expect(
      await within(codeForm()).findByText(
        'Пять неверных кодов подряд — этот код больше не действует. Нажмите «Отправить ещё раз», чтобы получить новый.',
      ),
    ).toBeInTheDocument();
  });

  it('«Отправить ещё раз» доступна через 60 с, отправляет новое письмо и снова ждёт 60 с', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const requests: unknown[] = [];
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/auth/magic-link')) requests.push(await request.clone().json());
    });
    await sendLetter(user);

    const waiting = screen.getByRole('button', { name: /Отправить ещё раз через \d+ с/ });
    expect(waiting).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    const ready = screen.getByRole('button', { name: 'Отправить ещё раз' });
    expect(ready).toBeEnabled();
    await user.click(ready);

    expect(
      await screen.findByText('Отправили новое письмо. Код из прежнего больше не действует.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Отправить ещё раз через \d+ с/ })).toBeDisabled();
    expect(requests).toEqual([{ email: 'a.karimov@toshlog.example' }, { email: 'a.karimov@toshlog.example' }]);
    portalServer.events.removeAllListeners();
  });

  it('подсказка о задержке письма и «Спаме», вход через Telegram', async () => {
    const user = userEvent.setup();
    await sendLetter(user);
    expect(screen.getByText('Письмо может идти несколько минут. Проверьте папку «Спам».')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Войти через Telegram' })).toHaveAttribute(
      'href',
      expect.stringMatching(/^https:\/\/t\.me\//),
    );
  });

  it('«Уже есть код из письма?» — вход по коду приглашения без нового письма', async () => {
    const user = userEvent.setup();
    let letters = 0;
    portalServer.use(
      http.post('*/api/portal/v1/auth/magic-link', () => {
        letters += 1;
        return new HttpResponse(null, { status: 200 });
      }),
    );
    const { router } = renderApp('/login');
    await user.type(await screen.findByLabelText('E-mail'), 'n.saidova@toshlog.example');
    await user.click(screen.getByRole('link', { name: 'Уже есть код из письма? Войти по коду' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Вход по коду' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login/code');
    expect(within(codeForm()).getByLabelText('E-mail')).toHaveValue('n.saidova@toshlog.example');
    expect(screen.getByRole('button', { name: 'Отправить ещё раз' })).toBeEnabled();
    await user.type(within(codeForm()).getByLabelText('Код из письма'), '734002');
    await user.click(within(codeForm()).getByRole('button', { name: 'Войти' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(letters).toBe(0);
  });

  it('axe: «Мы отправили письмо» с ошибкой кода без нарушений', async () => {
    const user = userEvent.setup();
    await sendLetter(user);
    await user.type(within(codeForm()).getByLabelText('Код из письма'), '000000');
    await user.click(within(codeForm()).getByRole('button', { name: 'Войти' }));
    await within(codeForm()).findByText(/Код неверный/);
    expect((await axe(document.body)).violations).toEqual([]);
  });

  it('хелперы: только цифры, не больше шести; таймер считает вниз до нуля', () => {
    expect(codeDigits('Код: 12-34 56 7')).toBe('123456');
    expect(secondsLeft(0, 0)).toBe(60);
    expect(secondsLeft(0, 59_001)).toBe(1);
    expect(secondsLeft(0, 60_000)).toBe(0);
  });
});
