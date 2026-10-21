import { randomBytes } from 'node:crypto';
import { expect, type Page } from '@playwright/test';
import { CRM_URL, crmAdmin } from './env';

/** Вход администратора CRM FIX-51 (пароль — из окружения). */
export async function crmLogin(page: Page): Promise<void> {
  const { email, password } = crmAdmin();
  await page.goto(`${CRM_URL}/login`);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/(inbox|leads|dashboard)/);
}

/** Id лида по тексту потребности (лид из формы «Я новый клиент» несёт метку прогона в тексте). */
export async function findLeadId(page: Page, needle: string): Promise<number> {
  await page.goto(`${CRM_URL}/leads`);
  const row = page.getByRole('row').filter({ hasText: needle }).first();
  await expect(row).toBeVisible();
  await row.getByRole('link').first().click();
  await expect(page).toHaveURL(/\/leads\/\d+/);
  return Number(new URL(page.url()).pathname.split('/').pop());
}

/** «Забрать» лида и «Передать в бэк-офис» (компания и заявка в ERP, приглашение в Cabinet уходит из ERP). */
export async function takeAndHandOff(page: Page, leadId: number, companyName: string): Promise<void> {
  await page.goto(`${CRM_URL}/leads/${leadId}`);
  const actions = page.getByRole('group', { name: /Действия/ });
  await actions.getByRole('button', { name: 'Забрать' }).click();
  const handoff = actions.getByRole('button', { name: 'Передать в бэк-офис' });
  await expect(handoff).toBeVisible();
  await handoff.click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('или новый клиент').fill(companyName);
  await dialog.getByRole('button', { name: 'Передать в бэк-офис' }).click();
  await expect(page.getByText('Клиент создан')).toBeVisible();
}

/** Действие карточки лида: кнопка в ряду «Действия» или пункт меню «Ещё». */
export async function leadAction(page: Page, name: string): Promise<void> {
  const actions = page.getByRole('group', { name: /Действия/ });
  await expect(actions).toBeVisible();
  const direct = actions.getByRole('button', { name, exact: true });
  if (await direct.count()) {
    await direct.click();
    return;
  }
  await actions.getByRole('button', { name: /Ещё/ }).click();
  await page.getByRole('menuitem', { name }).click();
}

/**
 * Сброс пароля сотрудника из «Пользователи» (администратор): возвращает временный пароль (показывается один раз) —
 * только в память процесса, дальше он идёт в форму входа. Прежние сессии сотрудника завершаются.
 */
export async function resetStaffPassword(adminPage: Page, name: string): Promise<string> {
  await adminPage.goto(`${CRM_URL}/users`);
  await adminPage.getByRole('button', { name: `Действия с пользователем ${name}` }).click();
  await adminPage.getByRole('menuitem', { name: 'Сбросить пароль', exact: true }).click();
  await adminPage.getByRole('dialog').getByRole('button', { name: 'Сбросить' }).click();
  const temporary = adminPage.getByRole('dialog').filter({ hasText: 'Временный пароль' }).locator('code').first();
  await expect(temporary).toBeVisible();
  const password = (await temporary.innerText()).trim();
  await adminPage.getByRole('dialog').getByRole('button', { name: 'Готово' }).click();
  return password;
}

/** Вход сотрудника CRM по e-mail и паролю; временный пароль после сброса CRM просит сменить — новый случайный, только в памяти процесса. */
export async function crmLoginAs(page: Page, email: string, password: string): Promise<void> {
  await page.goto(`${CRM_URL}/login`);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/(inbox|leads|dashboard|profile|change-password)/);
  if (page.url().includes('/change-password')) {
    const fresh = `Fx${randomBytes(8).toString('hex')}9`;
    await page.getByLabel('Текущий пароль').fill(password);
    await page.getByLabel('Новый пароль').fill(fresh);
    await page.getByLabel('Повторите пароль').fill(fresh);
    await page.getByRole('button', { name: 'Сохранить' }).click();
    await expect(page).toHaveURL(/\/(inbox|leads|dashboard|profile)/);
  }
}

/** Клиент CRM с ИНН («Клиенты» → «Новый клиент»). */
export async function createClient(page: Page, name: string, inn: string): Promise<void> {
  await page.goto(`${CRM_URL}/clients`);
  await page.getByRole('button', { name: 'Новый клиент' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название').fill(name);
  await dialog.getByLabel('ИНН').fill(inn);
  await dialog.getByRole('button', { name: 'Создать клиента' }).click();
  await expect(page).toHaveURL(/\/clients\/\d+/);
}

/** Лид «Звонок» с согласием, отмеченным менеджером; открывается его карточка. */
export async function createConsentedLead(page: Page, name: string, phone: string, need: string): Promise<void> {
  await page.goto(`${CRM_URL}/inbox`);
  await page.getByRole('button', { name: 'Новый лид' }).click();
  const form = page.getByRole('dialog');
  await form.getByLabel('Имя').fill(name);
  await form.getByLabel('Телефон').fill(phone);
  await form.getByLabel('Что нужно').fill(need);
  await form.getByRole('button', { name: 'Создать' }).click();
  await expect(page).toHaveURL(/\/leads\/\d+/);
  await leadAction(page, 'Согласие получено');
  await page.getByRole('dialog').getByRole('button', { name: 'Согласие получено' }).click();
  await expect(page.getByText('Согласие отмечено')).toBeVisible();
  await expect(page.getByRole('group', { name: /Действия/ }).getByRole('button', { name: 'Передать в бэк-офис' })).toBeVisible();
}

/** «Передать в бэк-офис» на существующего клиента CRM (не «или новый клиент»). */
export async function handoffToExistingClient(page: Page, clientName: string): Promise<void> {
  await leadAction(page, 'Передать в бэк-офис');
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: 'Существующий клиент' }).fill(clientName);
  await page.getByTitle(clientName).click();
  await dialog.getByRole('button', { name: 'Передать в бэк-офис' }).click();
}
