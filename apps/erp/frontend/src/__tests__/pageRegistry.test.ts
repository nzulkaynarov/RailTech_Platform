import { describe, it, expect } from 'vitest';
import {
  BUYER_PAGES,
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
//   • R6 (+ `catalog-reference`): три справочника свелись к ОДНОЙ странице с вкладками, и
//     новая страница наследует ровно те же свойства, что были у каждого из трёх маршрутов
//     (продавцовая, открывается из меню). Старые идентификаторы остались в реестре
//     маршрутами-алиасами — иначе закладка `#categories` уехала бы на дашборд.
//   • M1-ERP-02 (волна 1a): операторская плоскость удалена — 17 страниц `admin-*`,
//     наборы ADMIN_PAGES / ADMIN_REACHABLE_PAGES и флаги `admin` / `adminReachable` исчезли
//     из реестра вместе с `PlatformAdminShell` (MIGRATION-MAP §1, ARCHITECTURE §7).
//   • M1-ERP-02 (волна 1c): порог проверки компании удалён — флаг исключений из него и набор
//     разрешённых до проверки страниц исчезли из реестра; гейт страниц — только контекст.

const asSorted = (value: Set<string> | readonly string[]) => [...value].sort();

// PAGE_REGISTRY — кортеж точных литеральных типов (`as const`), поэтому у строки
// без флага соответствующего поля просто нет. Для обхода смотрим на него через
// широкий PageDefinition, где все флаги опциональны.
const registry: readonly PageDefinition[] = PAGE_REGISTRY;

describe('реестр страниц: эквивалентность прежним наборам App.tsx', () => {
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
        // + волна A номенклатуры: очередь наполнения продавца (spec-nomenclature-lifecycle).
        'nomenclature',
        // R2/R3: «Мои товары» + создание/редактор карточки; nomenclature — алиас.
        'my-products', 'product-new', 'product-edit',
        // + T3: справочник ТН ВЭД (spec-tnved-flow).
        'hs-directory',
        // + R6: страница справочников (ТН ВЭД · категории · группы) — тоже продавцовая.
        'catalog-reference',
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
        'contracts', 'invoices', 'payments', 'acts', 'fulfillments', 'other-documents', 'company-files',
        'my-subscription', 'catalog-import',
        // + волна A номенклатуры.
        'nomenclature',
        // R2/R3: «Мои товары» + создание/редактор карточки; nomenclature — алиас.
        'my-products', 'product-new', // product-edit — параметрный, из меню не открывается
        // + T3: справочник ТН ВЭД.
        'hs-directory',
        // + R6: единственный пункт меню, оставшийся от трёх справочников.
        'catalog-reference',
      ]),
    );
  });
});

describe('реестр страниц: инварианты', () => {
  it('идентификаторы уникальны', () => {
    expect(PAGE_IDS.length).toBe(new Set(PAGE_IDS).size);
  });

  it('каждая страница достижима хотя бы для одной роли', () => {
    const orphans = registry.filter((page) => !page.buyer && !page.seller);
    expect(orphans.map((page) => page.id)).toEqual([]);
  });

  it('навигация из меню не предлагает параметризованные маршруты', () => {
    // `handleNavigate` принимает голый идентификатор, поэтому маршрут, требующий id
    // в хэше, нельзя открыть кликом по пункту меню — только адресным переходом.
    for (const id of ['product_detail', 'request-detail', 'deal-quote']) {
      expect(NAVIGABLE_PAGES.has(id)).toBe(false);
    }
  });
});
