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
//   • KYC_ALLOWED_PAGES += страницы номенклатуры — наполнение каталога разрешено до
//     верификации, публикация осталась за порогом (гейт переехал в catalog/publishing.py).
//   • R6 (+ `catalog-reference`): три справочника свелись к ОДНОЙ странице с вкладками, и
//     новая страница наследует ровно те же свойства, что были у каждого из трёх маршрутов
//     (продавцовая, до KYC, открывается из меню). Старые идентификаторы остались в реестре
//     маршрутами-алиасами — иначе закладка `#categories` уехала бы на дашборд.

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
        // Наполнение каталога до верификации (эталон Amazon Seller Central): карточки,
        // справочники и загрузка прайса открыты, ПУБЛИКАЦИЯ — нет, её держит сервер
        // (`SELLER_KYC_REQUIRED` в catalog/publishing.py).
        'nomenclature', 'hs-directory', 'categories', 'equipment-groups', 'catalog-import',
        // R2/R3: «Мои товары» + создание/редактор карточки; nomenclature — алиас.
        'my-products', 'product-new', 'product-edit',
        // R6: единая страница справочников — на том же уровне доступа, что и три маршрута,
        // которые она заменила в меню.
        'catalog-reference',
        // Карточка своей заявки: KYC-floor разрешает покупателю ЧЕРНОВИК, список заявок ему
        // уже открыт, и строка кликабельна — без этой страницы клик по собственному
        // черновику отбрасывал новичка на дашборд. Порог остался там, где он и есть по
        // смыслу: на ОТПРАВКЕ (сервер, `KYC_REQUIRED_TO_SUBMIT`).
        'request-detail',
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
        'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
        'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
        'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
        'admin-operator-roles', 'admin-access-log', 'admin-support', 'admin-leads',
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
    // С 8 до 13 — волной «наполнение до верификации»: пять страниц номенклатуры перестали
    // прятаться, потому что ГОТОВИТЬ каталог до проверки документов можно (Amazon Seller
    // Central), а выпускать в общий каталог — нет. Порог не исчез, он переехал с раздела на
    // действие публикации, и держит его сервер.
    // С 13 до 14 — R6: три справочника свелись в одну страницу, но старые маршруты остались
    // алиасами (закладки), поэтому исключений стало на одно больше, а ДОСТУПА — ни на грамм:
    // те же три справочника, просто теперь у них общий вход.
    // С 14 до 17 — R2/R3: реестр «Мои товары», создание и редактор карточки. Это те же
    // поверхности наполнения, что открыл #550, — одним объектом вместо шторки и очереди.
    // С 17 до 18 — карточка СВОЕЙ заявки: черновик разрешён KYC-floor'ом, а прочитать его
    // было нельзя. Доступа к чужому это не даёт: выборка на сервере и так своя.
    expect(KYC_ALLOWED_PAGES.size).toBeLessThanOrEqual(18);
  });

  it('до KYC доступно ровно то, куда зовут подсказки новичку', () => {
    // Чек-лист онбординга и баннер тарифа — единственные элементы, которые ДО верификации
    // предлагают действие. Пока их цели не были исключениями, обе подсказки вели в отказ.
    for (const id of ['my-requests', 'my-subscription', 'request-detail']) {
      expect(KYC_ALLOWED_PAGES.has(id)).toBe(true);
    }
  });
});
