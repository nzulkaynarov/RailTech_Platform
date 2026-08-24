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

/**
 * Каталог — чтение, разрешено до KYC; `product_detail` параметризован.
 *
 * Наполнение номенклатуры тоже `kycExempt`: эталон Amazon Seller Central — листинги
 * готовятся, пока идёт проверка аккаунта, а живыми становятся после неё. Ниже L2 продавец
 * заводит и правит карточки, грузит прайс и смотрит справочники; ПУБЛИКАЦИЯ остаётся за
 * порогом и отказывает на сервере (`SELLER_KYC_REQUIRED`, catalog/publishing.py).
 */
const CATALOG_READ = [
  { id: 'products', buyer: true, seller: true, kycExempt: true, navigable: true },
  // Очередь наполнения номенклатуры — только продавцовая сторона (у покупателя своего каталога нет).
  { id: 'nomenclature', seller: true, kycExempt: true, navigable: true },
  // R2/R3: единый реестр «Мои товары» и карточка-редактор. `nomenclature` выше остаётся
  // рабочим алиасом (закладки, ссылки из уведомлений) и в меню больше не показывается.
  // Наполнение открыто до KYC (#550), поэтому все три — kycExempt; публикацию держит сервер.
  { id: 'my-products', seller: true, kycExempt: true, navigable: true },
  { id: 'product-new', seller: true, kycExempt: true, navigable: true },
  { id: 'product-edit', seller: true, kycExempt: true },
  // Справочники платформы одной страницей: ТН ВЭД · категории · группы оборудования (R6).
  // Пункт меню теперь ОДИН — раздел «Номенклатура» состоял из шести, и три из них были
  // справочниками (D14). Старые маршруты ниже остались рабочими алиасами на свою вкладку.
  { id: 'catalog-reference', seller: true, kycExempt: true, navigable: true },
  { id: 'hs-directory', seller: true, kycExempt: true, navigable: true },
  { id: 'product_detail', buyer: true, seller: true, kycExempt: true },
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
  { id: 'contracts', buyer: true, seller: true, adminReachable: true, navigable: true },
  // Оператору открыт, потому что его же страница договоров ведёт сюда кнопкой «Открыть счёт».
  { id: 'invoices', buyer: true, seller: true, adminReachable: true, navigable: true },
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
  // Подписка — страница СЧЁТА, а не бизнес-операция: и баннер тарифа, и чек-лист онбординга
  // зовут сюда новичка ДО прохождения KYC (эталон — Stripe/Odoo: биллинг доступен всегда).
  // Пока страница была за KYC-порогом, обе подсказки вели в отказ.
  { id: 'my-subscription', buyer: true, seller: true, kycExempt: true, navigable: true },
  // Карточка сделки — одна страница для обеих сторон, родительская крошка контекстная.
  // Оператору открыта: на его страницах КП и договоров ссылка на сделку ведёт сюда.
  //
  // `kycExempt` — ровно по той же причине, что у `my-requests`: ниже KYC L2 покупателю
  // разрешён ЧЕРНОВИК заявки (ADR-0006, KYC floor), список своих заявок ему уже открыт, и
  // строка в нём кликабельна. Без этой пометки клик по собственному черновику отбрасывал
  // новичка на дашборд: гейт стоял на ЧТЕНИИ своего документа, тогда как настоящий порог —
  // ОТПРАВКА (сервер держит его кодом `KYC_REQUIRED_TO_SUBMIT`). Эталон тот же, что у
  // Stripe и Odoo: незавершённую верификацию блокирует публикация, а не просмотр черновика.
  { id: 'request-detail', buyer: true, seller: true, adminReachable: true, kycExempt: true },
] as const satisfies readonly PageDefinition[];

const BUYER_ONLY = [
  // До KYC покупателю разрешены регистрация, просмотр каталога и ЧЕРНОВИК заявки
  // (ADR-0006, KYC floor) — значит и страница своих заявок нужна ему до верификации.
  // Иначе чек-лист онбординга зовёт создать заявку и упирается в KYC-гейт.
  { id: 'my-requests', buyer: true, kycExempt: true, navigable: true },
  { id: 'suppliers', buyer: true, navigable: true },
] as const satisfies readonly PageDefinition[];

const SELLER_ONLY = [
  // R6: собственных страниц у этих маршрутов больше нет — оба открывают «Справочники» на
  // своей вкладке. Строки оставлены намеренно: хэши напечатаны в закладках и старых письмах,
  // а удалить маршрут — значит отправить такую ссылку на дашборд.
  { id: 'categories', seller: true, kycExempt: true, navigable: true },
  { id: 'equipment-groups', seller: true, kycExempt: true, navigable: true },
  { id: 'catalog-import', seller: true, kycExempt: true, navigable: true },
  { id: 'sourcing-requests', seller: true, navigable: true },
  { id: 'crm-deals', seller: true, navigable: true },
  { id: 'crm-quotes', seller: true, adminReachable: true, navigable: true },
  // Билдер КП — рабочее место ПРОДАВЦА (правка цен, маржи, себестоимости). Покупателю сюда
  // не нужно и нельзя: его вид того же КП живёт на карточке заявки. Ссылки на КП поэтому
  // разрешаются через `documentRoute` по стороне зрителя, а не открытием этой страницы.
  { id: 'deal-quote', seller: true },
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
