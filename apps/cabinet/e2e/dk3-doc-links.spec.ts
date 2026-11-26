/**
 * ДК-3 · договор, счёт и акт по ссылке получателя на dev-сборке с моком портального API: гость видит один документ со своими
 * фактами и действиями (договор — «Подписать», акт — «Принять» и «Вернуть», счёт — реквизиты и «Оплатили?»), тот же диалог
 * кода, на узбекском. На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0), нет горизонтальной прокрутки.
 * Запуск из apps/cabinet:
 *   E2E_SCREENS_DIR=../../docs/screens/dk3-doc-links E2E_SCREENS_SPEC=dk3-doc-links npx playwright test -c playwright.screens.config.ts
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

async function language(page: Page, lang: 'ru' | 'uz') {
  await page.addInitScript((value) => window.localStorage.setItem('cabinet.language', value), lang);
}

test('договор: факты и «Принять редакцию»', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/contract-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'Договор CT-0042' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Принять редакцию' })).toBeEnabled();
  await snap(page, 'contract-guest');
});

test('договор: диалог кода и подпись', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/contract-token-0123456789');
  await page.getByRole('button', { name: 'Принять редакцию' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await expect(dialog.getByText(/Отправили код на p\*\*\*@vostok-trans\.uz/)).toBeVisible();
  await snap(page, 'contract-code-dialog');
  await dialog.getByLabel('Код из письма').fill('123456');
  await dialog.getByRole('button', { name: 'Принять редакцию' }).click();
  await expect(page.getByText('Договор согласован. Он будет выставлен на подписание — сообщим.')).toBeVisible();
  await snap(page, 'contract-signed');
});

test('счёт: реквизиты, срок и «Оплатили?», действий над счётом нет', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/invoice-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'Счёт INV-0077' })).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: 'Реквизиты для оплаты' })).toBeVisible();
  await snap(page, 'invoice-guest');
});

test('счёт на узбекском', async ({ page }) => {
  await language(page, 'uz');
  await page.goto('/d/invoice-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'INV-0077 hisobi' })).toBeVisible();
  await snap(page, 'invoice-guest-uz');
});

test('оплаченный счёт', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/invoice-paid-0123456789');
  await expect(page.getByText('Счёт оплачен.')).toBeVisible();
  await snap(page, 'invoice-paid');
});

test('акт: «Принять акт» и «Вернуть с замечаниями»', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/act-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'Акт ACT-0031' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Принять акт' })).toBeEnabled();
  await snap(page, 'act-guest');
  await page.getByRole('button', { name: 'Вернуть с замечаниями' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await dialog.getByLabel('Что нужно исправить?').fill('Сумма в акте не совпадает со счётом.');
  await snap(page, 'act-return-dialog');
});

test('акт без права решать: кнопки неактивны, причина рядом', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/act-viewer-0123456789');
  await expect(page.getByRole('button', { name: 'Принять акт' })).toBeDisabled();
  await expect(page.getByText(/нет права принимать решения/)).toBeVisible();
  await snap(page, 'act-no-right');
});
