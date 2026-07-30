import { describe, it, expect } from 'vitest';
import {
  ADMIN_PAGES,
  ADMIN_REACHABLE_PAGES,
  BUYER_PAGES,
  KYC_ALLOWED_PAGES,
  NAVIGABLE_PAGES,
  PAGE_IDS,
  PAGE_REGISTRY,
  SELLER_PAGES,
  type PageDefinition,
} from '../config/pageRegistry';

// Реестр страниц заменил ЧЕТЫРЕ параллельных списка идентификаторов, которые раньше
// жили в App.tsx (union-тип Page, наборы гейтов, validTypes в handleNavigate, switch
// рендера). Эти тесты — доказательство эквивалентности: наборы, ВЫВЕДЕННЫЕ из реестра,
// совпадают с прежними рукописными до символа. Если правка реестра сдвинет любой гейт,
// тест упадёт здесь, а не багом на проде.
//
// Литералы ниже переписаны с App.tsx на коммите 67d7feb (до рефактора) и намеренно
// НЕ выводятся из реестра — иначе тест проверял бы сам себя.
//
// ОСОЗНАННЫЕ РАСХОЖДЕНИЯ со снимком, внесённые волной U1 (аудит UI 2026-07-30). Каждое —
// закрытие тупика «объект показан, а страницы для этой роли нет»; всё остальное обязано
// совпадать со снимком, иначе тест падает:
//   • BUYER_PAGES += `acts` — акт двусторонний, заказчик его принимает (сервер отдаёт ему
//     `viewer_can_sign`), а страница была продавцовской;
//   • ADMIN_REACHABLE_PAGES += `invoices`, `request-detail` — с операторских страниц КП и
//     договоров ведут ссылки именно туда;
//   • KYC_ALLOWED_PAGES += `my-requests`, `my-subscription` — чек-лист онбординга и баннер
//     тарифа зовут новичка ровно сюда ДО верификации.

const asSorted = (value: Set<string> | readonly string[]) => [...value].sort();

// PAGE_REGISTRY — кортеж точных литеральных типов (`as const`), поэтому у строки
// без флага соответствующего поля просто нет. Для обхода смотрим на него через
// широкий PageDefinition, где все флаги опциональны.
const registry: readonly PageDefinition[] = PAGE_REGISTRY;

describe('реестр страниц: эквивалентность прежним наборам App.tsx', () => {
  it('ADMIN_PAGES', () => {
    expect(asSorted(ADMIN_PAGES)).toEqual(
      asSorted([
        'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
        'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
        'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
        'admin-operator-roles', 'admin-access-log', 'admin-support', 'admin-leads',
      ]),
    );
  });

  it('KYC_ALLOWED_PAGES', () => {
    expect(asSorted(KYC_ALLOWED_PAGES)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help', 'products', 'product_detail',
        'my-requests', 'my-subscription',
      ]),
    );
  });

  it('ADMIN_REACHABLE_PAGES', () => {
    expect(asSorted(ADMIN_REACHABLE_PAGES)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help',
        'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
        'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
        'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
        'admin-operator-roles', 'admin-access-log', 'admin-support', 'admin-leads',
        'crm-quotes', 'contracts', 'invoices', 'request-detail',
      ]),
    );
  });

  it('BUYER_PAGES', () => {
    expect(asSorted(BUYER_PAGES)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help',
        'products', 'product_detail', 'my-requests', 'request-detail',
        'contracts', 'invoices', 'payments', 'acts', 'fulfillments', 'other-documents', 'company-files',
        'my-subscription', 'suppliers',
      ]),
    );
  });

  it('SELLER_PAGES', () => {
    expect(asSorted(SELLER_PAGES)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help',
        'products', 'product_detail', 'categories', 'equipment-groups', 'catalog-import',
        'sourcing-requests', 'crm-deals', 'crm-quotes',
        'deal-quote', 'request-detail', 'my-subscription',
        'contracts', 'invoices', 'payments', 'acts', 'fulfillments', 'other-documents', 'company-files',
        'clients',
      ]),
    );
  });

  it('NAVIGABLE_PAGES == прежний validTypes из handleNavigate', () => {
    expect(asSorted(NAVIGABLE_PAGES)).toEqual(
      asSorted([
        'dashboard', 'products', 'profile', 'settings',
        'sourcing-requests',
        'crm-deals', 'crm-quotes',
        'clients', 'suppliers',
        'categories', 'equipment-groups',
        'help', 'my-requests',
        'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
        'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
        'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
        'admin-operator-roles', 'admin-access-log', 'admin-support', 'admin-leads',
        'contracts', 'invoices', 'payments', 'acts', 'fulfillments', 'other-documents', 'company-files',
        'my-subscription', 'catalog-import',
      ]),
    );
  });
});

describe('реестр страниц: инварианты', () => {
  it('идентификаторы уникальны', () => {
    expect(PAGE_IDS.length).toBe(new Set(PAGE_IDS).size);
  });

  it('каждая страница достижима хотя бы для одной роли', () => {
    const orphans = registry.filter(
      (page) => !page.buyer && !page.seller && !page.admin && !page.adminReachable,
    );
    expect(orphans.map((page) => page.id)).toEqual([]);
  });

  it('навигация из меню не предлагает параметризованные маршруты', () => {
    // `handleNavigate` принимает голый идентификатор, поэтому маршрут, требующий id
    // в хэше, нельзя открыть кликом по пункту меню — только адресным переходом.
    for (const id of ['product_detail', 'request-detail', 'deal-quote']) {
      expect(NAVIGABLE_PAGES.has(id)).toBe(false);
    }
  });

  it('admin-страница подразумевает достижимость оператором', () => {
    for (const page of registry.filter((entry) => entry.admin)) {
      expect(ADMIN_REACHABLE_PAGES.has(page.id)).toBe(true);
    }
  });

  it('страница вне KYC-исключений недоступна до верификации', () => {
    // Порог KYC (ADR-0005 tier T0): всё, что не помечено kycExempt, отбрасывается
    // гейтом до подтверждения L2 — здесь фиксируем, что список исключений короткий.
    // Потолок поднят с 6 до 8 волной U1: до верификации доступны ещё свои заявки
    // (черновик разрешён KYC-floor'ом) и подписка (страница счёта, а не бизнес-операция).
    expect(KYC_ALLOWED_PAGES.size).toBeLessThanOrEqual(8);
  });

  it('до KYC доступно ровно то, куда зовут подсказки новичку', () => {
    // Чек-лист онбординга и баннер тарифа — единственные элементы, которые ДО верификации
    // предлагают действие. Пока их цели не были исключениями, обе подсказки вели в отказ.
    for (const id of ['my-requests', 'my-subscription']) {
      expect(KYC_ALLOWED_PAGES.has(id)).toBe(true);
    }
  });
});
