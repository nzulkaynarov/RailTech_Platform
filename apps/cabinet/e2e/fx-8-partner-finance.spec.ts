/**
 * FX-8 · оборот и оценка партнёра: подписи без слова «взаиморасчёты» и пустое состояние «Нет данных». 1440 и 390 px, снимок,
 * axe (serious/critical = 0) и отсутствие горизонтальной прокрутки (`snap`).
 */
import { expect, test } from '@playwright/test';
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

test('оборот и оценка', async ({ page }) => {
  await page.goto('/partner/orders?view=finance');
  await expect(page.getByText('Оборот по заказам')).toBeVisible();
  await expect(page.getByText('Разбивка по заказам')).toBeVisible();
  await snap(page, 'finance');
});

test('нечем измерить — «Нет данных»', async ({ page }) => {
  await page.addInitScript(
    ([session]) => window.sessionStorage.setItem('cabinet.mock.session', session),
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'empty', access: PARTNER })] as const,
  );
  await page.goto('/partner/orders?view=finance');
  await expect(page.getByText('Нет данных').first()).toBeVisible();
  await snap(page, 'finance-empty');
});
