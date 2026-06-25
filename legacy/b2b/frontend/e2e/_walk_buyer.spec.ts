import { test } from '@playwright/test';
import * as fs from 'fs';
test('buyer journey walkthrough', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  fs.mkdirSync('e2e/audit', { recursive: true });
  const shot = async (n: string) => { await page.screenshot({ path: `e2e/audit/buyer-${n}.png`, fullPage: true }); };
  await page.goto('/');
  await page.locator('input[type="email"]').fill('buyer.local@railtech.uz');
  await page.locator('input[type="password"]').fill('Test1234!');
  await page.getByRole('button', { name: /войти|sign in|вход/i }).click();
  await page.locator('input[type="password"]').waitFor({ state: 'detached', timeout: 20000 });
  await page.waitForTimeout(1500);
  await shot('1-dashboard');
  await page.evaluate(() => { window.location.hash = 'catalog'; }); await page.waitForTimeout(2500);
  await shot('2-catalog');
  // try to add first product to cart
  const addBtns = page.getByRole('button', { name: /cart|корзин|add|добав|в корзину/i });
  if (await addBtns.count() > 0) { await addBtns.first().click().catch(()=>{}); await page.waitForTimeout(800); }
  await shot('3-after-add');
  // open cart (look for a cart trigger in header)
  const cartTrigger = page.locator('[aria-label*="cart" i], [aria-label*="корзин" i]').first();
  if (await cartTrigger.count() > 0) { await cartTrigger.click().catch(()=>{}); await page.waitForTimeout(800); }
  await shot('4-cart');
  await page.evaluate(() => { window.location.hash = 'my-requests'; }); await page.waitForTimeout(2000);
  await shot('5-my-requests');
  await page.evaluate(() => { window.location.hash = 'request-detail/20'; }); await page.waitForTimeout(2500);
  await shot('6-request-detail');
  fs.writeFileSync('e2e/audit/walk.json', JSON.stringify({ errors }, null, 2));
  console.log('WALK done errors=' + errors.length);
});
