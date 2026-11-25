/**
 * ДК-1, ДК-2 · документ по ссылке из письма на dev-сборке с моком портального API: гость видит один документ (ru, uz),
 * диалог кода (один на любое действие), первый вход — оферта и политика, результат действия, контакт без права решать,
 * отозванная и просроченная ссылка. На каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0), нет горизонтальной
 * прокрутки. Запуск из apps/cabinet:
 *   E2E_SCREENS_DIR=../../../../docs/screens/dk12-doc-link E2E_SCREENS_SPEC=dk12-doc-link npx playwright test -c playwright.screens.config.ts
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const LIVE = '/d/live-token-0123456789';

async function language(page: Page, lang: 'ru' | 'uz') {
  await page.addInitScript((value) => window.localStorage.setItem('cabinet.language', value), lang);
}

test('гость по ссылке: один документ, никаких разделов кабинета', async ({ page }) => {
  await language(page, 'ru');
  await page.goto(LIVE);
  await expect(page.getByRole('heading', { level: 1, name: 'Коммерческое предложение QT-0118' })).toBeVisible();
  await expect(page.getByRole('navigation')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Принять предложение' })).toBeEnabled();
  await snap(page, 'guest-document');
});

test('гость по ссылке на узбекском', async ({ page }) => {
  await language(page, 'uz');
  await page.goto(LIVE);
  await expect(page.getByRole('heading', { level: 1, name: 'QT-0118 taklifi' })).toBeVisible();
  await snap(page, 'guest-document-uz');
});

test('«Принять»: диалог кода, верный код — вход и принятие без повторного нажатия', async ({ page }) => {
  await language(page, 'ru');
  await page.goto(LIVE);
  await page.getByRole('button', { name: 'Принять предложение' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await expect(dialog.getByText(/Отправили код на p\*\*\*@vostok-trans\.uz/)).toBeVisible();
  await snap(page, 'code-dialog');

  await dialog.getByLabel('Код из письма').fill('000000');
  await dialog.getByRole('button', { name: 'Принять предложение' }).click();
  await expect(dialog.getByText(/Код неверный или устарел/)).toBeVisible();
  await snap(page, 'code-dialog-wrong');

  await dialog.getByLabel('Код из письма').fill('123456');
  await dialog.getByRole('button', { name: 'Принять предложение' }).click();
  await expect(page.getByText('Предложение принято. Договор появится в вашем кабинете.')).toBeVisible();
  await snap(page, 'accepted');
});

test('ДК-4: код ушёл и в Telegram — диалог говорит, куда', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/tg-token-0123456789');
  await page.getByRole('button', { name: 'Принять предложение' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await expect(dialog.getByText(/Отправили код на p\*\*\*@vostok-trans\.uz и в Telegram/)).toBeVisible();
  await expect(dialog.getByText('Не пришло на почту? Код есть и в Telegram.')).toBeVisible();
  await snap(page, 'code-dialog-telegram');
});

test('«Вернуть с замечаниями»: текст и код в одном диалоге', async ({ page }) => {
  await language(page, 'ru');
  await page.goto(LIVE);
  await page.getByRole('button', { name: 'Вернуть с замечаниями' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await expect(dialog.getByLabel('Что нужно исправить?')).toBeVisible();
  await dialog.getByLabel('Что нужно исправить?').fill('Срок поставки велик, нужна скидка за объём.');
  await snap(page, 'code-dialog-remarks');
});

test('первый вход: после кода — оферта и политика, потом действие', async ({ page }) => {
  await language(page, 'ru');
  await page.addInitScript(() => window.sessionStorage.setItem('cabinet.mock.legal', JSON.stringify({ published: true, accepted: false })));
  await page.goto(LIVE);
  await page.getByRole('button', { name: 'Принять предложение' }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердите, что это вы' });
  await expect(dialog.getByText(/примете условия использования и политику/)).toBeVisible();
  await snap(page, 'code-dialog-first-entry', { screenshot: false });
  await dialog.getByLabel('Код из письма').fill('123456');
  await dialog.getByRole('button', { name: 'Принять предложение' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Условия работы в кабинете' })).toBeVisible();
  await snap(page, 'first-entry-legal');
  await page.getByRole('button', { name: 'Принимаю', exact: true }).click();
  await expect(page.getByText('Предложение принято. Договор появится в вашем кабинете.')).toBeVisible();
});

test('контакт без права решать: кнопки неактивны, причина рядом', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/viewer-token-0123456789');
  await expect(page.getByRole('button', { name: 'Принять предложение' })).toBeDisabled();
  await expect(page.getByText(/нет права принимать решения/)).toBeVisible();
  await snap(page, 'no-right');
});

test('вошедший контакт: код не нужен', async ({ page }) => {
  await language(page, 'ru');
  await page.addInitScript(() =>
    window.sessionStorage.setItem('cabinet.mock.session', JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' })),
  );
  await page.goto(LIVE);
  await expect(page.getByText(/код не нужен/)).toBeVisible();
  await page.getByRole('button', { name: 'Принять предложение' }).click();
  const dialog = page.getByRole('dialog', { name: 'Принять предложение?' });
  await expect(dialog.getByLabel('Код из письма')).toHaveCount(0);
  await snap(page, 'member-confirm');
});

test('ссылка отозвана или просрочена: только причина', async ({ page }) => {
  await language(page, 'ru');
  await page.goto('/d/revoked-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'Ссылка отозвана' })).toBeVisible();
  await expect(page.getByText('ООО «РейлТех»')).toHaveCount(0);
  await snap(page, 'link-revoked');
  await page.goto('/d/expired-token-0123456789');
  await expect(page.getByRole('heading', { level: 1, name: 'Срок ссылки истёк' })).toBeVisible();
  await snap(page, 'link-expired');
});
