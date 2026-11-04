import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { pushManagerReply } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { POLL_INTERVAL_MS } from '@/lib/messages';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, heading } from '@/test/screens';

/**
 * Чат кабинета (CHAT-1, ADR-0023): лента компании, бейдж непрочитанного из `/me.unread`, опрос только при открытом экране
 * и видимой вкладке, отправка с оптимистичной строкой и повтором тем же ключом, метка документа, текст — только текст.
 */
const page = () => document.querySelector('main') as HTMLElement;
const feed = () => within(page()).getByRole('list', { name: 'Переписка с менеджером' });

let visibility: DocumentVisibilityState = 'visible';
beforeAll(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
});
afterEach(() => {
  visibility = 'visible';
  vi.useRealTimers();
});

function setVisibility(state: DocumentVisibilityState) {
  visibility = state;
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

/** Опросы ленты: `GET /messages?after_id=…` (первая загрузка — без параметра). */
function pollLog(): string[] {
  const log: string[] = [];
  portalServer.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname.endsWith('/messages') && url.searchParams.has('after_id')) {
      log.push(url.searchParams.get('after_id') ?? '');
    }
  });
  return log;
}

describe('«Сообщения»', () => {
  it('бейдж непрочитанного в меню — из /me.unread', async () => {
    signedIn();
    renderApp('/requests');
    await heading('Запросы');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    const link = within(side).getByRole('link', { name: 'Сообщения' });
    expect(link).toHaveAttribute('href', '/messages');
    expect(link).toHaveAccessibleDescription('Непрочитанных сообщений: 1');
    expect(link).toHaveTextContent('Сообщения1'); // бейдж
    // на телефоне раздел в «Ещё» — бейдж на кнопке
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(within(bottom).getByRole('button', { name: 'Ещё' })).toHaveAccessibleDescription(
      'Непрочитанных сообщений: 1',
    );
  });

  it('лента: свои справа «Вы», ответы менеджера с именем, метки документов; открыл — прочитано, бейдж ушёл', async () => {
    signedIn();
    const read = captureBody('/messages/read');
    renderApp('/messages');
    await heading('Сообщения');
    const list = await within(page()).findByRole('list', { name: 'Переписка с менеджером' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('Вы');
    expect(within(items[0]).getByRole('link', { name: 'КП KP-2026-0042' })).toHaveAttribute('href', '/quotes/301');
    expect(items[1]).toHaveTextContent('Илья Смирнов, менеджер');
    expect(items[2]).toHaveTextContent('Dilnoza Yusupova');
    expect(within(items[2]).getByRole('link', { name: 'Счёт S-2026-0124' })).toHaveAttribute('href', '/invoices');

    await waitFor(() => expect(read.current).toEqual({ last_id: 504 }));
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    await waitFor(() => expect(within(side).getByRole('link', { name: 'Сообщения' })).not.toHaveAccessibleDescription());
    expect(within(side).getByRole('link', { name: 'Сообщения' })).toHaveTextContent(/^Сообщения$/);
    await expectNoAxeViolations();
  });

  it('опрос раз в 10 с только при видимой вкладке; ушёл с экрана — опроса нет', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signedIn();
    const polls = pollLog();
    const { router } = renderApp('/messages');
    await heading('Сообщения');
    await within(page()).findByRole('list', { name: 'Переписка с менеджером' });
    expect(polls).toEqual([]);

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(polls).toEqual(['504']));

    setVisibility('hidden');
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3));
    expect(polls).toHaveLength(1);

    pushManagerReply('Ответ, пока вкладка была скрыта');
    setVisibility('visible'); // вернулись — сразу догоняем ленту
    await within(feed()).findByText('Ответ, пока вкладка была скрыта');
    expect(polls).toEqual(['504', '504']);

    await act(() => router.navigate('/requests'));
    await heading('Запросы');
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3));
    expect(polls).toHaveLength(2);
  });

  it('отправка: строка «Отправляется…» сразу, ключ повтора по контракту, метка документа в теле', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/messages');
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    portalServer.use(
      http.post('*/api/portal/v1/messages', async () => {
        await gate;
        return undefined; // дальше — обработчик мока
      }),
    );
    renderApp('/messages?about=quote&id=301&number=KP-2026-0042');
    await heading('Сообщения');
    await within(page()).findByRole('list', { name: 'Переписка с менеджером' });
    expect(within(page()).getByRole('group', { name: 'Документ, о котором вопрос' })).toHaveTextContent('КП KP-2026-0042');

    await user.type(within(page()).getByLabelText('Сообщение менеджеру'), 'Когда отгрузка?{Enter}');
    expect(await within(feed()).findByText('Отправляется…')).toBeInTheDocument();
    expect(within(page()).getByLabelText('Сообщение менеджеру')).toHaveValue('');
    // метка ушла с сообщением: адрес чата меняется навигацией роутера — асинхронно
    await waitFor(() =>
      expect(within(page()).queryByRole('group', { name: 'Документ, о котором вопрос' })).not.toBeInTheDocument(),
    );

    release();
    await waitFor(() => expect(within(feed()).queryByText('Отправляется…')).not.toBeInTheDocument());
    const sent = body.current as { text: string; client_message_id: string; context: unknown };
    expect(sent.text).toBe('Когда отгрузка?');
    expect(sent.client_message_id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(sent.context).toEqual({ kind: 'quote', id: 301 });
    const rows = within(feed()).getAllByRole('listitem');
    const last = rows[rows.length - 1];
    expect(last).toHaveTextContent('Когда отгрузка?');
    expect(within(last).getByRole('link', { name: 'КП KP-2026-0042' })).toBeInTheDocument();
  });

  it('не ушло — «Не отправлено · Повторить» тем же client_message_id', async () => {
    signedIn();
    const user = userEvent.setup();
    const keys: string[] = [];
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/messages')) {
        keys.push(((await request.clone().json()) as { client_message_id: string }).client_message_id);
      }
    });
    portalServer.use(
      http.post('*/api/portal/v1/messages', () => HttpResponse.json({ detail: 'HTTP_503' }, { status: 503 }), {
        once: true,
      }),
    );
    renderApp('/messages');
    await heading('Сообщения');
    await within(page()).findByRole('list', { name: 'Переписка с менеджером' });
    await user.type(within(page()).getByLabelText('Сообщение менеджеру'), 'Проверка связи');
    await user.click(within(page()).getByRole('button', { name: 'Отправить' }));

    expect(await within(feed()).findByText('Не отправлено')).toBeInTheDocument();
    await user.click(within(feed()).getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(within(feed()).queryByText('Не отправлено')).not.toBeInTheDocument());
    expect(within(feed()).getAllByText('Проверка связи')).toHaveLength(1);
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });

  it('текст — только текст: HTML из ответа не исполняется, переносы сохраняются', async () => {
    signedIn();
    renderApp('/messages');
    await heading('Сообщения');
    await within(page()).findByRole('list', { name: 'Переписка с менеджером' });
    pushManagerReply('<img src=x onerror="alert(1)"><b>жирный</b>');
    setVisibility('visible');
    expect(await within(feed()).findByText('<img src=x onerror="alert(1)"><b>жирный</b>')).toBeInTheDocument();
    expect(page().querySelector('img, b')).toBeNull();
    expect(within(feed()).getByText(/платёжку приложили/)).toHaveClass('whitespace-pre-wrap');
  });

  it('без права действовать: поле закрыто с пояснением (контакт на узбекском — тексты uz)', async () => {
    signedIn('viewer');
    renderApp('/messages');
    await heading('Xabarlar');
    await within(page()).findByRole('list', { name: 'Menejer bilan yozishma' });
    expect(within(page()).getByLabelText('Menejerga xabar')).toBeDisabled();
    expect(within(page()).getByRole('button', { name: 'Yuborish' })).toBeDisabled();
    expect(within(page()).getByText(/sizda faqat ko‘rish/)).toBeInTheDocument();
  });

  it('пустая лента — подсказка, что писать сюда', async () => {
    signedIn('actor', 'empty');
    renderApp('/messages');
    await heading('Сообщения');
    expect(await within(page()).findByRole('heading', { name: 'Здесь будет переписка с менеджером' })).toBeInTheDocument();
    await expectNoAxeViolations();
  });
});
