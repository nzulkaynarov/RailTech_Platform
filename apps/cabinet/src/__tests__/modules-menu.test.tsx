import { screen, waitFor, within } from '@testing-library/react';
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

const PARTNER_DEFAULT = { roles: ['partner' as const], modules: ['my_products', 'catalog_requests'] };
const PARTNER_PRODUCTS_ONLY = { roles: ['partner' as const], modules: ['my_products'] };

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
  });

  it('партнёр с «Каталог и заявки»: только «Запросы» и «Каталог», без «Ещё»; корень ведёт в «Запросы»', async () => {
    signedIn('actor', 'demo', PARTNER_DEFAULT);
    const { router } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(router.state.location.pathname).toBe('/requests');

    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(
      within(side)
        .getAllByRole('link')
        .map((link) => link.textContent?.trim()),
    ).toEqual(['Запросы', 'Каталог']);
    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    expect(within(bottom).queryByRole('button', { name: 'Ещё' })).not.toBeInTheDocument();
  });

  it('партнёр: «Запросы» без виджета решений (КП, счетов, актов у него нет), «Новый запрос» доступен без can_act', async () => {
    // Контакт «viewer» мока — без права действовать и с узбекским языком: тексты берём из словаря, а не из русской строки
    signedIn('viewer', 'demo', PARTNER_DEFAULT);
    renderApp('/requests');

    await screen.findByText('Z-2026-0061');
    expect(screen.getByRole('link', { name: i18n.t('pages.requests.new') })).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('widgets.actionRequired.title'))).not.toBeInTheDocument();
    expect(screen.queryByTestId('action-required-error')).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t('common.viewOnly'))).not.toBeInTheDocument();
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

  it('партнёр без известных разделов: «Доступ открыт…», меню нет', async () => {
    signedIn('actor', 'demo', PARTNER_PRODUCTS_ONLY);
    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Доступ открыт' })).toBeInTheDocument();
    expect(
      screen.getByText('Разделы для вашей компании ещё настраиваются — свяжитесь с вашим менеджером.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Разделы кабинета' })).toBeInTheDocument(); // пустая боковая панель
    expect(within(screen.getByRole('navigation', { name: 'Разделы кабинета' })).queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryByRole('navigation', { name: 'Основные разделы' })).not.toBeInTheDocument();
    expect(screen.queryByText(/скоро/i)).not.toBeInTheDocument();
  });

  it('пустой список модулей — тот же экран', async () => {
    signedIn('actor', 'demo', { roles: ['partner'], modules: [] });
    renderApp('/requests');
    expect(await screen.findByRole('heading', { level: 1, name: 'Доступ открыт' })).toBeInTheDocument();
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
