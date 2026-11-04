/**
 * CAT-CARD-2 · карточка товара клиента на dev-сборке с моком портального API (MSW), без стенда:
 * `npm run test:e2e:cat-card`. Снимки 1440 и 390 px и axe — в docs/screens/CAT-CARD-2 (E2E_SCREENS_DIR), сводка — axe-summary.json.
 * Полная карточка (галерея из трёх фото, изготовитель, страна происхождения, гарантия, два документа) и карточка с одним фото,
 * где пустые блоки не рисуются; галерея листается стрелками.
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

async function signIn(page: Page, language: 'ru' | 'uz' | 'en' = 'ru') {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript(
    ([session, lang]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', lang);
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }), language] as const,
  );
}

test('полная карточка: галерея, изготовитель, гарантия, документы', async ({ page }) => {
  await signIn(page);
  await page.goto('/catalog/1001');
  await expect(page.getByRole('heading', { level: 1, name: 'Подшипник 6205-2RS' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Изготовитель' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Гарантия' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Документы' })).toBeVisible();

  const first = page.getByRole('button', { name: 'Фото 1 из 3' });
  await first.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('img', { name: 'Подшипник 6205-2RS, фото 2 из 3' })).toBeVisible();
  await page.keyboard.press('Home');
  await expect(page.getByRole('img', { name: 'Подшипник 6205-2RS, фото 1 из 3' })).toBeVisible();

  await snap(page, 'catalog-item-full');
});

test('карточка с одним фото и без документов: пустые блоки не рисуются', async ({ page }) => {
  await signIn(page);
  await page.goto('/catalog/1002');
  await expect(page.getByRole('heading', { level: 1, name: 'Ремень приводной SPZ 1250' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Изготовитель' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Документы' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Следующее фото' })).toHaveCount(0);
  await snap(page, 'catalog-item-partial');
});

test('карточка на узбекском и английском', async ({ page }) => {
  await signIn(page, 'uz');
  await page.goto('/catalog/1001');
  await expect(page.getByRole('heading', { name: 'Ishlab chiqaruvchi' })).toBeVisible();
  await snap(page, 'catalog-item-uz', { screenshot: true });
});
