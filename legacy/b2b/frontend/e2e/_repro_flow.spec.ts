import { test } from '@playwright/test';
import * as fs from 'fs';
test('repro full open flow', async ({ page }) => {
  const out: any = { steps: [], errors: [] };
  page.on('pageerror', (e) => out.errors.push(String(e)));
  await page.goto('/');
  await page.locator('input[type="email"]').fill('seller.local@railtech.uz');
  await page.locator('input[type="password"]').fill('Test1234!');
  await page.getByRole('button', { name: /войти|sign in|вход/i }).click();
  await page.locator('input[type="password"]').waitFor({ state: 'detached', timeout: 20000 });
  await page.waitForTimeout(1500);
  const trigger = page.locator('button, [role="button"]').filter({ hasText: /^\s*Buyer\s*$/i }).first();
  await trigger.click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(500);
  await page.getByRole('menuitem', { name: /seller|продавец/i }).first().click({ timeout: 4000 }).catch(() => {});
  await page.waitForTimeout(1000);
  // go to the seller CRM deals list
  await page.evaluate(() => { window.location.hash = 'crm-deals'; });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: 'e2e/audit/flow-1-list.png', fullPage: true });
  // capture the rows (title + what they will navigate to is internal) — click the 2nd row
  const rows = page.locator('table tbody tr');
  const rowCount = await rows.count();
  const rowText = await rows.nth(1).innerText().catch(() => '');
  out.steps.push({ rowCount, clickedRowText: rowText.replace(/\n/g, ' | ') });
  await rows.nth(1).click({ timeout: 6000 }).catch(() => out.steps.push('row-click-fail'));
  await page.waitForTimeout(2500);
  out.steps.push({ afterRowClickHash: await page.evaluate(() => location.hash) });
  await page.screenshot({ path: 'e2e/audit/flow-2-detail.png', fullPage: true });
  // on the request detail, click the open-КП / build-quote button
  const openKp = page.getByRole('button', { name: /кп|quote|calculat|расч|открыть|build/i }).first();
  await openKp.click({ timeout: 6000 }).catch(() => out.steps.push('openkp-fail'));
  await page.waitForTimeout(2500);
  out.steps.push({ afterOpenKpHash: await page.evaluate(() => location.hash) });
  const kpTxt = await page.locator('main, body').first().innerText().catch(() => '');
  out.steps.push({ kpHeader: kpTxt.split('\n').filter(l=>l.trim()).slice(6, 12) });
  await page.screenshot({ path: 'e2e/audit/flow-3-kp.png', fullPage: true });
  fs.writeFileSync('e2e/audit/flow.json', JSON.stringify(out, null, 2));
  console.log('FLOW done');
});
