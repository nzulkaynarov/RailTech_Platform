import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { http, HttpResponse } from 'msw';

import { MOCK_ACCEPT_CODE } from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading, requestLog } from '@/test/screens';

describe('КП', () => {
  it('список: все версии, сумма, срок, «ждут решения»', async () => {
    signedIn();
    renderApp('/quotes');
    await heading('Коммерческие предложения');
    expect(await screen.findByText('2 КП ждут вашего решения')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Коммерческие предложения' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    const first = within(list).getAllByRole('listitem')[0];
    expect(within(first).getByRole('link', { name: 'KP-2026-0042 · версия 2' })).toHaveAttribute('href', '/quotes/301');
    expect(within(first).getByText('48 600 000 UZS')).toBeInTheDocument();
    expect(within(first).getByText('25 окт. 2026 г.')).toBeInTheDocument();
    expect(within(list).getAllByText('Срок истёк')).toHaveLength(1);
    await expectNoAxeViolations();
  });

  it('карточка: разделы, позиции, заметки, обещанные даты, итог', async () => {
    signedIn();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    const lines = screen.getByRole('list', { name: 'Состав предложения' });
    expect(within(lines).getByText('Товары')).toBeInTheDocument();
    expect(within(lines).getByText('Подшипник 6205-2RS')).toBeInTheDocument();
    expect(within(lines).getByText('200 шт')).toBeInTheDocument();
    expect(within(lines).getByText('165 000 UZS')).toBeInTheDocument();
    expect(within(lines).getByText('5 нояб. 2026 г.')).toBeInTheDocument();
    expect(within(lines).getByText('Доставка до склада клиента в Ташкенте включена')).toBeInTheDocument();
    expect(screen.getAllByText('48 600 000 UZS').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('button', { name: 'Скачать: KP-2026-0042' })).toBeInTheDocument();
  });

  it('этапы услуги: КП по этапам с копейками', async () => {
    signedIn();
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    expect(screen.getByText('Этап 1. Обследование площадки и проект')).toBeInTheDocument();
    expect(screen.getAllByText('Этап')).toHaveLength(3);
    expect(screen.getAllByText('18 750 000,50 UZS').length).toBeGreaterThanOrEqual(1);
  });

  it('принять: «Получить код» → канал → неверный код → верный → «договор формируется»', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    const body = captureBody('/quotes/301/accept');
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog', { name: 'Принять КП KP-2026-0042' });

    // Шаг 1: кода ещё нет — поля ввода нет, есть «Получить код»; запроса кода ещё не было.
    expect(within(dialog).queryByLabelText('Код подтверждения')).not.toBeInTheDocument();
    expect(log).not.toContain('POST /quotes/301/request-code');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));

    // Шаг 2: ERP ответил каналом — показываем его и поле ввода.
    expect(await within(dialog).findByText('Код отправлен в Telegram. Действует 15 мин.')).toBeInTheDocument();
    expect(log).toContain('POST /quotes/301/request-code');
    expect(log).not.toContain('POST /quotes/301/accept');

    await user.type(within(dialog).getByLabelText('Код подтверждения'), '12');
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(within(dialog).getByText('Код — не короче 4 символов.')).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText('Код подтверждения'));
    await user.type(within(dialog).getByLabelText('Код подтверждения'), '000000');
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(await within(dialog).findByText(/Код неверен или не запрошен/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Код подтверждения')).toHaveAttribute('aria-invalid', 'true');
    await expectNoAxeViolations();

    await user.clear(within(dialog).getByLabelText('Код подтверждения'));
    await user.type(within(dialog).getByLabelText('Код подтверждения'), ` ${MOCK_ACCEPT_CODE.slice(0, 3)} ${MOCK_ACCEPT_CODE.slice(3)} `);
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));

    expect(await screen.findByText('КП принято')).toBeInTheDocument();
    expect(body.current).toEqual({ code: MOCK_ACCEPT_CODE });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Принято')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
    // Договор ERP создал сам — панель берёт номер из списка договоров.
    expect(await screen.findByText(/Договор D-2026-0042 готов/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'К договорам' })).toHaveAttribute('href', '/contracts');
  });

  it('канал e-mail: показан замаскированный адрес из ответа ERP', async () => {
    signedIn();
    portalServer.use(
      http.post('*/api/portal/v1/quotes/301/request-code', () =>
        HttpResponse.json({ channel: 'email', sent_to: 'a***@toshlog.uz', expires_in: 900 }, { status: 202 }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));
    expect(await within(dialog).findByText('Код отправлен на a***@toshlog.uz. Действует 15 мин.')).toBeInTheDocument();

    // Telegram с маскированным именем — адрес показывается.
    portalServer.use(
      http.post('*/api/portal/v1/quotes/301/request-code', () =>
        HttpResponse.json({ channel: 'telegram', sent_to: '@a***', expires_in: 600 }, { status: 202 }),
      ),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Отправить код ещё раз' }));
    expect(await within(dialog).findByText('Код отправлен в Telegram (@a***). Действует 10 мин.')).toBeInTheDocument();
  });

  it('код можно запросить ещё раз — второй запрос уходит в ERP', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Отправить код ещё раз' }));
    await waitFor(() => expect(log.filter((entry) => entry === 'POST /quotes/301/request-code')).toHaveLength(2));
  });

  it('повторная отправка кода упала (429) — поле кода на месте, уже полученный код вводится и принимается', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));
    expect(await within(dialog).findByLabelText('Код подтверждения')).toBeInTheDocument();

    // Повтор упёрся в общий лимит (портал считает запрос кода и акцепт одним ведром).
    failWith('post', '/quotes/301/request-code', 429, 'TOO_MANY_REQUESTS');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить код ещё раз' }));
    expect(await within(dialog).findByText(/Слишком много запросов/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Код подтверждения')).toBeInTheDocument();
    expect(within(dialog).getByText('Код отправлен в Telegram. Действует 15 мин.')).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Код подтверждения'), MOCK_ACCEPT_CODE);
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(await screen.findByText('КП принято')).toBeInTheDocument();
  });

  it.each([
    ['CONTACT_CHANNEL_REQUIRED', 422, /Нам некуда отправить код/],
    ['QUOTE_EXPIRED', 409, /Срок действия КП истёк/],
    ['QUOTE_FINALIZED', 409, /КП уже принято или отклонено/],
    ['TOO_MANY_REQUESTS', 429, /Слишком много запросов/],
    ['FORBIDDEN', 403, /нет права на это действие/],
    ['NOT_FOUND', 404, /Не найдено/],
  ])('запрос кода: %s (%i) — текст в диалоге, ввода кода нет', async (code, status, text) => {
    signedIn();
    failWith('post', '/quotes/301/request-code', status, code);
    const user = userEvent.setup();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));
    expect(await within(dialog).findByText(text)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText('Код подтверждения')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Получить код' })).toBeEnabled();
  });

  it.each([
    ['QUOTE_FINALIZED', 409, 'КП уже принято или отклонено — обновите страницу.'],
    ['QUOTE_EXPIRED', 409, /Срок действия КП истёк/],
    ['TOO_MANY_REQUESTS', 429, /Слишком много запросов/],
  ])('accept: %s (%i) — сообщение в диалоге', async (code, status, text) => {
    signedIn();
    failWith('post', '/quotes/301/accept', status, code);
    const user = userEvent.setup();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Получить код' }));
    await user.type(await within(dialog).findByLabelText('Код подтверждения'), MOCK_ACCEPT_CODE);
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(await within(dialog).findByText(text)).toBeInTheDocument();
  });

  it('КП в статусе «просмотрено» тоже можно принять', async () => {
    signedIn();
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    expect(screen.getByRole('button', { name: 'Принять' })).toBeInTheDocument();
  });

  it('отклонить: причина обязательна, уходит в ERP', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/quotes/310/reject');
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отклонить КП KP-2026-0057' });
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить КП' }));
    expect(within(dialog).getByText(/Укажите причину/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText('Причина'), 'Дорого');
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить КП' }));
    expect(await screen.findByText('КП отклонено')).toBeInTheDocument();
    expect(screen.getByText('Причина: Дорого')).toBeInTheDocument();
    expect(body.current).toEqual({ reason: 'Дорого' });
  });

  it('истёкшее КП — объяснение вместо кнопок', async () => {
    signedIn();
    renderApp('/quotes/330');
    await heading('КП KP-2026-0033');
    expect(screen.getByText('Срок действия КП истёк')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
  });

  it('can_act=false: принять и отклонить скрыты', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    expect(screen.getByText('Ждёт решения')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Получить код' })).not.toBeInTheDocument();
  });

  it('чужое КП (404) — «не найдено» без подробностей', async () => {
    signedIn();
    renderApp('/quotes/999');
    expect(await heading('Страница не найдена')).toBeInTheDocument();
  });

  it('пусто — пустое состояние', async () => {
    signedIn('actor', 'empty');
    renderApp('/quotes');
    expect(await screen.findByText('КП пока нет')).toBeInTheDocument();
  });

  it('axe: карточка КП', async () => {
    signedIn();
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    await expectNoAxeViolations();
  });
});
