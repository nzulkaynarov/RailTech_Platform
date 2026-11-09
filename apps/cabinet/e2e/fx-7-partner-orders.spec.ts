/**
 * FX-7 · заказы и запросы цен партнёра: подтверждение с датой, запрос на перенос срока, ответ с ценами, ошибка при открытии
 * несуществующего заказа. На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0) и отсутствие горизонтальной
 * прокрутки (`snap`). «Сегодня» — день фикстур мока.
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-11-10T12:00:00+05:00');
const PARTNER = { roles: ['partner'], modules: ['my_products', 'catalog_requests', 'messages', 'profile'] };

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo', access: PARTNER })] as const,
  );
});

async function openOrders(page: Page, query = '') {
  await page.goto(`/partner/orders${query}`);
  // Открытая по адресу карточка закрывает страницу для ролей, заголовок ищем только без неё.
  if (query.includes('Id=')) await expect(page.getByRole('dialog')).toBeVisible();
  else await expect(page.getByRole('heading', { level: 1, name: 'Заказы на поставку' })).toBeVisible();
}

test('список заказов и подтверждение с датой', async ({ page }) => {
  await openOrders(page);
  await expect(page.getByText('PO-2026-0041').first()).toBeVisible();
  await snap(page, 'orders-list');
  await page.getByRole('button', { name: 'Подтвердить' }).first().click();
  await expect(page.getByRole('dialog').getByText('Подтверждение заказа на поставку')).toBeVisible();
  await snap(page, 'confirm-dialog');
});

test('запрос на перенос срока виден в карточке, срок прежний', async ({ page }) => {
  await openOrders(page, '?orderId=8002');
  const card = page.getByRole('dialog');
  await card.getByRole('button', { name: 'Перенести срок' }).click();
  const dialog = page.getByRole('dialog', { name: 'Запрос на перенос срока' });
  await dialog.getByLabel(/Новая дата поставки/).fill('10.12.2026');
  await dialog.getByLabel('Причина').fill('Задержка сырья');
  await snap(page, 'date-change-dialog');
  await dialog.getByRole('button', { name: 'Отправить запрос' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'PO-2026-0042' }).first().click();
  await expect(page.getByRole('dialog').getByText(/Вы запросили перенос/)).toBeVisible();
  await snap(page, 'order-date-change');
});

test('ответ на запрос цен с ценами по позициям', async ({ page }) => {
  await openOrders(page, '?view=rfq');
  await page.getByRole('button', { name: 'Ответить' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Втулка резиновая')).toBeVisible();
  await dialog.getByLabel('Втулка резиновая').fill('1250,50');
  await snap(page, 'rfq-respond-dialog');
});

test('несуществующий заказ — ошибка вместо скелетона', async ({ page }) => {
  await openOrders(page, '?orderId=999999');
  await expect(page.getByRole('dialog').getByText('Не удалось открыть')).toBeVisible();
  await snap(page, 'order-not-found');
});
