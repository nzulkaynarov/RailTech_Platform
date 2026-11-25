/**
 * ЕД-4 (волна 24): позиция каталога в строке Cabinet — миниатюра или значок типа и наш артикул. КП, поставки, сделка и каталог
 * на dev-сборке с моком портального API (MSW): `npm run test:e2e:item-thumbs`. Снимки 1512 и 390 px и axe — в
 * docs/screens/ph2-item-thumbs (E2E_SCREENS_DIR).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');
const WIDTHS = [
  { width: 1512, height: 900 },
  { width: 390, height: 844 },
] as const;

async function signIn(page: Page) {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript(
    ([session, lang]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', lang);
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }), 'ru'] as const,
  );
}

const thumb = (page: Page) => page.locator('img[src*="/thumbnail?v="]').first();

test('КП: строки с миниатюрой и артикулом', async ({ page }) => {
  await signIn(page);
  await page.goto('/quotes/301');
  await expect(page.getByRole('heading', { level: 1, name: 'Коммерческое предложение KP-2026-0042' })).toBeVisible();
  await expect(thumb(page)).toBeVisible();
  await snap(page, 'cabinet-quote', { widths: WIDTHS });
});

test('каталог: карточка списка с миниатюрой и артикулом', async ({ page }) => {
  await signIn(page);
  await page.goto('/catalog');
  await expect(page.getByRole('heading', { level: 1, name: 'Каталог' })).toBeVisible();
  await expect(thumb(page)).toBeVisible();
  await snap(page, 'cabinet-catalog', { widths: WIDTHS });
});

test('сделка: поставка с миниатюрой', async ({ page }) => {
  await signIn(page);
  await page.goto('/deals/35');
  await expect(page.getByRole('heading', { level: 1, name: 'Проект ПР-2026-035' })).toBeVisible();
  await expect(thumb(page)).toBeVisible();
  await snap(page, 'cabinet-deal', { widths: WIDTHS });
});
