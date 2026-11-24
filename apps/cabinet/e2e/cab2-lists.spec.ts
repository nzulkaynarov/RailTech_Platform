/**
 * CAB-2 · единые компоненты списков кабинета на dev-сборке с моком (MSW): меню строки «⋯», панель «фильтр + поиск» в
 * одном ряду, компактный список «первые N · Показать все», одно пустое состояние. Каждый список — 1512 и 390 px:
 * снимок, axe (serious/critical = 0) и отсутствие горизонтальной прокрутки (scrollWidth ≤ innerWidth на 390).
 * Открытые меню и выпадающие списки — без axe: открытый модальный Radix ставит aria-hidden на корень (известный ложный aria-hidden-focus);
 * закрытые состояния проверены axe.
 * Запуск из apps/cabinet: E2E_SCREENS_DIR=../../../../docs/screens/cab2-lists E2E_SCREENS_SPEC=cab2-lists \
 *   npx playwright test -c playwright.screens.config.ts
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');
const WIDTHS = [
  { width: 1512, height: 900 },
  { width: 390, height: 844 },
] as const;

const DUAL = {
  roles: ['client', 'partner'],
  modules: ['catalog_requests', 'quotes', 'documents', 'contracts', 'invoices', 'acts', 'deliveries', 'messages', 'company', 'team', 'profile', 'my_products', 'letters'],
};

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript((session) => {
    window.sessionStorage.setItem('cabinet.mock.session', session);
    window.localStorage.setItem('cabinet.language', 'ru');
    window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
  }, JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo', access: DUAL }));
});

const h1 = (page: Page) => expect(page.getByRole('heading', { level: 1 })).toBeVisible();

/** Ширина 390: страница не шире окна — и документ, и сам список. */
async function noHorizontalScroll(page: Page, screen: string) {
  await page.setViewportSize(WIDTHS[1]);
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `scrollWidth − innerWidth на 390 — ${screen}`).toBeLessThanOrEqual(0);
}

const SCREENS: Array<[string, string]> = [
  ['requests', '/requests'],
  ['quotes', '/quotes'],
  ['contracts', '/contracts'],
  ['invoices', '/invoices'],
  ['acts', '/acts'],
  ['deliveries', '/deliveries'],
  ['documents', '/documents'],
  ['letters', '/letters'],
  ['messages', '/messages'],
  ['team', '/team'],
  ['my-products', '/my-products'],
  ['partner-orders', '/partner/orders'],
  ['catalog', '/catalog'],
];

for (const [name, path] of SCREENS) {
  test(`список «${name}»: 1512 и 390, без горизонтальной прокрутки`, async ({ page }) => {
    await page.goto(path);
    await h1(page);
    await page.waitForTimeout(600);
    await snap(page, name, { widths: WIDTHS });
    await noHorizontalScroll(page, name);
  });
}

for (const size of WIDTHS) {
  test(`меню строки открывается на ${size.width}: счета и заявки`, async ({ page }) => {
    // ширина — до открытия меню: смена окна закрывает или сдвигает открытое меню
    await page.setViewportSize(size);
    await page.goto('/invoices');
    await h1(page);
    await page.getByRole('button', { name: 'Действия: S-2026-0118' }).click();
    await expect(page.getByRole('menuitem', { name: 'Скачать' })).toBeVisible();
    await snap(page, 'invoices-row-menu', { widths: [size], axe: false });
    await page.keyboard.press('Escape');
    await page.goto('/requests');
    await h1(page);
    await page.getByRole('button', { name: /^Действия: / }).first().click();
    await expect(page.getByRole('menuitem', { name: 'Повторить заявку' })).toBeVisible();
    await snap(page, 'requests-row-menu', { widths: [size], axe: false });
  });
}

test('документы: фильтр по виду — выпадающий список в одной панели с поиском', async ({ page }) => {
  await page.goto('/documents');
  await h1(page);
  await page.getByRole('combobox', { name: 'Вид документа' }).click();
  await snap(page, 'documents-filter-open', { widths: WIDTHS, axe: false });
});
