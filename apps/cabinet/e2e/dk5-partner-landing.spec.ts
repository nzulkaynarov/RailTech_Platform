/**
 * ДК-5 · партнёр, который только продаёт нам: после входа — «Заказы на поставку», раздела покупателя («Заявки», «Каталог») в меню
 * нет. 1440 и 390 px, снимок, axe, без
 * горизонтальной прокрутки (`snap`).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-11-10T12:00:00+05:00');
const SELLER = { roles: ['partner'], modules: ['my_products', 'letters', 'messages', 'profile'] };

async function signIn(page: Page, role: 'actor' | 'viewer') {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role, auth_method: 'magic_link', dataset: 'demo', access: SELLER })] as const,
  );
}

test('новый партнёр: вход ведёт в «Заказы на поставку», раздела покупателя нет', async ({ page }) => {
  await signIn(page, 'actor');
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Заказы на поставку' })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe('/partner/orders');
  const side = page.getByRole('navigation', { name: 'Разделы кабинета' });
  if (await side.isVisible()) {
    await expect(side.getByRole('link', { name: /^Каталог/ })).toHaveCount(0);
    await expect(side.getByRole('link', { name: /^Заявки/ })).toHaveCount(0);
  }
  await snap(page, 'partner-seller-landing');
});
