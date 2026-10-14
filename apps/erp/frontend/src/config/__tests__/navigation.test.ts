import { describe, it, expect } from 'vitest';
import { buildNavigation, TENANT_NAV } from '../navigation';
import type { Capabilities } from '@/store/userStore';

const t = (key: string) => key;

function caps(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    permissions: [],
    ...overrides,
  };
}

function leafIds(items: ReturnType<typeof buildNavigation>): string[] {
  return items.filter((item) => item.id).map((item) => item.id as string);
}

function allIds(items: ReturnType<typeof buildNavigation>): string[] {
  return items.flatMap((item) => [item.id, ...(item.children ?? []).map((child) => child.id)])
    .filter((id): id is string => Boolean(id));
}

describe('buildNavigation — back office of one company (M1-ERP-05 roles)', () => {
  it('shows every register to a viewer without permissions (reading is open to all staff)', () => {
    // «Наблюдатель» (пустой список прав) видит все реестры: просмотр открыт любому сотруднику.
    const items = buildNavigation(TENANT_NAV, caps(), 'dashboard', t);
    expect(leafIds(items)).toEqual(['dashboard', 'crm-deals', 'clients']);
    const documents = items.find((item) => item.label === 'shell.documents');
    expect(documents?.children?.map((child) => child.id)).toEqual([
      'crm-quotes', 'contracts', 'invoices', 'payments', 'acts', 'fulfillments', 'other-documents', 'company-files',
    ]);
  });

  it('has no buyer pages in the menu (moved to Cabinet)', () => {
    const ids = allIds(buildNavigation(TENANT_NAV, caps(), 'dashboard', t));
    for (const buyerPage of ['my-requests', 'suppliers', 'products']) {
      expect(ids).not.toContain(buyerPage);
    }
  });

  it('hides a tool page when the role lacks its permission (price upload needs catalog.manage)', () => {
    const viewer = allIds(buildNavigation(TENANT_NAV, caps(), 'dashboard', t));
    expect(viewer).toContain('my-products');
    expect(viewer).not.toContain('catalog-import');
    const catalog = allIds(buildNavigation(TENANT_NAV, caps({ permissions: ['catalog.manage'] }), 'dashboard', t));
    expect(catalog).toContain('catalog-import');
  });
});
