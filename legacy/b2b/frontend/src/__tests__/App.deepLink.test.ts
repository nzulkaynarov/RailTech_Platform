import { describe, it, expect } from 'vitest';
import { parseHashToPage } from '../routes/hashRoute';
import { evaluatePageGuard, type PageGuardInput } from '../routes/pageGuard';

// WP-4 — cold-load deep-link regression guard.
//
// Root cause under test: on a cold load with a persisted valid session,
// authStore rehydrates isAuthenticated/user from localStorage while isLoading
// stays at its default `false`, so App mounts MainApp on the FIRST render —
// before initAuth()/loadFromAuth() run. At that instant userStore is still at
// pre-auth DEFAULTS (role 'USER', kycStatus 'not_started', activeStatus 'BUYER',
// empty statusEntries). The old KYC/context guards enforced against those and
// bounced a valid deep-link (#request-detail/{id}, #deal-quote/{id}) to
// #dashboard, clobbering the hash via replaceState. The fix defers all guards
// until bootstrap (`bootstrapped`, i.e. userStore.screen === 'main').

/** Build a guard input with sensible verified-buyer defaults. */
function input(overrides: Partial<PageGuardInput> & { pageType: string }): PageGuardInput {
  return {
    role: 'USER',
    kycStatus: 'verified',
    activeStatus: 'BUYER',
    statusEntries: [{ status: 'BUYER', verification: 'verified' }],
    bootstrapped: true,
    ...overrides,
  };
}

/** Pre-auth default store state, as seen on the first render of a cold load. */
const PRE_AUTH_DEFAULTS: Omit<PageGuardInput, 'pageType'> = {
  role: 'USER',
  kycStatus: 'not_started',
  activeStatus: 'BUYER',
  statusEntries: [],
  bootstrapped: false,
};

describe('parseHashToPage', () => {
  it('parses a parameterised request-detail deep link', () => {
    expect(parseHashToPage('#request-detail/3')).toEqual({ type: 'request-detail', dealId: 3 });
  });

  it('parses a parameterised deal-quote deep link', () => {
    expect(parseHashToPage('#deal-quote/7')).toEqual({ type: 'deal-quote', dealId: 7 });
  });

  it('parses a product_detail deep link', () => {
    expect(parseHashToPage('#product_detail/ABC-1')).toEqual({ type: 'product_detail', productId: 'ABC-1' });
  });

  it('falls back to the list page for a bare/invalid request-detail hash', () => {
    expect(parseHashToPage('#request-detail')).toEqual({ type: 'my-requests' });
    expect(parseHashToPage('#request-detail/notanumber')).toEqual({ type: 'my-requests' });
  });

  it('falls back to crm-deals for an invalid deal-quote id', () => {
    expect(parseHashToPage('#deal-quote/xyz')).toEqual({ type: 'crm-deals' });
  });

  it('treats empty / #dashboard as dashboard', () => {
    expect(parseHashToPage('')).toEqual({ type: 'dashboard' });
    expect(parseHashToPage('#dashboard')).toEqual({ type: 'dashboard' });
  });

  it('strips a query suffix from the hash', () => {
    expect(parseHashToPage('#crm-quotes?deal=123')).toEqual({ type: 'crm-quotes' });
  });
});

describe('evaluatePageGuard — cold-load deferral (the fix)', () => {
  it('ALLOWS a request-detail deep link before bootstrap (does not bounce on defaults)', () => {
    // Before the fix this bounced: kyc default not_started + request-detail
    // outside KYC_ALLOWED_PAGES.
    expect(evaluatePageGuard({ ...PRE_AUTH_DEFAULTS, pageType: 'request-detail' })).toEqual({ action: 'allow' });
  });

  it('ALLOWS a deal-quote deep link before bootstrap (seller cold load)', () => {
    // Before the fix this bounced twice: KYC (not_started) AND context
    // (default BUYER + empty statusEntries → deal-quote ∉ BUYER_PAGES).
    expect(evaluatePageGuard({ ...PRE_AUTH_DEFAULTS, pageType: 'deal-quote' })).toEqual({ action: 'allow' });
  });

  it('ALLOWS an admin deep link before bootstrap (admin cold load)', () => {
    expect(evaluatePageGuard({ ...PRE_AUTH_DEFAULTS, pageType: 'admin-users' })).toEqual({ action: 'allow' });
  });
});

describe('evaluatePageGuard — valid deep links survive bootstrap', () => {
  it('opens request-detail for a verified buyer', () => {
    expect(evaluatePageGuard(input({ pageType: 'request-detail' }))).toEqual({ action: 'allow' });
  });

  it('opens request-detail for a verified seller', () => {
    expect(
      evaluatePageGuard(
        input({ pageType: 'request-detail', activeStatus: 'SELLER', statusEntries: [{ status: 'SELLER', verification: 'verified' }] }),
      ),
    ).toEqual({ action: 'allow' });
  });

  it('opens deal-quote for a verified seller', () => {
    expect(
      evaluatePageGuard(
        input({ pageType: 'deal-quote', activeStatus: 'SELLER', statusEntries: [{ status: 'SELLER', verification: 'verified' }] }),
      ),
    ).toEqual({ action: 'allow' });
  });
});

describe('evaluatePageGuard — cross-role / role bounces still hold after bootstrap', () => {
  it('bounces a pure buyer off a seller-only page (deal-quote)', () => {
    expect(evaluatePageGuard(input({ pageType: 'deal-quote' }))).toEqual({ action: 'bounce', reason: 'context' });
  });

  it('adopts the seller context for a dual buyer+seller hitting a seller page', () => {
    expect(
      evaluatePageGuard(
        input({
          pageType: 'deal-quote',
          activeStatus: 'BUYER',
          statusEntries: [
            { status: 'BUYER', verification: 'verified' },
            { status: 'SELLER', verification: 'verified' },
          ],
        }),
      ),
    ).toEqual({ action: 'adopt', context: 'SELLER' });
  });

  it('bounces an unverified user off a non-KYC-floor page (KYC guard)', () => {
    expect(evaluatePageGuard(input({ pageType: 'request-detail', kycStatus: 'pending' }))).toEqual({
      action: 'bounce',
      reason: 'kyc',
    });
  });

  it('bounces a non-admin off an admin page (admin guard)', () => {
    expect(evaluatePageGuard(input({ pageType: 'admin-users' }))).toEqual({ action: 'bounce', reason: 'admin' });
  });

  it('lets an admin open an admin page', () => {
    expect(evaluatePageGuard(input({ pageType: 'admin-users', role: 'ADMIN' }))).toEqual({ action: 'allow' });
  });

  it('lets an admin open an allowlisted moderation surface (contracts)', () => {
    expect(evaluatePageGuard(input({ pageType: 'contracts', role: 'ADMIN' }))).toEqual({ action: 'allow' });
  });

  it('bounces an admin off a business page not on its allowlist (crm-deals)', () => {
    expect(evaluatePageGuard(input({ pageType: 'crm-deals', role: 'ADMIN' }))).toEqual({
      action: 'bounce',
      reason: 'context',
    });
  });

  it('bounces an unknown/stale hash to the dashboard (invalid hash → dashboard)', () => {
    expect(evaluatePageGuard(input({ pageType: 'totally-bogus-page' }))).toEqual({ action: 'bounce', reason: 'context' });
  });
});
