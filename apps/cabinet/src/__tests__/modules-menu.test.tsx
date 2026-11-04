import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { parse } from 'yaml';
import { axe } from 'vitest-axe';

import { NAV_ITEMS, navFor } from '@/app/nav';
import i18n from '@/i18n';
import { CLIENT_ACCESS } from '@/mocks/fixtures';
import { renderApp, signedIn } from '@/test/render';

/** Меню строится из `/me.modules` (ADR-0022, PART-1): клиент — прежнее меню, партнёр — по включённым модулям. */

const CLIENT_LINKS = [
  'Запросы',
  'КП',
  'Каталог',
  'Документы',
  'Договоры',
  'Счета',
  'Акты',
  'Поставки',
  'Компания',
  'Команда',
  'Профиль',
];

const PARTNER_DEFAULT = { roles: ['partner' as const], modules: ['my_products', 'catalog_requests', 'profile'] };
const PARTNER_PRODUCTS_ONLY = { roles: ['partner' as const], modules: ['my_products', 'profile'] };

describe('меню из /me.modules', () => {
  it('клиент: меню прежнее — те же 11 пунктов в том же порядке, нижняя навигация с «Ещё»', async () => {
    signedIn();
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });

    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(CLIENT_LINKS);
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(
      within(bottom)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(['Запросы', 'КП', 'Каталог', 'Документы']);
    expect(within(bottom).getByRole('button', { name: 'Ещё' })).toBeInTheDocument();
  });

  it('шаблон клиента в моках — тот же, что в контракте, и каждому модулю клиента есть пункт меню', async () => {
    // Типов node в Cabinet нет (tsconfig.app): модуль берётся динамически, строкой
    const fs = (await import('node:fs' as string)) as { readFileSync: (path: string, encoding: string) => string };
    // vitest идёт из apps/cabinet
    const contract = parse(fs.readFileSync('../../packages/contracts/openapi/erp-portal.yaml', 'utf8'));
    const template = contract.components.schemas.Me['x-role-modules'];
    expect(CLIENT_ACCESS.modules).toEqual(template.client);
    expect(new Set(NAV_ITEMS.map((item) => item.module))).toEqual(new Set(template.client));
    expect(contract.components.schemas.Me['x-role-default-modules'].partner).toEqual(PARTNER_DEFAULT.modules);
  });

  it('навигация: неизвестные модули не рисуются, пустой список — пустое меню', () => {
    expect(navFor(['my_products', 'something_new']).items).toEqual([]);
    expect(navFor([]).items).toEqual([]);
    expect(navFor(undefined).items).toEqual([]);
    expect(navFor(['catalog_requests', 'something_new']).items.map((item) => item.to)).toEqual([
      '/requests',
      '/catalog',
    ]);
    // «Профиль» есть у любой сессии, но рабочим разделом не считается
    expect(navFor(['my_products', 'profile']).items.map((item) => item.to)).toEqual(['/profile']);
    expect(navFor(['my_products', 'profile']).work).toEqual([]);
  });

  it('партнёр с «Каталог и заявки»: «Запросы», «Каталог» и «Профиль»; корень ведёт в «Запросы»', async () => {
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(router.state.location.pathname).toBe('/requests');

    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(['Запросы', 'Каталог', 'Профиль']);
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(within(bottom).getByRole('button', { name: 'Ещё' })).toBeInTheDocument(); // в «Ещё» — «Профиль»
  });

  it('партнёр: «Запросы» без виджета решений (КП, счетов, актов у него нет); «Новый запрос» — по can_act, как у клиента', async () => {
    // Мок: контакт «actor» с правом действовать, «viewer» — без права (и с узбекским языком): тексты берём из словаря
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const actor = renderApp('/requests');
    await screen.findByText('Z-2026-0061');
    expect(screen.getByRole('link', { name: i18n.t('pages.requests.new') })).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('widgets.actionRequired.title'))).not.toBeInTheDocument();
    expect(screen.queryByTestId('action-required-error')).not.toBeInTheDocument();
    // «Проект …» — просто текст: страница проекта собирает КП, договоры и счета
    expect(screen.queryByRole('link', { name: /D-57/ })).not.toBeInTheDocument();
    expect(screen.getByText(/D-57/)).toBeInTheDocument();
    actor.unmount();

    signedIn('viewer', 'demo', PARTNER_DEFAULT);
    renderApp('/requests');
    await screen.findByText('Z-2026-0061');
    expect(screen.queryByRole('link', { name: i18n.t('pages.requests.new') })).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('common.viewOnly'))).toBeInTheDocument();
  });

  it('клиент видит «Проект …» ссылкой', async () => {
    signedIn();
    renderApp('/requests');
    await screen.findByText('Z-2026-0061');
    expect(screen.getByRole('link', { name: /D-57/ })).toHaveAttribute('href', '/deals/57');
  });

  it('клиент без права действовать по-прежнему только смотрит', async () => {
    signedIn('viewer');
    renderApp('/requests');

    await screen.findByText('Z-2026-0061');
    expect(screen.queryByRole('link', { name: i18n.t('pages.requests.new') })).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('common.viewOnly'))).toBeInTheDocument();
  });

  it('партнёр открывает клиентский раздел по адресу — возвращается в доступный', async () => {
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });

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
      await waitFor(() => expect(router.state.location.pathname, path).toBe('/requests'));
      expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' }), path).toBeInTheDocument();
    }
  });

  it('партнёр без известных разделов: «Доступ открыт…», в меню только «Профиль»', async () => {
    signedIn('actor', 'demo', PARTNER_PRODUCTS_ONLY);
    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Доступ открыт' })).toBeInTheDocument();
    expect(
      screen.getByText('Разделы для вашей компании ещё настраиваются — свяжитесь с вашим менеджером.'),
    ).toBeInTheDocument();
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(['Профиль']);
    expect(screen.queryByText(/скоро/i)).not.toBeInTheDocument();
  });

  it('пустой список модулей — тот же экран', async () => {
    signedIn('actor', 'demo', { roles: ['partner'], modules: [] });
    renderApp('/requests');
    expect(await screen.findByRole('heading', { level: 1, name: 'Доступ открыт' })).toBeInTheDocument();
  });

  it.each([
    ['по умолчанию', PARTNER_DEFAULT, '/requests'],
    ['только «Мои товары» (экран «Доступ открыт»)', PARTNER_PRODUCTS_ONLY, '/'],
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

  it('axe: экран «Доступ открыт» и меню партнёра без нарушений', async () => {
    signedIn('actor', 'demo', PARTNER_PRODUCTS_ONLY);
    const empty = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Доступ открыт' });
    expect((await axe(empty.container)).violations).toEqual([]);
    empty.unmount();

    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const menu = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect((await axe(menu.container)).violations).toEqual([]);
  });
});
