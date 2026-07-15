import { describe, it, expect } from 'vitest';
import {
  isKycVerified,
  buildNavigation,
  TENANT_NAV,
  type CapableSides,
} from '../navigation';
import type { Capabilities } from '@/store/userStore';

const t = (key: string) => key;

function caps(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    kyc_level: null,
    can_buy: true,
    can_sell: true,
    subscription_active: false,
    can_send_quotes: false,
    quote_send_is_demo: false,
    permissions: [],
    is_platform_admin: false,
    operator_permissions: null,
    ...overrides,
  };
}

function leafIds(items: ReturnType<typeof buildNavigation>): string[] {
  return items.filter((item) => item.id).map((item) => item.id as string);
}

describe('isKycVerified', () => {
  it('treats the seeded L2 code as verified', () => {
    expect(isKycVerified('L2_VERIFIED')).toBe(true);
  });

  it('treats the seeded top-tier code L3_CONTRACTED as verified (bug fix — was L3_VERIFIED)', () => {
    expect(isKycVerified('L3_CONTRACTED')).toBe(true);
  });

  it('does NOT treat the phantom L3_VERIFIED as verified (no such seeded code)', () => {
    expect(isKycVerified('L3_VERIFIED')).toBe(false);
  });

  it('treats pre-KYC / unknown levels as unverified', () => {
    expect(isKycVerified('L1_UNVERIFIED')).toBe(false);
    expect(isKycVerified('PROFILE_SUBMITTED')).toBe(false);
    expect(isKycVerified(null)).toBe(false);
    expect(isKycVerified(undefined)).toBe(false);
  });
});

describe('buildNavigation — ADR-0005 tier T0 (KYC pending)', () => {
  const t0Buyer: CapableSides = { buy: true, sell: false };

  it('shows only Главная + Каталог for a KYC-pending buyer (catalog-read only)', () => {
    const items = buildNavigation(
      TENANT_NAV,
      caps({ kyc_level: 'L1_UNVERIFIED' }),
      t0Buyer,
      'dashboard',
      t,
    );
    // Everything except dashboard + catalog-read (products) must be hidden pre-KYC —
    // matches App.tsx KYC_ALLOWED_PAGES so nothing is shown-then-bounced.
    expect(leafIds(items)).toEqual(['dashboard', 'products']);
  });

  it('reveals kyc-gated items once the company reaches L3_CONTRACTED', () => {
    const items = buildNavigation(
      TENANT_NAV,
      caps({ kyc_level: 'L3_CONTRACTED' }),
      t0Buyer,
      'dashboard',
      t,
    );
    // A verified buyer now sees the buyer request surface that kyc:true had hidden.
    expect(leafIds(items)).toContain('my-requests');
  });
});
