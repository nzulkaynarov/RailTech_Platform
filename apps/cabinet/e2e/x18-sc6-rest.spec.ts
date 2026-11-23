/**
 * Х-18 · «Новая заявка»: сохранённый черновик предлагается («Продолжить · Начать заново»), а не подставляется молча.
 * Dev-сборка с моком (MSW), 1440 и 390 px, снимок и axe на каждом экране (`snap`).
 *
 *   E2E_SCREENS_DIR=../../../../docs/screens/x18-sc6-rest E2E_SCREENS_SPEC=x18-sc6-rest npx playwright test -c playwright.screens.config.ts
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

async function signIn(page: Page) {
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' })] as const,
  );
}

test('черновик «Новой заявки»: предложение, «Продолжить» и «Начать заново»', async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await signIn(page);
  await page.goto('/requests/new');
  await expect(page.getByRole('heading', { level: 1, name: 'Новая заявка' })).toBeVisible();
  await page.getByLabel('Что нужно').fill('Кабель ВВГнг для цеха, 2 км, до конца месяца');
  await page.waitForTimeout(300);
  await page.goto('/requests');
  await page.goto('/requests/new');
  await expect(page.getByRole('heading', { level: 1, name: 'Новая заявка' })).toBeVisible();

  await expect(page.getByText(/^У вас есть черновик от /)).toBeVisible();
  await expect(page.getByLabel('Что нужно')).toHaveValue('');
  await snap(page, 'draft-offer');

  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page.getByLabel('Что нужно')).toHaveValue('Кабель ВВГнг для цеха, 2 км, до конца месяца');
  await expect(page.getByText(/^У вас есть черновик от /)).toHaveCount(0);
  await snap(page, 'draft-continued');

  await page.goto('/requests');
  await page.goto('/requests/new');
  await page.getByRole('button', { name: 'Начать заново' }).click();
  await expect(page.getByLabel('Что нужно')).toHaveValue('');
  await expect(page.getByText(/^У вас есть черновик от /)).toHaveCount(0);
});
