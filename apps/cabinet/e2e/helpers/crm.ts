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
