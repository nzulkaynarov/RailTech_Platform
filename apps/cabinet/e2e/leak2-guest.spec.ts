/**
 * В-1 · документ по ссылке для адреса, который не контакт компании: гость видит один документ и PDF, без действий, без
 * «Открыть кабинет» и без строки про код — одна нейтральная строка. 1512, 1440 и 390 px, снимок, axe.
 *   E2E_SCREENS_DIR=../../docs/screens/leak2 E2E_SCREENS_SPEC=leak2-guest npx playwright test -c playwright.screens.config.ts
 */
import { expect, test } from '@playwright/test';
import { snap } from './helpers/shots';

test('гость без контакта: документ и PDF, действий нет', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'ru'));
  await page.goto('/d/nocontact-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'КП QT-0118' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Скачать PDF: КП QT-0118' })).toBeEnabled();
  await expect(page.getByText('Чтобы ответить по документу — напишите отправителю')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Принять предложение' })).toHaveCount(0);
  await expect(page.getByText(/Любое действие — после кода/)).toHaveCount(0);
  await snap(page, 'leak2-guest-no-contact', {
    widths: [
      { width: 1512, height: 900 },
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ],
  });
});
