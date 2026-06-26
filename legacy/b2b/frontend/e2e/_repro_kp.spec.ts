import { test } from '@playwright/test';
import * as fs from 'fs';
test('repro seller open different КП', async ({ page }) => {
  const out: any = { steps: [], errors: [] };
  page.on('pageerror', (e) => out.errors.push(String(e)));
  await page.goto('/');
  await page.locator('input[type="email"]').fill('seller.local@railtech.uz');
  await page.locator('input[type="password"]').fill('Test1234!');
  await page.getByRole('button', { name: /войти|sign in|вход/i }).click();
  await page.locator('input[type="password"]').waitFor({ state: 'detached', timeout: 20000 });
  await page.waitForTimeout(1500);
  // switch to Seller context via the sidebar dropdown
  const trigger = page.locator('button, [role="button"]').filter({ hasText: /^\s*Buyer\s*$/i }).first();
  await trigger.click({ timeout: 6000 }).catch(() => out.steps.push('trigger-fail'));
  await page.waitForTimeout(600);
  const sellerOpt = page.getByRole('menuitem', { name: /seller|продавец/i }).first();
  await sellerOpt.click({ timeout: 4000 }).catch(() => out.steps.push('seller-opt-fail'));
  await page.waitForTimeout(1200);
  // open two КП builders directly and capture what renders
  for (const id of [4, 7]) {
    await page.evaluate((d) => { window.location.hash = `deal-quote/${d}`; }, id);
    await page.waitForTimeout(2500);
    const txt = await page.locator('main, body').first().innerText().catch(() => '');
    const header = (txt.match(/#\s*\d+\s*[-–]\s*v?\d+/) || [''])[0];
    const firstLines = txt.split('\n').filter((l) => l.trim()).slice(0, 6);
    out.steps.push({ navTo: `deal-quote/${id}`, header, firstLines, hash: await page.evaluate(() => location.hash) });
    await page.screenshot({ path: `e2e/audit/repro-${id}.png`, fullPage: true });
  }
  fs.writeFileSync('e2e/audit/repro.json', JSON.stringify(out, null, 2));
  console.log('REPRO done');
});
