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
 */

export interface PageDefinition {
  /** Идентификатор страницы = хэш-маршрут (`#crm-deals`) и `activePage` для шеллов. */
  id: string;
  /** Доступна в контексте покупателя (ADR-0005 Phase C). */
  buyer?: boolean;
  /** Доступна в контексте продавца. */
  seller?: boolean;
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

/** Страницы, общие для обоих контекстов. */
const UTILITY = [
  { id: 'dashboard', buyer: true, seller: true, navigable: true },
  { id: 'profile', buyer: true, seller: true, navigable: true },
  { id: 'settings', buyer: true, seller: true, navigable: true },
  { id: 'help', buyer: true, seller: true, navigable: true },
] as const satisfies readonly PageDefinition[];

/** Каталог и наполнение номенклатуры; `product_detail` параметризован. */
const CATALOG_READ = [
  { id: 'products', buyer: true, seller: true, navigable: true },
  // Очередь наполнения номенклатуры — только продавцовая сторона (у покупателя своего каталога нет).
  { id: 'nomenclature', seller: true, navigable: true },
  // R2/R3: единый реестр «Мои товары» и карточка-редактор. `nomenclature` выше остаётся
  // рабочим алиасом (закладки, ссылки из уведомлений) и в меню больше не показывается.
  { id: 'my-products', seller: true, navigable: true },
  { id: 'product-new', seller: true, navigable: true },
  { id: 'product-edit', seller: true },
  // Справочники платформы одной страницей: ТН ВЭД · категории · группы оборудования (R6).
  // Пункт меню теперь ОДИН — раздел «Номенклатура» состоял из шести, и три из них были
  // справочниками (D14). Старые маршруты ниже остались рабочими алиасами на свою вкладку.
  { id: 'catalog-reference', seller: true, navigable: true },
  { id: 'hs-directory', seller: true, navigable: true },
  { id: 'product_detail', buyer: true, seller: true },
] as const satisfies readonly PageDefinition[];

/**
 * Документооборот, общий для покупателя и продавца.
 *
 * Правило раздела (U1): если документ ВИДЕН обеим сторонам сделки, то и страница документа
 * доступна обеим. Иначе получается разрыв «объект показан, а места нет»: виджеты выводят то,
 * что вернул сервер, а маршрут упирается в статический список ролей. Списки при этом сужены
 * видимостью на бэкенде — контрагент видит только документы СВОИХ сделок, скрытая конкуренция
 * (ADR-0003 §5) не страдает.
 */
const SHARED_DOCUMENTS = [
  { id: 'contracts', buyer: true, seller: true, navigable: true },
  { id: 'invoices', buyer: true, seller: true, navigable: true },
  { id: 'payments', buyer: true, seller: true, navigable: true },
  { id: 'fulfillments', buyer: true, seller: true, navigable: true },
  // Акт — ДВУСТОРОННИЙ документ: выпускает исполнитель, принимает заказчик (волна G2), и
  // сервер отдаёт покупателю `viewer_can_sign`/`viewer_can_reject`. Пока страница была
  // продавцовской, покупатель не мог воспользоваться собственным правом: четыре поверхности
  // показывали ему акт, и все четыре вели в отказ. Это было единственное исключение из
  // правила раздела — остальные документы цепочки уже были общими.
  { id: 'acts', buyer: true, seller: true, navigable: true },
  { id: 'other-documents', buyer: true, seller: true, navigable: true },
  { id: 'company-files', buyer: true, seller: true, navigable: true },
  // Подписка — страница СЧЁТА, а не бизнес-операция (уйдёт с волной подписок M1-ERP-02).
  { id: 'my-subscription', buyer: true, seller: true, navigable: true },
  // Карточка сделки — одна страница для обеих сторон, родительская крошка контекстная.
  { id: 'request-detail', buyer: true, seller: true },
] as const satisfies readonly PageDefinition[];

const BUYER_ONLY = [
  { id: 'my-requests', buyer: true, navigable: true },
  { id: 'suppliers', buyer: true, navigable: true },
] as const satisfies readonly PageDefinition[];

const SELLER_ONLY = [
  // R6: собственных страниц у этих маршрутов больше нет — оба открывают «Справочники» на
  // своей вкладке. Строки оставлены намеренно: хэши напечатаны в закладках и старых письмах,
  // а удалить маршрут — значит отправить такую ссылку на дашборд.
  { id: 'categories', seller: true, navigable: true },
  { id: 'equipment-groups', seller: true, navigable: true },
  { id: 'catalog-import', seller: true, navigable: true },
  { id: 'sourcing-requests', seller: true, navigable: true },
  { id: 'crm-deals', seller: true, navigable: true },
  { id: 'crm-quotes', seller: true, navigable: true },
  // Билдер КП — рабочее место ПРОДАВЦА (правка цен, маржи, себестоимости). Покупателю сюда
  // не нужно и нельзя: его вид того же КП живёт на карточке заявки. Ссылки на КП поэтому
  // разрешаются через `documentRoute` по стороне зрителя, а не открытием этой страницы.
  { id: 'deal-quote', seller: true },
  { id: 'clients', seller: true, navigable: true },
] as const satisfies readonly PageDefinition[];

export const PAGE_REGISTRY = [
  ...UTILITY,
  ...CATALOG_READ,
  ...SHARED_DOCUMENTS,
  ...BUYER_ONLY,
  ...SELLER_ONLY,
] as const satisfies readonly PageDefinition[];

/** Идентификатор любой страницы SPA — основа дискриминанта в `Page`. */
export type PageId = (typeof PAGE_REGISTRY)[number]['id'];

const idsWhere = (predicate: (page: PageDefinition) => boolean | undefined): Set<string> =>
  new Set(PAGE_REGISTRY.filter((page) => predicate(page)).map((page) => page.id));

export const BUYER_PAGES = idsWhere((page) => page.buyer);
export const SELLER_PAGES = idsWhere((page) => page.seller);

/** Цели, которые принимает `handleNavigate` (голый идентификатор из меню/кнопки). */
export const NAVIGABLE_PAGES = idsWhere((page) => page.navigable);

/** Все идентификаторы — рантайм-список для проверок «известен ли маршрут». */
export const PAGE_IDS: readonly PageId[] = PAGE_REGISTRY.map((page) => page.id);
