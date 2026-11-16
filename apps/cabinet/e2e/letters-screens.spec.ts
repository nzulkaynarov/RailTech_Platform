/**
 * ЛИД-8 (ADR-0026) · «Письма» кабинета на dev-сборке с моком портального API: наши исходящие с файлом и квитанции о
 * письмах компании, фильтр «Ваши», пустой раздел. На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0) и
 * отсутствие горизонтальной прокрутки (`snap`). Запуск: `E2E_SCREENS_SPEC=letters-screens npx playwright test -c
 * playwright.screens.config.ts`.
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

async function signIn(page: Page, dataset: 'demo' | 'empty' = 'demo') {
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset })] as const,
  );
}

const h1 = (page: Page) => expect(page.getByRole('heading', { level: 1, name: 'Письма' })).toBeVisible();

test('письма: наши с файлом, ваши с номером регистрации и ответом', async ({ page }) => {
  await signIn(page);
  await page.goto('/letters');
  await h1(page);
  await expect(page.getByText('OUT-031/26').first()).toBeVisible();
  await snap(page, 'letters');
  await page.getByRole('button', { name: 'Ваши' }).click();
  await expect(page.getByText('IN-117/26').first()).toBeVisible();
  await snap(page, 'letters-yours');
});

test('пустой раздел — понятное пустое состояние', async ({ page }) => {
  await signIn(page, 'empty');
  await page.goto('/letters');
  await expect(page.getByText('Писем пока нет')).toBeVisible();
  await snap(page, 'letters-empty');
});
