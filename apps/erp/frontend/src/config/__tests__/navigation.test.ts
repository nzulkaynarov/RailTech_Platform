import { describe, it, expect } from 'vitest';
import {
  buildNavigation,
  TENANT_NAV,
  type CapableSides,
} from '../navigation';
import type { Capabilities } from '@/store/userStore';

const t = (key: string) => key;

function caps(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_buy: true,
    can_sell: true,
    subscription_active: false,
    can_send_quotes: false,
    quote_send_is_demo: false,
    permissions: [],
    ...overrides,
  };
}

function leafIds(items: ReturnType<typeof buildNavigation>): string[] {
  return items.filter((item) => item.id).map((item) => item.id as string);
}

describe('buildNavigation — no company-verification tier (M1-ERP-02)', () => {
  const buyer: CapableSides = { buy: true, sell: false };

  it('shows the buyer work surfaces without any verification level', () => {
    // Раньше покупатель без подтверждённого уровня проверки видел только Главную и Каталог.
    // Проверки клиентов в ERP нет: пункт решают сторона и права роли.
    const items = buildNavigation(TENANT_NAV, caps(), buyer, 'dashboard', t);
    expect(leafIds(items)).toEqual(['dashboard', 'my-requests', 'suppliers', 'products']);
    const documents = items.find((item) => item.label === 'shell.documents');
    expect(documents?.children?.map((child) => child.id)).toContain('contracts');
  });

  it('still hides a permission-gated item when the role lacks the permission', () => {
    const items = buildNavigation(TENANT_NAV, caps({ permissions: ['catalog.manage'] }), buyer, 'dashboard', t);
    expect(leafIds(items)).not.toContain('my-requests');
    expect(leafIds(items)).toContain('suppliers');
  });
});
