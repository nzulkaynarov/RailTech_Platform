import { test, expect } from '@playwright/test';

/**
 * Auth-flow regression net for the registration → setup-password journey that
 * broke three times on 2026-06-08 (email link, public-route redirect, dropped
 * phone). NON-INVASIVE: it never submits the registration form (no user is
 * created) and uses a fake uid/token, so it is safe to run against prod.
 *
 * Run: cd frontend && E2E_BASE_URL=https://b2b.railtech.uz npm run test:e2e
 */

// A structurally-valid but expired zustand-persisted auth blob. It makes the
// app's initAuth() call /me with a dead token → 401 → refresh 401.
const STALE_AUTH = JSON.stringify({
  state: { accessToken: 'stale.invalid.token', refreshToken: 'stale.invalid.token', isAuthenticated: true },
  version: 0,
});

test.describe('auth flow', () => {
  test('register page renders its form (no crash, no raw i18n keys)', async ({ page }) => {
    await page.goto('/register');
    await expect(page.locator('#root')).not.toBeEmpty();
    await expect(page.getByRole('textbox').first()).toBeVisible();

    const bodyText = (await page.locator('body').innerText()).toLowerCase();
    expect(bodyText, 'untranslated i18n key visible on register page').not.toMatch(
      /\b(common|auth|register|onboarding)\.[a-z]/
    );
  });

  // Regression for project-bug-public-route-401-redirect: a stale token in
  // localStorage makes initAuth's /me return 401; the response interceptor must
  // NOT bounce the user off /setup-password to the login screen. Before the fix
  // the page would flash and then redirect to '/'.
  test('setup-password keeps the user on the page despite a stale token', async ({ page }) => {
    await page.addInitScript((auth) => {
      window.localStorage.setItem('railtech-auth', auth);
    }, STALE_AUTH);

    await page.goto('/setup-password?uid=FAKEuid&token=fake-token-123');
    // Let initAuth → /me (401) → refresh (401) → interceptor settle.
    await page.waitForLoadState('networkidle');

    // The password-setup page must still be rendered — not the login screen.
    await expect(
      page.getByTestId('password-setup-page'),
      'a stale-token 401 bounced the user off the setup page'
    ).toBeVisible();
    // ...and the URL must not have been rewritten to the login root.
    await expect(page).toHaveURL(/\/setup-password/);
  });
});
