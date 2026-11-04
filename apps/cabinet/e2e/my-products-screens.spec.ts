/**
 * PART-2 · «Мои товары» партнёра на dev-сборке с моком портального API: список, карточка с подсветкой замечаний, мастер
 * загрузки прайса (проверка с ошибками по строкам, готово), пустой раздел с тремя шагами, меню клиента-партнёра
 * «Покупаю / Поставляю». На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0) и отсутствие горизонтальной
 * прокрутки (`snap`). «Сегодня» — день фикстур мока (2026-10-14).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

const PARTNER = { roles: ['partner'], modules: ['my_products', 'catalog_requests', 'profile'] };
const DUAL = {
  roles: ['client', 'partner'],
  modules: ['catalog_requests', 'quotes', 'documents', 'contracts', 'invoices', 'acts', 'deliveries', 'company', 'team', 'profile', 'my_products'],
};

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
});

async function signIn(page: Page, access: { roles: string[]; modules: string[] }, dataset: 'demo' | 'empty' = 'demo') {
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset, access })] as const,
  );
}

const h1 = (page: Page, name: string) => expect(page.getByRole('heading', { level: 1, name })).toBeVisible();

test('список: вкладки с количеством, свои цены, пометки свежести, возвращённая карточка', async ({ page }) => {
  await signIn(page, PARTNER);
  await page.goto('/my-products');
  await h1(page, 'Мои товары');
  await expect(page.getByRole('list', { name: 'Мои карточки' }).or(page.getByRole('table', { name: 'Мои карточки' }))).toBeVisible();
  await snap(page, 'my-products-list');
});

test('отправка на проверку: выбор, диалог, «Проверка обычно занимает 1 рабочий день»', async ({ page }) => {
  await signIn(page, PARTNER);
  await page.goto('/my-products');
  await h1(page, 'Мои товары');
  await page.getByRole('checkbox', { name: /Выбрать карточку Тормозная колодка/ }).check();
  await page.getByRole('button', { name: 'Отправить на проверку (1)' }).click();
  await snap(page, 'my-products-submit-dialog');
  await page.getByRole('dialog').getByRole('button', { name: 'Отправить' }).click();
  await expect(page.getByText('Проверка обычно занимает 1 рабочий день', { exact: false })).toBeVisible();
  await snap(page, 'my-products-submitted');
});

test('карточка: замечания сотрудника привязаны к полям', async ({ page }) => {
  await signIn(page, PARTNER);
  await page.goto('/my-products?card=9005');
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByText('Укажите артикул по шильдику изделия').first()).toBeVisible();
  await snap(page, 'my-products-card-returned');
});

test('мастер: проверка файла с ошибками по строкам, затем готово', async ({ page }) => {
  await signIn(page, PARTNER);
  await page.goto('/my-products');
  await h1(page, 'Мои товары');
  await page.getByRole('button', { name: 'Загрузить прайс' }).click();
  const dialog = page.getByRole('dialog', { name: 'Загрузка прайса' });
  await expect(dialog).toBeVisible();
  await snap(page, 'my-products-wizard-file');
  await dialog.locator('input[type="file"]').setInputFiles({ name: 'errors.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from([0x50, 0x4b, 3, 4]) });
  await dialog.getByRole('button', { name: 'Проверить файл' }).click();
  await expect(dialog.getByText('Проверка завершена')).toBeVisible();
  await expect(dialog.getByText('Строка 4')).toBeVisible();
  await snap(page, 'my-products-wizard-preview');
  await dialog.getByRole('button', { name: 'Загрузить без ошибочных строк' }).click();
  await expect(dialog.getByText('Прайс загружен')).toBeVisible();
  await snap(page, 'my-products-wizard-done');
});

test('пустой раздел: три шага с кнопками', async ({ page }) => {
  await signIn(page, PARTNER, 'empty');
  await page.goto('/my-products');
  await expect(page.getByRole('heading', { name: 'Загрузите прайс по шаблону — карточки появятся здесь' })).toBeVisible();
  await snap(page, 'my-products-empty');
});

test('меню клиента-партнёра: «Покупаю», «Поставляю», «Компания»', async ({ page }) => {
  await signIn(page, DUAL);
  await page.goto('/my-products');
  await h1(page, 'Мои товары');
  await expect(page.getByRole('navigation', { name: 'Разделы кабинета' }).getByRole('heading', { name: 'Поставляю' })).toBeVisible();
  await snap(page, 'menu-client-and-partner');
});
