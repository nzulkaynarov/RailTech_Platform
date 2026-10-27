/**
 * D1-9 · публичные экраны кабинета: вход, «Проверьте почту», «Я новый клиент» (форма и «Спасибо»).
 *
 * Идёт по dev-сборке с моком портального API и формы CRM (MSW), без стенда: `npm run test:e2e:public`.
 * Что проверяет: нейтральный текст безопасности после ввода любого адреса, ссылка «Вы новый клиент? Оставьте запрос»
 * ведёт к форме, у «Войти через Telegram» подпись «откроется бот, вход по приглашению», после отправки запроса —
 * «Спасибо» с обещанием подтверждения на e-mail. На каждом экране — снимки 1440 и 390 px, axe (serious/critical = 0)
 * и отсутствие горизонтальной прокрутки (`snap`, как в гейте M2).
 */
import { expect, test } from '@playwright/test';
import { snap } from './helpers/shots';

test.describe('публичные экраны кабинета', () => {
  test('вход: подпись у Telegram, письмо «Проверьте почту», путь нового клиента', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { level: 1, name: 'Вход в кабинет' })).toBeVisible();
    await expect(page.getByText('Откроется бот, вход по приглашению.')).toBeVisible();
    await snap(page, '01-login');

    await page.getByLabel('E-mail').fill('neznakomets@example.com');
    await page.getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Проверьте почту' })).toBeVisible();
    await expect(
      page.getByText('Если адрес neznakomets@example.com зарегистрирован, мы отправили ссылку для входа.'),
    ).toBeVisible();
    await snap(page, '02-login-sent');

    await page.getByRole('link', { name: 'Вы новый клиент? Оставьте запрос' }).click();
    await expect(page).toHaveURL(/\/new-client$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Я новый клиент' })).toBeVisible();
    await snap(page, '03-new-client');
  });

  test('«Я новый клиент»: заявка отправлена — «Спасибо» и подтверждение на e-mail', async ({ page }) => {
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
    await expect(page.getByText('Мы отправим подтверждение запроса на alisher@example.com.')).toBeVisible();
    await snap(page, '05-new-client-sent');
  });

  test('uz и en: «Проверьте почту» и ссылка нового клиента переведены', async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'uz'));
    await page.goto('/login/sent');
    await expect(page.getByRole('heading', { level: 1, name: 'Pochtangizni tekshiring' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Yangi mijozmisiz? Soʻrov qoldiring' })).toHaveAttribute('href', '/new-client');
    await snap(page, '06-login-sent-uz');

    await page.addInitScript(() => window.localStorage.setItem('cabinet.language', 'en'));
    await page.goto('/login');
    await expect(page.getByText('The bot will open; sign-in is by invitation.')).toBeVisible();
    await snap(page, '07-login-en');
  });
});
