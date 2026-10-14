import { test, expect, Page, APIRequestContext } from '@playwright/test';
import { createHmac } from 'crypto';

/**
 * Browser E2E for the 2FA login flow + Settings Hub, run against the local stack.
 *
 * The 2FA-login test is the regression net for the 2026-07-12 prod-breaker: App.tsx
 * gated the whole app on the auth store's `isLoading`, so login() unmounted LoginPage
 * mid-request and wiped the local `twoFactorRequired`/`tempToken` state the
 * 2fa_required response had just set — the 6-digit code form NEVER appeared and no
 * 2FA-enabled user could log in. This spec asserts the code form shows and a valid
 * TOTP completes the login.
 *
 * SELF-CONTAINED: beforeAll enables 2FA on the seller test user via the API (fixed
 * flow, computed TOTP) and afterAll disables it, so the suite leaves no state behind.
 * Seed the local users first (`make seed`, default password Demo1234!). Local-only —
 * the seeded users don't exist on prod.
 *
 * Run: cd frontend && npx playwright test e2e/2fa-and-settings.spec.ts
 */

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';
const IS_LOCAL_STACK = /localhost|127\.0\.0\.1/.test(BASE_URL);
const API = process.env.E2E_API_URL || (IS_LOCAL_STACK ? 'http://localhost:8000/api/v1' : `${BASE_URL}/api/v1`);
const SEED_PW = process.env.E2E_SEED_PASSWORD || 'Demo1234!';
const SELLER = { email: process.env.E2E_SELLER_EMAIL || 'seller.local@erp.localhost', password: SEED_PW };
const BUYER = { email: process.env.E2E_BUYER_EMAIL || 'buyer.local@erp.localhost', password: SEED_PW };
const RAW_KEY = /\b(common|dashboardpage|settings|profile|shell|auth)\.[a-z]/;

// RFC 6238 TOTP (SHA1, 6 digits, 30s) — must match backend pyotp.
function totp(secret: string, atMs = Date.now()): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of secret.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  const key = Buffer.from(bytes);
  const counter = Math.floor(atMs / 1000 / 30);
  const msg = Buffer.alloc(8);
  msg.writeBigInt64BE(BigInt(counter));
  const hmac = createHmac('sha1', key).update(msg).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const code = ((hmac[offset] & 0x7f) << 24) | (hmac[offset + 1] << 16) | (hmac[offset + 2] << 8) | hmac[offset + 3];
  return (code % 1e6).toString().padStart(6, '0');
}

async function apiLoginAccess(request: APIRequestContext, creds: { email: string; password: string }): Promise<string> {
  const res = await request.post(`${API}/auth/token/`, { data: creds });
  const body = await res.json();
  if (body.access) return body.access;
  // Already 2FA-enabled (a prior run left it on) — recover via the 2FA login step is
  // impossible without the secret; fail loudly so the operator reseeds.
  throw new Error(`Expected password-only login for ${creds.email}, got ${JSON.stringify(body)} — reseed the stack.`);
}

test.describe('2FA login', () => {
  test.describe.configure({ mode: 'serial' });
  test.skip(!IS_LOCAL_STACK, 'Needs seeded local users + backend API — not runnable against prod');

  let secret = '';

  test.beforeAll(async ({ request }) => {
    const access = await apiLoginAccess(request, SELLER);
    const auth = { Authorization: `Bearer ${access}` };
    const setup = await request.post(`${API}/auth/2fa/setup/`, { headers: auth });
    expect(setup.ok(), 'setup2FA failed').toBeTruthy();
    secret = (await setup.json()).secret;
    const verify = await request.post(`${API}/auth/2fa/verify/`, {
      headers: auth,
      data: { secret, code: totp(secret), current_password: SELLER.password },
    });
    expect(verify.ok(), `verify2FA failed: ${await verify.text()}`).toBeTruthy();
  });

  test.afterAll(async ({ request }) => {
    if (!secret) return;
    // Log in through the 2FA step to get an access token, then disable 2FA (cleanup).
    const tokenRes = await request.post(`${API}/auth/token/`, { data: SELLER });
    const { temp_token } = await tokenRes.json();
    const loginRes = await request.post(`${API}/auth/login/2fa/`, { data: { temp_token, code: totp(secret) } });
    const access = (await loginRes.json()).access;
    await request.post(`${API}/auth/2fa/disable/`, {
      headers: { Authorization: `Bearer ${access}` },
      data: { code: totp(secret), current_password: SELLER.password },
    });
  });

  // THE regression: before the App.tsx fix, this input never appeared.
  test('code-entry form appears after the password step', async ({ page }) => {
    await page.goto('/');
    await page.locator('input[type="email"]').first().fill(SELLER.email);
    await page.locator('input[type="password"]').first().fill(SELLER.password);
    await page.locator('button[type="submit"]').first().click();
    await expect(
      page.locator('input[maxlength="6"]'),
      'the 6-digit 2FA code field must appear after password (regression: App unmounted LoginPage)'
    ).toBeVisible({ timeout: 15_000 });
    // and it must be the 2FA screen, not a stale login form
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).not.toMatch(RAW_KEY);
  });

  test('a valid TOTP completes the login into the app', async ({ page }) => {
    await page.goto('/');
    await page.locator('input[type="email"]').first().fill(SELLER.email);
    await page.locator('input[type="password"]').first().fill(SELLER.password);
    await page.locator('button[type="submit"]').first().click();
    const code = page.locator('input[maxlength="6"]');
    await expect(code).toBeVisible({ timeout: 15_000 });
    await code.fill(totp(secret));
    await page.locator('button[type="submit"]').first().click();
    // Login form gone → we're in the authenticated shell.
    await expect(page.locator('input[maxlength="6"]')).toHaveCount(0, { timeout: 20_000 });
    await expect(page.locator('input[type="password"]')).toHaveCount(0, { timeout: 20_000 });
  });
});

test.describe('Settings Hub', () => {
  test.skip(!IS_LOCAL_STACK, 'Needs seeded local users — not runnable against prod');

  async function login(page: Page, creds: { email: string; password: string }) {
    await page.goto('/');
    await page.locator('input[type="email"]').first().fill(creds.email);
    await page.locator('input[type="password"]').first().fill(creds.password);
    await page.locator('button[type="submit"]').first().click();
    await expect(page.locator('input[type="email"]')).toHaveCount(0, { timeout: 20_000 });
  }

  async function openSection(page: Page, key: string) {
    await page.evaluate((section) => {
      history.replaceState({}, '', `/?section=${section}`);
      window.location.hash = 'settings';
    }, key);
  }

  test('buyer sees profile + security sections, no raw i18n keys', async ({ page }) => {
    await login(page, BUYER);
    for (const section of ['profile', 'security']) {
      await openSection(page, section);
      await expect(page.locator('#root')).not.toBeEmpty();
      const body = (await page.locator('body').innerText()).toLowerCase();
      expect(body, `raw i18n key visible in settings/${section}`).not.toMatch(RAW_KEY);
    }
    // Security must render the 2FA control (buyer has 2FA OFF → the enable affordance).
    const securityText = (await page.locator('body').innerText()).toLowerCase();
    expect(securityText).toMatch(/two-factor|двухфактор|2fa/);
  });
});
