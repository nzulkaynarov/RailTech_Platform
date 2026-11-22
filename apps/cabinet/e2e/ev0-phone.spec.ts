/**
 * ЕВ-0 · гигиена телефона в Кабинете на dev-сборке с моком (MSW): указатель coarse (Pixel 7), ширины 390 / 768 / 1024 без
 * горизонтальной прокрутки, нижняя навигация и лист «Ещё» — цели от 44 px, лист поднят над экранной клавиатурой.
 * Снимки — в docs/screens/ev0-phone (E2E_SCREENS_DIR), запуск из apps/cabinet:
 *
 *   E2E_SCREENS_SPEC=ev0-phone E2E_SCREENS_DIR=../../../../docs/screens/ev0-phone npx playwright test -c playwright.screens.config.ts
 */
import { devices, expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { SCREENS_DIR } from './helpers/env';
import { snap } from './helpers/shots';

test.use({ ...devices['Pixel 7'], locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

async function signIn(page: Page) {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      // экранная клавиатура: visualViewport подменён, window.__kb(px) «открывает» её
      const vv = Object.assign(new EventTarget(), { height: window.innerHeight, offsetTop: 0 });
      Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
      (window as unknown as { __kb: (h: number) => void }).__kb = (h) => {
        vv.height = window.innerHeight - h;
        vv.dispatchEvent(new Event('resize'));
      };
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' })] as const,
  );
}

const sizes = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
];

for (const size of sizes) {
  test(`${size.width}: главные экраны без горизонтальной прокрутки`, async ({ page }) => {
    await signIn(page);
    await page.setViewportSize(size);
    for (const route of ['/requests', '/quotes', '/documents', '/messages', '/profile']) {
      await page.goto(route);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${route} @${size.width}`).toBeLessThanOrEqual(0);
    }
  });
}

test('390 и 768: снимок и axe экрана заявок', async ({ page }) => {
  await signIn(page);
  await page.goto('/requests');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await snap(page, 'cabinet-requests', { widths: [{ width: 390, height: 844 }, { width: 768, height: 1024 }] });
});

test('390: нижняя навигация и лист «Ещё» — цели от 44 px, лист над клавиатурой', async ({ page }) => {
  await signIn(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/requests');
  const nav = page.getByRole('navigation', { name: 'Основные разделы' });
  await expect(nav).toBeVisible();
  for (const target of await nav.locator('a, button').all()) {
    const box = await target.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
  }
  await page.screenshot({ path: path.join(SCREENS_DIR, 'cabinet-bottom-nav-390.png') });

  await nav.getByRole('button', { name: 'Ещё' }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet).toBeVisible();
  for (const target of await sheet.locator('a, button').all()) {
    expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  }

  await page.evaluate(() => (window as unknown as { __kb: (h: number) => void }).__kb(320));
  await expect(page.locator('html')).toHaveAttribute('data-kb', 'open');
  const box = await sheet.boundingBox();
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(844 - 320 + 1);
  await page.screenshot({ path: path.join(SCREENS_DIR, 'cabinet-sheet-keyboard-390.png') });
});
