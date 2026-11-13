import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { botLink } from '@/app/links';
import { CLIENT_ACCESS } from '@/mocks/fixtures';
import { chatLink, contextFromSearch } from '@/lib/messages';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

/**
 * «Написать менеджеру» (CHAT-1, ADR-0023): чат кабинета с меткой документа, а не бот — общение в кабинете не уводит в
 * Telegram. Бот — второй канал: ссылка на экране чата, вход и «Я новый клиент». Имя бота в тестах — `railtech_test_bot`.
 */
const BOT = 'https://t.me/railtech_test_bot';
/** Экран сделки собирается из семи списков портала — под параллельной нагрузкой дольше 1 с. */
const LOADED = { timeout: 5000 };
/** Содержимое экрана: роль ищется внутри `<main>` (CONVENTIONS, «Правило тестов»). */
const page = () => document.querySelector('main') as HTMLElement;
const chat = (kind: string, id: number, number: string) => chatLink({ kind: kind as 'deal', id, number });

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('ссылки', () => {
  it('chatLink: метка документа в адресе чата; без метки — просто чат', () => {
    expect(chatLink(null)).toBe('/messages');
    expect(chat('quote', 301, 'KP-2026-0042')).toBe('/messages?about=quote&id=301&number=KP-2026-0042');
  });

  it('contextFromSearch: неполная или чужая метка не принимается', () => {
    const parse = (query: string) => contextFromSearch(new URLSearchParams(query));
    expect(parse('about=act&id=701&number=A-2026-0090')).toEqual({ kind: 'act', id: 701, number: 'A-2026-0090' });
    expect(parse('about=contract&id=1&number=X')).toBeNull();
    expect(parse('about=quote&id=abc&number=X')).toBeNull();
    expect(parse('about=quote&id=301')).toBeNull();
  });

  it('бот — второй канал: имя с @ принимается, пустое — ссылок нет', () => {
    vi.stubEnv('VITE_BOT_USERNAME', '@railtech_test_bot');
    expect(botLink('web')).toBe(`${BOT}?start=web`);
    vi.stubEnv('VITE_BOT_USERNAME', '');
    expect(botLink('web')).toBeNull();
  });
});

describe('«Написать менеджеру» на экранах', () => {
  it('сделка: кнопка в шапке ведёт в чат кабинета с меткой проекта, не в Telegram', async () => {
    signedIn();
    renderApp('/deals/35');
    await heading('Проект ПР-2026-035');
    const link = await within(page()).findByRole('link', { name: 'Написать менеджеру о проекте ПР-2026-035' }, LOADED);
    expect(link).toHaveAttribute('href', chat('deal', 35, 'ПР-2026-035'));
    expect(link).not.toHaveAttribute('target');
    expect(link).toHaveTextContent('Написать менеджеру');
    await expectNoAxeViolations();
  });

  it('карточка КП: метка этого КП', async () => {
    signedIn();
    renderApp('/quotes/301');
    await heading(/KP-2026-0042/);
    const link = within(page()).getByRole('link', { name: 'Написать менеджеру о КП KP-2026-0042' });
    expect(link).toHaveAttribute('href', chat('quote', 301, 'KP-2026-0042'));
  });

  it.each([
    ['/contracts', 'Договоры', 'Написать менеджеру о договоре D-2026-0048', chat('deal', 48, 'ПР-2026-048')],
    ['/invoices', 'Счета', 'Написать менеджеру о счёте S-2026-0124', chat('invoice', 603, 'S-2026-0124')],
    ['/acts', 'Акты', 'Написать менеджеру об акте A-2026-0090', chat('act', 701, 'A-2026-0090')],
  ])('%s: в строке — метка документа (договор — его проекта)', async (path, title, name, href) => {
    signedIn();
    renderApp(path);
    await heading(title);
    expect(await within(page()).findByRole('link', { name })).toHaveAttribute('href', href);
    await expectNoAxeViolations();
  });

  it('поставки: в шапке каждого проекта своя метка', async () => {
    signedIn();
    renderApp('/deliveries');
    await heading('Поставки');
    const links = await within(page()).findAllByRole('link', { name: /^Написать менеджеру о (проекте|заявке) (ПР|ЗВ)-\d{4}-\d+$/ });
    expect(links.length).toBeGreaterThan(1);
    for (const link of links) {
      const number = link.getAttribute('aria-label')!.match(/((ПР|ЗВ)-\d{4}-\d+)$/)![1];
      expect(link).toHaveAttribute('href', chat('deal', Number(number.slice(-3)), number));
    }
    await expectNoAxeViolations();
  });

  it('клик открывает чат с плашкой документа', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/quotes/301');
    await heading(/KP-2026-0042/);
    await user.click(within(page()).getByRole('link', { name: 'Написать менеджеру о КП KP-2026-0042' }));
    await heading('Сообщения');
    expect(router.state.location.search).toBe('?about=quote&id=301&number=KP-2026-0042');
    expect(within(page()).getByRole('group', { name: 'Документ, о котором вопрос' })).toHaveTextContent(
      'О документе: КП KP-2026-0042',
    );
  });

  it('модуля «Сообщения» нет у сессии — кнопки нет', async () => {
    signedIn('actor', 'demo', { roles: ['client'], modules: CLIENT_ACCESS.modules.filter((m) => m !== 'messages') });
    renderApp('/deals/35');
    await heading('Проект ПР-2026-035');
    await within(page()).findByRole('region', { name: 'Счета' }, LOADED);
    expect(within(page()).queryByRole('link', { name: /Написать менеджеру/ })).not.toBeInTheDocument();
  });

  it('экран чата: бот — вторая ссылка «Написать в Telegram»; без имени бота её нет', async () => {
    signedIn();
    const first = renderApp('/messages');
    await heading('Сообщения');
    expect(within(page()).getByRole('link', { name: 'Написать в Telegram' })).toHaveAttribute('href', BOT);
    first.unmount();

    vi.stubEnv('VITE_BOT_USERNAME', '');
    renderApp('/messages');
    await heading('Сообщения');
    expect(within(page()).queryByRole('link', { name: 'Написать в Telegram' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /t\.me/ })).toBeNull();
  });
});
