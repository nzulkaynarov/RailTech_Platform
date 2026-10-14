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

describe('buildNavigation — back office of one company (M1-ERP-02 wave 3)', () => {
  it('shows the back-office work surfaces without any buyer/seller side', () => {
    // Сторон «покупатель / продавец» нет: пункт решает только право роли. Пустой список прав =
    // «неизвестно» — меню ничего не прячет (сервер всё равно решает).
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

  it('still hides a permission-gated item when the role lacks the permission', () => {
    const items = buildNavigation(TENANT_NAV, caps({ permissions: ['catalog.manage'] }), 'dashboard', t);
    expect(leafIds(items)).not.toContain('crm-deals');
    expect(allIds(items)).toContain('my-products');
  });
});
