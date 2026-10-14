/**
 * Единый реестр страниц SPA — один источник правды для маршрутизации и гейтов.
 *
 * Раньше идентификаторы страниц дублировались в ЧЕТЫРЁХ параллельных списках внутри App.tsx:
 * union-тип `Page`, наборы гейтов (BUYER/SELLER…), инлайновый `validTypes` в
 * `handleNavigate` и 42-веточный `switch` рендера. Держать их синхронно приходилось вручную,
 * и это уже ломалось: страницы `clients`/`suppliers` были во всех наборах, кроме `validTypes`,
 * из-за чего клик по пункту меню молча отбрасывал пользователя на дашборд (ADR-0005 Phase F).
 *
 * Теперь страница объявляется ОДИН раз строкой этой таблицы, а все наборы выводятся из неё.
 * Добавить страницу — добавить строку; забыть её где-то ещё уже нельзя.
 *
 * ERP — бэк-офис одной компании (M1-ERP-02 волна 3): все страницы принадлежат сотрудникам
 * бэк-офиса, флагов стороны «покупатель / продавец» больше нет. Доступ к действиям решает право
 * роли (меню прячет недоступное — `config/navigation`, истина — на сервере). Покупательские
 * страницы («Мои заявки», «Поставщики», витрина каталога) ушли в Cabinet (`apps/cabinet`).
 */

export interface PageDefinition {
  /** Идентификатор страницы = хэш-маршрут (`#crm-deals`) и `activePage` для шелла. */
  id: string;
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

/** Служебные страницы. */
const UTILITY = [
  { id: 'dashboard', navigable: true },
  { id: 'profile', navigable: true },
  { id: 'settings', navigable: true },
  { id: 'help', navigable: true },
] as const satisfies readonly PageDefinition[];

/** Каталог и наполнение номенклатуры; `product_detail` и `product-edit` параметризованы. */
const CATALOG = [
  // Бывшая витрина каталога покупателя (волна 3 удалила её): старый хэш — алиас «Моих товаров».
  { id: 'products', navigable: true },
  // R2/R3: единый реестр «Мои товары» и карточка-редактор. `nomenclature` — рабочий алиас
  // (закладки, ссылки из уведомлений), в меню не показывается.
  { id: 'nomenclature', navigable: true },
  { id: 'my-products', navigable: true },
  { id: 'product-new', navigable: true },
  { id: 'product-edit' },
  // Справочники одной страницей: ТН ВЭД · категории (R6). Пункт меню ОДИН;
  // старые маршруты ниже — рабочие алиасы на свою вкладку.
  { id: 'catalog-reference', navigable: true },
  { id: 'hs-directory', navigable: true },
  { id: 'categories', navigable: true },
  { id: 'catalog-import', navigable: true },
  { id: 'product_detail' },
] as const satisfies readonly PageDefinition[];

/** Документы сделки со стороны исполнителя: договоры, счета, оплаты, акты, отгрузка. */
const DOCUMENTS = [
  { id: 'contracts', navigable: true },
  { id: 'invoices', navigable: true },
  { id: 'payments', navigable: true },
  { id: 'fulfillments', navigable: true },
  { id: 'acts', navigable: true },
  { id: 'other-documents', navigable: true },
  { id: 'company-files', navigable: true },
] as const satisfies readonly PageDefinition[];

/** Работа с запросами клиентов: очередь сделок, карточка сделки, КП-билдер, книга клиентов. */
const SALES = [
  // Старый хэш очереди заявок — алиас «Сделок» (закладки и письма).
  { id: 'sourcing-requests', navigable: true },
  { id: 'crm-deals', navigable: true },
  { id: 'crm-quotes', navigable: true },
  // Карточка сделки и билдер КП — параметризованы (`request-detail/7`, `deal-quote/7`).
  { id: 'request-detail' },
  { id: 'deal-quote' },
  { id: 'clients', navigable: true },
] as const satisfies readonly PageDefinition[];

export const PAGE_REGISTRY = [
  ...UTILITY,
  ...CATALOG,
  ...DOCUMENTS,
  ...SALES,
] as const satisfies readonly PageDefinition[];

/** Идентификатор любой страницы SPA — основа дискриминанта в `Page`. */
export type PageId = (typeof PAGE_REGISTRY)[number]['id'];

/** Цели, которые принимает `handleNavigate` (голый идентификатор из меню/кнопки). */
export const NAVIGABLE_PAGES: ReadonlySet<string> = new Set(
  PAGE_REGISTRY.filter((page: PageDefinition) => page.navigable).map((page) => page.id),
);

/** Все идентификаторы — рантайм-список для проверок «известен ли маршрут». */
export const PAGE_IDS: readonly PageId[] = PAGE_REGISTRY.map((page) => page.id);
