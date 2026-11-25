import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { parse } from 'yaml';
import { afterEach, describe, expect, it } from 'vitest';
import { axe } from 'vitest-axe';

import { NAV_ITEMS, navFor } from '@/app/nav';
import i18n from '@/i18n';
import type { Schemas } from '@/api/portal';
import { CLIENT_ACCESS } from '@/mocks/fixtures';
import { setMockPartnerApplication } from '@/mocks/handlers';
import { renderApp, signedIn } from '@/test/render';

/** Меню строится из `/me.modules` (ADR-0022, PART-1): клиент — прежнее меню, партнёр — по включённым модулям. */

const CLIENT_LINKS = [
  'Заявки',
  'КП',
  'Каталог',
  'Поставки',
  'Договоры',
  'Счета',
  'Акты',
  'Письма',
  'Все документы',
  'Сообщения',
  'Компания',
  'Команда',
  'Профиль',
];

const PARTNER_DEFAULT = {
  roles: ['partner' as const],
  modules: ['my_products', 'catalog_requests', 'letters', 'messages', 'profile'],
};
/** То, что сервер даёт новому партнёру: раздела покупателя нет (ДК-5), он — только поставщик. */
const PARTNER_SELLER = { roles: ['partner' as const], modules: ['my_products', 'letters', 'messages', 'profile'] };
const PARTNER_PRODUCTS_ONLY = { roles: ['partner' as const], modules: ['my_products', 'profile'] };
/** Партнёр, у которого сотрудник выключил оба раздела: остался только «Профиль». */
const PARTNER_NOTHING = { roles: ['partner' as const], modules: ['profile'] };

/** Клиент, у которого сотрудник завёл ещё и партнёрское отношение: обе роли, клиентские модули и «Мои товары». */
const DUAL = { roles: ['client' as const, 'partner' as const], modules: [...CLIENT_ACCESS.modules, 'my_products'] };

describe('меню по блокам «Покупаю · Продаю · Документы · Компания» (план §3d ЛИД-1)', () => {
  it('две роли: четыре блока, а не четырнадцать пунктов подряд', async () => {
    signedIn('actor', 'demo', DUAL);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' }); // корень — первый раздел «Покупаю»
    expect(router.state.location.pathname).toBe('/requests');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(within(side).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Покупаю', 'Продаю', 'Документы', 'Компания']);
    const groups = within(side).getAllByRole('group');
    expect(groups.map((group) => within(group).getAllByRole('link').map((link) => link.textContent?.replace(/\d+/g, '').trim()))).toEqual([
      ['Заявки', 'КП', 'Каталог', 'Поставки'],
      ['Мои товары', 'Заказы на поставку'],
      ['Договоры', 'Счета', 'Акты', 'Письма', 'Все документы'],
      // «Сообщения» (CHAT-1) — в «Компании»: беседа компании с нами одна и о покупках, и о поставках
      ['Сообщения', 'Компания', 'Команда', 'Профиль'],
    ]);
    expect((await axe(side)).violations).toEqual([]);
  });

  it('телефон: внизу запросы, КП, каталог и «Мои товары»; «Ещё» — по тем же блокам', async () => {
    signedIn('actor', 'demo', DUAL);
    const user = userEvent.setup();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(
      within(bottom)
        .getAllByRole('link')
        .map((link) => link.textContent?.replace(/\d+/g, '').trim()),
    ).toEqual(['Заявки', 'КП', 'Каталог', 'Мои товары']);
    await user.click(within(bottom).getByRole('button', { name: 'Ещё' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Покупаю', 'Продаю', 'Документы', 'Компания']);
    expect(within(sheet).getByRole('link', { name: 'Договоры' })).toBeInTheDocument();
    expect(within(sheet).getByRole('link', { name: 'Заказы на поставку' })).toBeInTheDocument();
    expect(within(sheet).getByRole('link', { name: 'Профиль' })).toBeInTheDocument();
  });

  it('«Мои товары» открывается из меню, адрес и заголовок раздела', async () => {
    signedIn('actor', 'demo', DUAL);
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });
    await user.click(within(screen.getByRole('navigation', { name: 'Разделы кабинета' })).getByRole('link', { name: 'Мои товары' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Мои товары' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/my-products');
  });

  it('клиент без партнёрской роли: те же блоки, только без «Продаю»', async () => {
    signedIn();
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(within(side).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Покупаю', 'Документы', 'Компания']);
    expect(within(side).queryByRole('link', { name: 'Мои товары' })).not.toBeInTheDocument();
  });

  it('обе роли, но «Мои товары» выключены: меню как у клиента', () => {
    const nav = navFor(CLIENT_ACCESS.modules, ['client', 'partner']);
    expect(nav.groups.map((group) => group.key)).toEqual(['buy', 'documents', 'company']);
    expect(nav.items.map((item) => item.to)).toEqual(navFor(CLIENT_ACCESS.modules, ['client']).items.map((item) => item.to));
  });

  it('все ключи разделов есть в трёх словарях', () => {
    for (const language of ['ru', 'uz', 'en']) {
      for (const key of ['nav.groups.buy', 'nav.groups.sell', 'nav.groups.documents', 'nav.groups.company', 'nav.myProducts', 'nav.partnerOrders']) {
        expect(i18n.exists(key, { lng: language }), `${language}: ${key}`).toBe(true);
      }
    }
  });
});

describe('меню из /me.modules', () => {
  it('клиент: меню — 12 пунктов в том же порядке (+ «Сообщения», CHAT-1), нижняя навигация с «Ещё»', async () => {
    signedIn();
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });

    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.replace(/\d+/g, '').trim()),
    ).toEqual(CLIENT_LINKS);
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(
      within(bottom)
        .getAllByRole('link')
        .map((link) => link.textContent?.replace(/\d+/g, '').trim()),
    ).toEqual(['Заявки', 'КП', 'Каталог', 'Все документы']);
    expect(within(bottom).getByRole('button', { name: 'Ещё' })).toBeInTheDocument();
  });

  it('шаблон клиента в моках — тот же, что в контракте, и каждому модулю клиента есть пункт меню', async () => {
    // Типов node в Cabinet нет (tsconfig.app): модуль берётся динамически, строкой
    const fs = (await import('node:fs' as string)) as { readFileSync: (path: string, encoding: string) => string };
    // vitest идёт из apps/cabinet
    const contract = parse(fs.readFileSync('../../packages/contracts/openapi/erp-portal.yaml', 'utf8'));
    const template = contract.components.schemas.Me['x-role-modules'];
    expect(CLIENT_ACCESS.modules).toEqual(template.client);
    // «Мои товары» — модуль партнёра, не клиента: в шаблоне клиента его нет, и клиентского пункта меню он не добавляет
    expect(new Set(NAV_ITEMS.filter((item) => item.group !== 'sell').map((item) => item.module))).toEqual(
      new Set(template.client),
    );
    expect(new Set(NAV_ITEMS.filter((item) => item.group === 'sell').map((item) => item.module))).toEqual(new Set(['my_products']));
    expect(contract.components.schemas.Me['x-role-default-modules'].partner).toEqual(PARTNER_SELLER.modules);
  });

  it('навигация: неизвестные модули не рисуются, пустой список — пустое меню', () => {
    expect(navFor(['something_new']).items).toEqual([]);
    expect(navFor([]).items).toEqual([]);
    expect(navFor(undefined).items).toEqual([]);
    expect(navFor(['catalog_requests', 'something_new']).items.map((item) => item.to)).toEqual([
      '/requests',
      '/catalog',
    ]);
    // «Профиль» есть у любой сессии, но рабочим разделом не считается
    expect(navFor(['profile']).items.map((item) => item.to)).toEqual(['/profile']);
    expect(navFor(['profile']).work).toEqual([]);
    // «Мои товары» — первым пунктом партнёра: у партнёра без клиентской роли первым идёт блок «Продаю»
    expect(navFor(['my_products', 'catalog_requests', 'profile'], ['partner']).items.map((item) => item.to)).toEqual([
      '/my-products',
      '/partner/orders',
      '/requests',
      '/catalog',
      '/profile',
    ]);
    expect(navFor(['my_products', 'catalog_requests', 'profile'], ['partner']).groups.map((group) => group.key)).toEqual([
      'sell',
      'buy',
      'company',
    ]);
  });

  it('партнёр с обоими модулями: «Мои товары», «Запросы», «Каталог» и «Профиль»; корень ведёт в «Мои товары»', async () => {
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Мои товары' });
    expect(router.state.location.pathname).toBe('/my-products');

    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.replace(/\d+/g, '').trim()),
    ).toEqual(['Мои товары', 'Заказы на поставку', 'Заявки', 'Каталог', 'Письма', 'Сообщения', 'Профиль']);
    // партнёр: первым «Продаю»; в «Документах» пока только «Письма» (ADR-0026), договор и оплаты — план §3d ЛИД-6
    expect(within(side).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Продаю', 'Покупаю', 'Документы', 'Компания']);
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(within(bottom).getByRole('button', { name: 'Ещё' })).toBeInTheDocument(); // в «Ещё» — «Сообщения», «Профиль»
  });

  it('партнёр: «Запросы» без виджета решений (КП, счетов, актов у него нет); «Новый запрос» — по can_act, как у клиента', async () => {
    // Мок: контакт «actor» с правом действовать, «viewer» — без права (и с узбекским языком): тексты берём из словаря
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const actor = renderApp('/requests');
    await screen.findByText('ЗВ-2026-061');
    expect(screen.getByRole('link', { name: i18n.t('pages.requests.new') })).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('widgets.actionRequired.title'))).not.toBeInTheDocument();
    expect(screen.queryByTestId('action-required-error')).not.toBeInTheDocument();
    // «Проект …» — просто текст: страница проекта собирает КП, договоры и счета
    const actorList = screen.getByRole('list', { name: 'Заявки' });
    expect(within(actorList).queryByRole('link', { name: /Проект ПР-2026-057/ })).not.toBeInTheDocument();
    expect(within(actorList).getByText(/Проект ПР-2026-057/)).toBeInTheDocument();
    actor.unmount();

    signedIn('viewer', 'demo', PARTNER_DEFAULT);
    renderApp('/requests');
    await screen.findByText('ЗВ-2026-061');
    expect(document.querySelector('a[href="/requests/new"]')).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('common.viewOnly'))).toBeInTheDocument();
  });

  it('клиент видит «Проект …» ссылкой', async () => {
    signedIn();
    renderApp('/requests');
    await screen.findByText('ЗВ-2026-061');
    const list = screen.getByRole('list', { name: 'Заявки' });
    expect(within(list).getByRole('link', { name: /Проект ПР-2026-057/ })).toHaveAttribute('href', '/deals/57');
  });

  it('клиент без права действовать по-прежнему только смотрит', async () => {
    signedIn('viewer');
    renderApp('/requests');

    await screen.findByText('ЗВ-2026-061');
    expect(screen.queryByRole('link', { name: i18n.t('pages.requests.new') })).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('common.viewOnly'))).toBeInTheDocument();
  }, 60_000); // 12 s alone (same on main), 30 s under CI load: first render of the whole app

  it('партнёр открывает клиентский раздел по адресу — возвращается в доступный', async () => {
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });
    await router.navigate('/quotes');
    await waitFor(() => expect(router.state.location.pathname).toBe('/my-products')); // первый раздел партнёра
    await router.navigate('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });

    for (const path of [
      '/quotes',
      '/contracts',
      '/invoices',
      '/acts',
      '/deliveries',
      '/documents',
      '/team',
      '/quotes/301',
    ]) {
      await router.navigate(path);
      await waitFor(() => expect(router.state.location.pathname, path).toBe('/my-products'));
      expect(await screen.findByRole('heading', { level: 1, name: 'Мои товары' }), path).toBeInTheDocument();
    }
  });

  it('партнёр только с «Мои товары»: два пункта, корень ведёт в «Заказы на поставку», клиентские разделы закрыты', async () => {
    signedIn('actor', 'demo', PARTNER_PRODUCTS_ONLY);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });
    expect(router.state.location.pathname).toBe('/partner/orders');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.replace(/\d+/g, '').trim()),
    ).toEqual(['Мои товары', 'Заказы на поставку', 'Профиль']);
    await router.navigate('/requests');
    await waitFor(() => expect(router.state.location.pathname).toBe('/my-products'));
  });

  it('новый партнёр (шаблон сервера): раздела покупателя в меню нет, вход ведёт в «Заказы на поставку» (ДК-5)', async () => {
    signedIn('actor', 'demo', PARTNER_SELLER);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });
    expect(router.state.location.pathname).toBe('/partner/orders');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    const names = within(side)
      .getAllByRole('link')
      .map((link) => link.textContent?.replace(/\d+/g, '').trim());
    expect(names).not.toContain('Заявки');
    expect(names).not.toContain('Каталог');
  });

  it('партнёр без разделов (оба модуля выключены): «Разделы ещё не открыты…», в меню только «Профиль»', async () => {
    signedIn('actor', 'demo', PARTNER_NOTHING);
    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Разделы ещё не открыты' })).toBeInTheDocument();
    expect(
      screen.getByText('Менеджер откроет их для вашей компании — напишите ему, если ждёте долго.'),
    ).toBeInTheDocument();
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(['Профиль']);
    expect(screen.queryByText(/скоро/i)).not.toBeInTheDocument();
  });

  describe('кандидат в партнёры (FX-1): сервер отдаёт roles=[partner], modules=[messages, profile]', () => {
    const CANDIDATE = { roles: ['partner' as const], modules: ['messages', 'profile'] };
    const CONTRACT_SENT = {
      id: 701,
      status: 'contract_sent',
      kind: 'supplier',
      categories_description: 'Крепёж и рельсовые скрепления',
      company_name: 'ООО Кандидат',
      inn: '7722222222',
      contact_name: 'Кандидат',
      email: 'candidate@candidate.example',
      phone: null,
      contract_number: 'PART-2026-0701',
      contract_date: '2026-11-08',
      rejected_reason: null,
      created_at: '2026-11-08T10:00:00Z',
      updated_at: '2026-11-08T11:00:00Z',
    } as Schemas['PartnerApplication'];

    afterEach(() => setMockPartnerApplication(null));

    it('на главной — карточка заявки с кнопкой согласования', async () => {
      signedIn('actor', 'demo', CANDIDATE);
      setMockPartnerApplication(CONTRACT_SENT);
      const { container } = renderApp('/');
      expect(await screen.findByRole('button', { name: 'Согласовать проект договора' })).toBeInTheDocument();
      expect((await axe(container)).violations).toEqual([]);
    });

    it('с разделом «Письма» в модулях кандидат всё равно попадает на карточку договора (ПД-1)', async () => {
      signedIn('actor', 'demo', { ...CANDIDATE, modules: ['messages', 'profile', 'letters'] });
      setMockPartnerApplication(CONTRACT_SENT);
      const { router } = renderApp('/');
      expect(await screen.findByRole('button', { name: 'Согласовать проект договора' })).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/');
    });

    it('раздел «Компания» приводит к той же карточке', async () => {
      signedIn('actor', 'demo', CANDIDATE);
      setMockPartnerApplication(CONTRACT_SENT);
      const { router } = renderApp('/company');
      expect(await screen.findByRole('button', { name: 'Согласовать проект договора' })).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/');
    });

    it('без заявки — обычный первый раздел', async () => {
      signedIn('actor', 'demo', CANDIDATE);
      setMockPartnerApplication(null);
      const { router } = renderApp('/');
      await waitFor(() => expect(router.state.location.pathname).toBe('/messages'));
    });
  });

  it.each([
    ['по умолчанию', PARTNER_DEFAULT, '/requests'],
    ['без разделов (экран «Разделы ещё не открыты»)', PARTNER_NOTHING, '/'],
  ])('профиль партнёра %s: меню «Профиль», смена языка и выход', async (_name, access, start) => {
    signedIn('actor', 'demo', access);
    const user = userEvent.setup();
    const { router } = renderApp(start);
    await screen.findByRole('navigation', { name: 'Разделы кабинета' });

    await user.click(within(screen.getByRole('navigation', { name: 'Разделы кабинета' })).getByRole('link', { name: 'Профиль' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Профиль' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/profile');

    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Profile' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Русский' }));
    await screen.findByRole('heading', { level: 1, name: 'Профиль' });

    await user.click(screen.getByRole('button', { name: 'Выйти из кабинета' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
  });

  it('axe: экран «Разделы ещё не открыты» и меню партнёра без нарушений', async () => {
    signedIn('actor', 'demo', PARTNER_NOTHING);
    const empty = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Разделы ещё не открыты' });
    expect((await axe(empty.container)).violations).toEqual([]);
    empty.unmount();

    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const menu = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Заявки' });
    expect((await axe(menu.container)).violations).toEqual([]);
  });
});
