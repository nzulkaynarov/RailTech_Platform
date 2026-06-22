import { test, expect } from '@playwright/test';

/**
 * Browser E2E for the golden path. The backend equivalent
 * (backend/crm/tests/test_golden_path.py) proves the SERVICE flow; this proves
 * the actual buyer/seller CLICKS work end-to-end in a real browser.
 *
 * Run: cd frontend && E2E_BASE_URL=https://staging.b2b.railtech.uz npm run test:e2e
 *
 * The `smoke` block below is runnable as-is. The full journey is a labelled
 * skeleton — fill the selectors marked TODO against the real UI (they depend on
 * data-testid / role labels we add as we go) and remove the test.skip.
 */

test.describe('smoke', () => {
  test('app loads without crashing or showing raw i18n keys', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#root')).not.toBeEmpty();

    // Raw-key detector: if i18n fails, the UI shows literal keys like
    // "dashboardPage.kpi.clients" or "common.save". Catch the obvious shapes.
    const bodyText = (await page.locator('body').innerText()).toLowerCase();
    const rawKeyPattern = /\b(common|dashboardpage|kycmanager|apierrors|onboarding)\.[a-z]/;
    expect(bodyText, 'visible text contains an untranslated i18n key').not.toMatch(rawKeyPattern);
  });

  test('backend health endpoint is up', async ({ request }) => {
    // The backend (not the SPA nginx) owns /health/. In the docker harness
    // localhost:8000 is socat-forwarded to the host backend; against staging the
    // env URL serves it at the same origin. Allow both.
    const base = process.env.E2E_API_URL || 'http://localhost:8000';
    const res = await request.get(`${base}/health/`);
    expect(res.ok()).toBeTruthy();
  });
});

// ── Full golden path (buyer → seller → КП → contract). Fill selectors, unskip. ──
test.describe('golden path', () => {
  test.skip(true, 'Selector skeleton — fill against the real UI, then enable. See Docs/ops/e2e.md');

  test('buyer single RFQ → seller bid → КП → approve', async ({ page }) => {
    // 1. Buyer logs in
    await page.goto('/');
    // TODO: await page.getByLabel('Email').fill(process.env.E2E_BUYER_EMAIL!);
    // TODO: await page.getByLabel('Password').fill(process.env.E2E_BUYER_PASSWORD!);
    // TODO: await page.getByRole('button', { name: /войти|sign in/i }).click();

    // 2. Buyer creates a deal / RFQ and adds a line item
    // TODO: navigate to deals, create, add item

    // 3. Buyer opens RFQ → stage RFQ_OPEN
    // TODO: assert stage badge text/code

    // 4. (seller session) submit a bid — use a second browser context with seller creds
    // 5. Accept bid → stage CALCULATING
    // 6. Build & send КП → stage QUOTE_SENT, PDF downloads
    // 7. Approve КП → stage CONTRACT_SIGNED
    expect(true).toBeTruthy();
  });
});
