/**
 * Единый реестр страниц SPA — один источник правды для маршрутизации и гейтов.
 *
 * Раньше идентификаторы страниц дублировались в ЧЕТЫРЁХ параллельных списках внутри App.tsx:
 * union-тип `Page`, наборы гейтов (ADMIN/KYC/BUYER/SELLER…), инлайновый `validTypes` в
 * `handleNavigate` и 42-веточный `switch` рендера. Держать их синхронно приходилось вручную,
 * и это уже ломалось: страницы `clients`/`suppliers` были во всех наборах, кроме `validTypes`,
 * из-за чего клик по пункту меню молча отбрасывал пользователя на дашборд (ADR-0005 Phase F).
 *
 * Теперь страница объявляется ОДИН раз строкой этой таблицы, а все наборы выводятся из неё.
 * Добавить страницу — добавить строку; забыть её где-то ещё уже нельзя.
 */

export interface PageDefinition {
  /** Идентификатор страницы = хэш-маршрут (`#crm-deals`) и `activePage` для шеллов. */
  id: string;
  /** Доступна в контексте покупателя (ADR-0005 Phase C). */
  buyer?: boolean;
  /** Доступна в контексте продавца. */
  seller?: boolean;
  /** Страница операторской панели (`admin-*`): требует SystemRole.ADMIN. */
  admin?: boolean;
  /**
   * Не-`admin-*` страница, до которой оператор всё же дотягивается из своего меню
   * (модерация КП, read-only просмотр договоров). `admin: true` подразумевает это.
   */
  adminReachable?: boolean;
  /** Доступна ниже KYC L2 (ADR-0005 tier T0): дашборд, утилиты и чтение каталога. */
  kycExempt?: boolean;
  /**
   * Открывается по голому идентификатору из `handleNavigate` / меню.
   * Параметризованные маршруты (`deal-quote/7`) — false: у них свои переходы.
   */
  navigable?: boolean;
}

// `as const satisfies` — форма каждой строки проверяется по PageDefinition, но литеральные
// типы идентификаторов СОХРАНЯЮТСЯ: из них выводится union `PageId`, а на нём держится
// сужение дискриминированного `Page` (без литералов `Exclude<string, …>` схлопнулся бы в
// `string`, и параметризованные маршруты перестали бы типизироваться).

/** Страницы, общие для обоих контекстов и доступные до прохождения KYC. */
const UTILITY = [
  { id: 'dashboard', buyer: true, seller: true, adminReachable: true, kycExempt: true, navigable: true },
  { id: 'profile', buyer: true, seller: true, adminReachable: true, kycExempt: true, navigable: true },
  { id: 'settings', buyer: true, seller: true, adminReachable: true, kycExempt: true, navigable: true },
  { id: 'help', buyer: true, seller: true, adminReachable: true, kycExempt: true, navigable: true },
] as const satisfies readonly PageDefinition[];

/** Каталог — чтение, разрешено до KYC; `product_detail` параметризован. */
const CATALOG_READ = [
  { id: 'products', buyer: true, seller: true, kycExempt: true, navigable: true },
  { id: 'product_detail', buyer: true, seller: true, kycExempt: true },
] as const satisfies readonly PageDefinition[];

/** Документооборот, общий для покупателя и продавца. */
const SHARED_DOCUMENTS = [
  { id: 'contracts', buyer: true, seller: true, adminReachable: true, navigable: true },
  { id: 'invoices', buyer: true, seller: true, navigable: true },
  { id: 'payments', buyer: true, seller: true, navigable: true },
  { id: 'fulfillments', buyer: true, seller: true, navigable: true },
  { id: 'other-documents', buyer: true, seller: true, navigable: true },
  { id: 'company-files', buyer: true, seller: true, navigable: true },
  { id: 'my-subscription', buyer: true, seller: true, navigable: true },
  // Карточка сделки — одна страница для обеих сторон, родительская крошка контекстная.
  { id: 'request-detail', buyer: true, seller: true },
] as const satisfies readonly PageDefinition[];

const BUYER_ONLY = [
  { id: 'my-requests', buyer: true, navigable: true },
  { id: 'suppliers', buyer: true, navigable: true },
] as const satisfies readonly PageDefinition[];

const SELLER_ONLY = [
  { id: 'categories', seller: true, navigable: true },
  { id: 'equipment-groups', seller: true, navigable: true },
  { id: 'catalog-import', seller: true, navigable: true },
  { id: 'sourcing-requests', seller: true, navigable: true },
  { id: 'crm-deals', seller: true, navigable: true },
  { id: 'crm-quotes', seller: true, adminReachable: true, navigable: true },
  { id: 'deal-quote', seller: true },
  { id: 'acts', seller: true, navigable: true },
  { id: 'clients', seller: true, navigable: true },
] as const satisfies readonly PageDefinition[];

const ADMIN_PLANE = [
  { id: 'admin-users', admin: true, navigable: true },
  { id: 'admin-kyc', admin: true, navigable: true },
  { id: 'admin-subscriptions', admin: true, navigable: true },
  { id: 'admin-entitlements', admin: true, navigable: true },
  { id: 'admin-role-apps', admin: true, navigable: true },
  { id: 'admin-catalog', admin: true, navigable: true },
  { id: 'admin-categories', admin: true, navigable: true },
  { id: 'admin-equipment-groups', admin: true, navigable: true },
  { id: 'admin-offers', admin: true, navigable: true },
  { id: 'admin-companies', admin: true, navigable: true },
  { id: 'admin-deals', admin: true, navigable: true },
  { id: 'admin-master-data', admin: true, navigable: true },
  { id: 'admin-email-templates', admin: true, navigable: true },
  { id: 'admin-operator-roles', admin: true, navigable: true },
  { id: 'admin-access-log', admin: true, navigable: true },
  { id: 'admin-support', admin: true, navigable: true },
  { id: 'admin-leads', admin: true, navigable: true },
] as const satisfies readonly PageDefinition[];

export const PAGE_REGISTRY = [
  ...UTILITY,
  ...CATALOG_READ,
  ...SHARED_DOCUMENTS,
  ...BUYER_ONLY,
  ...SELLER_ONLY,
  ...ADMIN_PLANE,
] as const satisfies readonly PageDefinition[];

/** Идентификатор любой страницы SPA — основа дискриминанта в `Page`. */
export type PageId = (typeof PAGE_REGISTRY)[number]['id'];

const idsWhere = (predicate: (page: PageDefinition) => boolean | undefined): Set<string> =>
  new Set(PAGE_REGISTRY.filter((page) => predicate(page)).map((page) => page.id));

/** Страницы операторской панели: не-ADMIN туда не попадает никогда. */
export const ADMIN_PAGES = idsWhere((page) => page.admin);

/** ADR-0005 tier T0 (KYC pending): дашборд, утилиты и чтение каталога. */
export const KYC_ALLOWED_PAGES = idsWhere((page) => page.kycExempt);

/**
 * Platform Admin — наблюдатель/модератор (ADR-0002): только модерация и платформенный CRUD,
 * НИКОГДА не покупательская/продавецкая бизнес-страница. Не-разрешённый хэш у оператора
 * отбрасывается на его дашборд, а не рендерит поверхность, на которой ему нельзя действовать.
 */
export const ADMIN_REACHABLE_PAGES = idsWhere((page) => page.admin || page.adminReachable);

export const BUYER_PAGES = idsWhere((page) => page.buyer);
export const SELLER_PAGES = idsWhere((page) => page.seller);

/** Цели, которые принимает `handleNavigate` (голый идентификатор из меню/кнопки). */
export const NAVIGABLE_PAGES = idsWhere((page) => page.navigable);

/** Все идентификаторы — рантайм-список для проверок «известен ли маршрут». */
export const PAGE_IDS: readonly PageId[] = PAGE_REGISTRY.map((page) => page.id);
