/**
 * План §3f РЕФ-3 · «Осталось N дней» у сроков в Кабинете на dev-сборке с моком портала: срок действия КП (список и карточка),
 * срок оплаты счёта. 1440 и 390 px, снимок, axe и отсутствие горизонтальной прокрутки (`snap`). «Сегодня» — день фикстур.
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-14T12:00:00+05:00'));
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' })] as const,
  );
});

const h1 = (page: Page, name: string | RegExp) => expect(page.getByRole('heading', { level: 1, name })).toBeVisible();

test('КП: срок действия с «осталось»', async ({ page }) => {
  await page.goto('/quotes');
  await h1(page, 'Коммерческие предложения');
  await expect(page.getByText(/остал(ся|ось) \d+ (день|дня|дней)|сегодня последний день/).first()).toBeVisible();
  await snap(page, 'quotes-time-left');
});

test('счета: срок оплаты с «осталось»', async ({ page }) => {
  await page.goto('/invoices');
  await h1(page, 'Счета');
  await snap(page, 'invoices-time-left');
});
