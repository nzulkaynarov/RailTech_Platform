/**
 * ДВ-5 · оферта и политика Кабинета на dev-сборке с моком портального API: экран принятия (русский и узбекский, длинный
 * текст прокручивается внутри), экран входа со ссылкой на политику и публичная политика. На каждом экране — 1440 и 390 px,
 * снимок, axe (serious/critical = 0), нет горизонтальной прокрутки. Запуск из apps/cabinet:
 *   E2E_SCREENS_DIR=../../../../docs/screens/dv5-offer E2E_SCREENS_SPEC=dv5-legal npx playwright test -c playwright.screens.config.ts
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

async function sessionWithLegal(page: Page, language: 'ru' | 'uz', accepted = false) {
  await page.addInitScript(
    ([session, legal, lang]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.sessionStorage.setItem('cabinet.mock.legal', legal);
      window.localStorage.setItem('cabinet.language', lang);
    },
    [
      JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }),
      JSON.stringify({ published: true, accepted }),
      language,
    ] as const,
  );
}

test('экран принятия: оба документа, «Принимаю» и «Не принимаю»; после принятия — кабинет', async ({ page }) => {
  await sessionWithLegal(page, 'ru');
  await page.goto('/quotes');
  await expect(page.getByRole('heading', { level: 1, name: 'Условия работы в кабинете' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Принимаю', exact: true })).toBeVisible();
  await expect(page.getByRole('tabpanel')).toContainText('Условия использования Кабинета (оферта)');
  await snap(page, 'acceptance-ru');
  await page.getByRole('tab', { name: 'Политика персональных данных' }).click();
  await expect(page.getByRole('tabpanel')).toContainText('Политика обработки персональных данных');
  await snap(page, 'acceptance-ru-privacy', { screenshot: false });

  await page.getByRole('button', { name: 'Принимаю', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Коммерческие предложения' })).toBeVisible();
});

test('экран принятия на узбекском', async ({ page }) => {
  await sessionWithLegal(page, 'uz');
  await page.goto('/quotes');
  await expect(page.getByRole('heading', { level: 1, name: 'Kabinetda işlaş şartlari' })).toBeVisible();
  await snap(page, 'acceptance-uz');
});

test('отказ: выход с объяснением на экране входа', async ({ page }) => {
  await sessionWithLegal(page, 'ru');
  await page.goto('/quotes');
  await page.getByRole('button', { name: 'Не принимаю' }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText(/Вы не приняли условия и политику/)).toBeVisible();
  await snap(page, 'declined-login');
});

test('вход: ссылка на политику стоит, пока политика опубликована; ведёт на её текст', async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem('cabinet.mock.legal', JSON.stringify({ published: true, accepted: false }));
    window.localStorage.setItem('cabinet.language', 'ru');
  });
  await page.goto('/login');
  const link = page.getByRole('link', { name: 'Политика обработки персональных данных' });
  await expect(link).toBeVisible();
  await snap(page, 'login-policy-link');
  await link.click();
  await expect(page.getByRole('heading', { level: 1, name: 'Политика обработки персональных данных в Кабинете' })).toBeVisible();
  await snap(page, 'policy-public');
});
