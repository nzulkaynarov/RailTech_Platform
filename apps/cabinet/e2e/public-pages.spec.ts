/**
 * D1-9 · публичные экраны кабинета: вход, «Мы отправили письмо», «Я новый клиент» (форма и «Спасибо»).
 *
 * Идёт по dev-сборке с моком портального API и формы CRM (MSW), без стенда: `npm run test:e2e:public`.
 * Что проверяет: нейтральный текст безопасности после ввода любого адреса, ссылка «Вы новый клиент? Оставьте запрос»
 * ведёт к форме, у «Войти через Telegram» подпись «откроется бот, вход по приглашению», после отправки запроса —
 * «Спасибо» (подтверждение клиенту шлёт CRM по любому каналу существующей карточки, поэтому текст нейтральный). На каждом экране — снимки 1440 и 390 px, axe (serious/critical = 0)
 * и отсутствие горизонтальной прокрутки (`snap`, как в гейте M2).
 */
import { expect, test } from '@playwright/test';
import { snap } from './helpers/shots';

test.describe('публичные экраны кабинета', () => {
  test('вход: подпись у Telegram, письмо «Мы отправили письмо», путь нового клиента', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { level: 1, name: 'Вход в кабинет' })).toBeVisible();
    await expect(page.getByText('Откроется бот, вход по приглашению.')).toBeVisible();
    await snap(page, '01-login');

    await page.getByLabel('E-mail').fill('neznakomets@example.com');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Мы отправили письмо' })).toBeVisible();
    await expect(
      page.getByText('Если адрес neznakomets@example.com зарегистрирован, в письме — код и ссылка для входа. Они действуют 60 минут.'),
    ).toBeVisible();
    await snap(page, '02-login-sent');

    await page.getByRole('link', { name: 'Вы новый клиент? Оставьте запрос' }).click();
    await expect(page).toHaveURL(/\/new-client$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Я новый клиент' })).toBeVisible();
    await snap(page, '03-new-client');
  });

  test('«Я новый клиент»: заявка отправлена — «Спасибо»', async ({ page }) => {
    await page.goto('/new-client');
    await expect(page.getByRole('button', { name: 'Отправить запрос' })).toBeEnabled();
    await page.getByLabel('Как к вам обращаться').fill('Алишер');
    await page.getByLabel('Компания (необязательно)').fill('ООО Рельс Демо');
    await page.getByLabel('Телефон').fill('+998 90 123 45 67');
    await page.getByLabel('E-mail').fill('alisher@example.com');
    await page.getByLabel('Что нужно').fill('Нужен расчёт поставки рельсов Р65, 50 тонн');
    await page.getByRole('checkbox', { name: /Согласен/ }).check();
    await snap(page, '04-new-client-filled');

    await page.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Спасибо! Запрос отправлен' })).toBeVisible();
    await snap(page, '05-new-client-sent');
  });

  test('uz и en: «Мы отправили письмо» и ссылка нового клиента переведены', async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'uz'));
    await page.goto('/login/code');
    await expect(page.getByRole('heading', { level: 1, name: 'Kod bilan kirish' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Yangi mijozmisiz? Soʻrov qoldiring' })).toHaveAttribute('href', '/new-client');
    await snap(page, '06-login-sent-uz');

    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'en'));
    await page.goto('/login');
    await expect(page.getByText('The bot will open; sign-in is by invitation.')).toBeVisible();
    await snap(page, '07-login-en');
  });

  test('B-MAIL-1: «Мы отправили письмо» — код из письма, «Отправить ещё раз» через 60 с, Telegram, вход по коду', async ({
    page,
  }) => {
    await page.clock.install();
    await page.goto('/login');
    await page.getByLabel('E-mail').fill('a.karimov@toshlog.uz');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Мы отправили письмо' })).toBeVisible();
    await expect(page.getByText('Письмо может идти несколько минут. Проверьте папку «Спам».')).toBeVisible();
    await expect(page.getByRole('button', { name: /Отправить ещё раз через \d+ с/ })).toBeDisabled();
    await expect(page.getByRole('link', { name: 'Войти через Telegram' })).toBeVisible();
    await expect(page.getByLabel('Код из письма')).toHaveAttribute('autocomplete', 'one-time-code');
    await snap(page, 'mail1-01-code-sent');

    await page.getByLabel('Код из письма').fill('000000');
    await page.getByRole('form', { name: 'Вход по коду из письма' }).getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByText('Код неверный или устарел. Проверьте письмо или отправьте новый код.')).toBeVisible();
    await snap(page, 'mail1-02-code-invalid');

    await page.getByLabel('Код из письма').fill('111111');
    await page.getByRole('form', { name: 'Вход по коду из письма' }).getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByText(/Пять неверных кодов подряд/)).toBeVisible();
    await page.clock.runFor(61_000);
    await expect(page.getByRole('button', { name: 'Отправить ещё раз', exact: true })).toBeEnabled();
    await snap(page, 'mail1-03-code-locked-resend');

    await page.getByRole('button', { name: 'Отправить ещё раз', exact: true }).click();
    await expect(page.getByText('Отправили новое письмо. Код из прежнего больше не действует.')).toBeVisible();
    await page.getByLabel('Код из письма').fill('429173');
    await page.getByRole('form', { name: 'Вход по коду из письма' }).getByRole('button', { name: 'Войти' }).click();
    await expect(page).toHaveURL(/\/requests$/);
  });

  test('B-MAIL-1: «Вход по коду» из приглашения — uz и en', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Уже есть код из письма? Войти по коду' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Вход по коду' })).toBeVisible();
    await snap(page, 'mail1-04-code-entry');
    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'uz'));
    await page.goto('/login/code');
    await expect(page.getByRole('heading', { level: 1, name: 'Kod bilan kirish' })).toBeVisible();
    await snap(page, 'mail1-05-code-entry-uz');
    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'en'));
    await page.goto('/login/code');
    await expect(page.getByRole('heading', { level: 1, name: 'Log in with a code' })).toBeVisible();
    await snap(page, 'mail1-06-code-entry-en');
  });
});
