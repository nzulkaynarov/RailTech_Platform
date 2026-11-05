/**
 * NOTIFY-2 · колокольчик кабинета на dev-сборке с моком портального API: бейдж непрочитанного в шапке, лента в шторке
 * справа (без ухода со страницы), «Прочитать все», переход в объект с выделенной строкой (`?focus=`), пустая лента. На
 * каждом экране — 1440 и 390 px, снимок, axe (serious/critical = 0) и отсутствие горизонтальной прокрутки (`snap`).
 * «Сегодня» — день фикстур мока (2026-10-14).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
});

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

const h1 = (page: Page, name: string) => expect(page.getByRole('heading', { level: 1, name })).toBeVisible();
const bell = (page: Page) => page.getByRole('banner').getByRole('button', { name: 'Уведомления' });

test('шапка: колокольчик с числом непрочитанных', async ({ page }) => {
  await signIn(page);
  await page.goto('/requests');
  await h1(page, 'Запросы');
  await expect(bell(page)).toContainText('3');
  await snap(page, 'bell-badge');
});

test('лента в шторке: объект, действие, время; непрочитанные выделены', async ({ page }) => {
  await signIn(page);
  await page.goto('/requests');
  await h1(page, 'Запросы');
  await bell(page).click();
  const panel = page.getByRole('dialog', { name: 'Уведомления' });
  await expect(panel.getByText('Новое КП KP-2026-0042 ждёт вашего решения')).toBeVisible();
  await snap(page, 'bell-panel');
  await panel.getByRole('button', { name: 'Прочитать все' }).click();
  await expect(panel.getByText('Не прочитано')).toHaveCount(0);
  await snap(page, 'bell-panel-all-read');
});

test('переход из уведомления в объект: строка счёта выделена', async ({ page }) => {
  await signIn(page);
  await page.goto('/requests');
  await h1(page, 'Запросы');
  await bell(page).click();
  await page.getByRole('dialog', { name: 'Уведомления' }).getByText(/Выставлен счёт S-2026-0124/).click();
  await expect(page).toHaveURL(/\/invoices\?focus=603$/);
  await h1(page, 'Счета');
  await expect(page.locator('[aria-current="true"]').first()).toContainText('S-2026-0124');
  await snap(page, 'bell-open-invoice');
});

test('пустая лента — понятное пустое состояние', async ({ page }) => {
  await signIn(page, 'empty');
  await page.goto('/requests');
  await h1(page, 'Запросы');
  await bell(page).click();
  await expect(page.getByRole('dialog', { name: 'Уведомления' }).getByText('Новых уведомлений нет')).toBeVisible();
  await snap(page, 'bell-empty');
});
