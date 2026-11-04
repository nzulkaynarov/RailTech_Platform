import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';

import i18n from '@/i18n';
import { notificationText, safeNotificationLink } from '@/lib/notifications';
import { notifications } from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { routeForStartParam } from '@/telegram/start-param';

/** Колокольчик кабинета (NOTIFY-2): бейдж из `/me`, лента в шторке, «Прочитать все», переход в объект. */

/** Кнопка колокольчика в шапке; пока шторка открыта, шапка скрыта от диктора (модальный слой) — ищем и там. */
function bell() {
  return within(screen.getByRole('banner', { hidden: true })).getByRole('button', { name: 'Уведомления', hidden: true });
}

async function openPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(bell());
  return screen.findByRole('dialog', { name: 'Уведомления' });
}

describe('колокольчик кабинета', () => {
  it('бейдж — число непрочитанных из /me, для диктора — пояснение', async () => {
    signedIn();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    await waitFor(() => expect(within(bell()).getByText('3')).toBeInTheDocument());
    expect(bell()).toHaveAccessibleDescription('3 непрочитанных уведомления');
  });

  it('лента в шторке без ухода со страницы: объект, действие, время; axe без нарушений', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const panel = await openPanel(user);
    const list = await within(panel).findByRole('list', { name: 'Список уведомлений' });
    const rows = within(list).getAllByRole('button');
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent('Новое КП KP-2026-0042 ждёт вашего решения');
    expect(rows[0]).toHaveTextContent('Не прочитано');
    expect(rows[1]).toHaveTextContent(/Выставлен счёт S-2026-0124 на 9\s800\s000\sсум/);
    expect(rows[2]).toHaveTextContent('Изменился срок поставки по проекту D-35: теперь 24 окт. 2026 г.');
    expect(rows[4]).toHaveTextContent('Поставка по проекту D-35: Отгружено');
    expect(rows[4]).not.toHaveTextContent('Не прочитано');
    expect(router.state.location.pathname).toBe('/requests');
    expect((await axe(document.body)).violations).toEqual([]);
  });

  it('«Прочитать все» гасит бейдж и отметки', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const panel = await openPanel(user);
    await within(panel).findByRole('list', { name: 'Список уведомлений' });
    await user.click(within(panel).getByRole('button', { name: 'Прочитать все' }));
    await waitFor(() => expect(within(panel).queryByText('Не прочитано')).not.toBeInTheDocument());
    expect(within(panel).getByRole('button', { name: 'Прочитать все' })).toBeDisabled();
    expect(within(bell()).queryByText('3')).not.toBeInTheDocument();
  });

  it('клик по уведомлению — отметка прочитанного и переход в объект', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const panel = await openPanel(user);
    const list = await within(panel).findByRole('list', { name: 'Список уведомлений' });
    await user.click(within(list).getAllByRole('button')[1]);
    await waitFor(() => expect(router.state.location.pathname).toBe('/invoices'));
    expect(router.state.location.search).toBe('?focus=603');
    await waitFor(() => expect(within(bell()).getByText('2')).toBeInTheDocument());
    // строка счёта выделена в списке раздела
    const focused = await waitFor(() => {
      const row = document.querySelector('[aria-current="true"]');
      expect(row).not.toBeNull();
      return row as HTMLElement;
    });
    expect(focused).toHaveTextContent('S-2026-0124');
  });

  it('пусто — понятное пустое состояние, бейджа нет', async () => {
    signedIn('actor', 'empty');
    const user = userEvent.setup();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(bell()).not.toHaveAccessibleDescription(/непрочитанн/);
    const panel = await openPanel(user);
    expect(await within(panel).findByText('Новых уведомлений нет')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Прочитать все' })).toBeDisabled();
  });

  it('счётчик опрашивается только при видимой вкладке, ленту отдельно не опрашивает', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signedIn();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const seen: string[] = [];
    const listener = ({ request }: { request: Request }) => seen.push(new URL(request.url).pathname);
    portalServer.events.on('request:start', listener);
    let visibility: DocumentVisibilityState = 'hidden';
    const spy = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    try {
      act(() => void window.dispatchEvent(new Event('visibilitychange')));
      await act(async () => void (await vi.advanceTimersByTimeAsync(130_000)));
      expect(seen.filter((path) => path.endsWith('/me'))).toHaveLength(0);
      visibility = 'visible';
      act(() => void window.dispatchEvent(new Event('visibilitychange')));
      await act(async () => void (await vi.advanceTimersByTimeAsync(61_000)));
      expect(seen.filter((path) => path.endsWith('/me')).length).toBeGreaterThanOrEqual(1);
      expect(seen.some((path) => path.endsWith('/notifications'))).toBe(false);
    } finally {
      portalServer.events.removeListener('request:start', listener);
      spy.mockRestore();
      vi.useRealTimers();
    }
  });
});

describe('текст уведомления', () => {
  const t = i18n.getFixedT('ru');

  it('у каждого вида есть текст во всех трёх словарях', () => {
    const keys = [...notifications.map((item) => item.text_key), 'act_issued_reminder', 'manager_replied', 'payment_overdue', 'partner_card_returned', 'fallback'];
    for (const language of ['ru', 'uz', 'en']) {
      for (const key of keys) {
        expect(i18n.exists(`notifications.text.${key}`, { lng: language }), `${language}: ${key}`).toBe(true);
      }
    }
  });

  it('напоминание об акте и незнакомый вид', () => {
    const act = notifications.find((item) => item.kind === 'act_issued')!;
    expect(notificationText({ ...act, params: { ...act.params, reminder: '1' } }, t)).toBe(
      'Напоминание: акт A-2026-0090 ждёт приёмки',
    );
    expect(notificationText({ ...act, text_key: 'brand_new_kind' }, t)).toBe('Новое уведомление A-2026-0090');
  });

  it('ссылка — только путь кабинета', () => {
    expect(safeNotificationLink('/quotes/1')).toBe('/quotes/1');
    expect(safeNotificationLink('//evil.example/x')).toBe('/profile');
    expect(safeNotificationLink('https://evil.example')).toBe('/profile');
  });
});

describe('объект уведомления и параметр запуска Mini App', () => {
  it('start_param `<тип>_<object.id>` ведёт туда же, куда ссылка уведомления (поставка — id сделки)', () => {
    const START: Record<string, string> = { quote: 'quote', invoice: 'invoice', act: 'act', delivery: 'delivery' };
    const checked = notifications.filter((item) => START[item.object.type]);
    expect(checked.some((item) => item.object.type === 'delivery')).toBe(true);
    for (const item of checked) {
      expect(routeForStartParam(`${START[item.object.type]}_${item.object.id}`), item.kind).toBe(item.link);
    }
  });
});
