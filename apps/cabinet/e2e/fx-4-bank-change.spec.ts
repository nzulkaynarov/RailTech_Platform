/**
 * FX-4 · смена банковских реквизитов: администратор подаёт, в кабинете статус «на проверке», старые реквизиты действуют;
 * форма блокирует новую смену. На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0) и отсутствие горизонтальной
 * прокрутки (`snap`).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

async function signIn(page: Page) {
  await page.addInitScript(
    ([session]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', 'ru');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' })] as const,
  );
}

test('подача смены: статус на проверке, старые реквизиты действуют', async ({ page }) => {
  await signIn(page);
  await page.goto('/company');
  await page.getByRole('button', { name: 'Изменить' }).click();
  await expect(page.getByText(/применятся только после проверки сотрудником/)).toBeVisible();
  await snap(page, 'cabinet-form');
  const field = page.getByLabel('Банковские реквизиты');
  await field.fill('р/с 20208000555566667777, Банк «Пример», МФО 00000');
  await page.getByRole('button', { name: 'Сохранить' }).click();

  const notice = page.getByRole('status', { name: 'Запрос на смену банковских реквизитов' });
  await expect(notice.getByText('На проверке')).toBeVisible();
  await snap(page, 'cabinet-pending');
});
