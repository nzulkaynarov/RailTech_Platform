// ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).
// Источник: packages/contracts/platform-rbac.yaml (version 2).
// Пересоздание: make -C apps/platform rbac (make check-platform сверяет с контрактом).
// Разделы, меню, поля, очередь, системные роли и шаблоны — один источник с BFF.
// Роли — данные CRM (названия и матрицы приходят из API).

export type AccessLevel = "full" | "read";
type I18n = { ru: string; uz: string; en: string };

/** Модули рейла в порядке показа. */
export const MODULES = ["dashboard", "crm", "eds", "erp", "chats", "admin"] as const;

export type ModuleCode = (typeof MODULES)[number];

interface ResourceDef {
  module: ModuleCode;
  levels: readonly AccessLevel[];
  backends: readonly string[];
  label: I18n;
}

/** Разделы каталога: модуль, допустимые уровни, бэкенды, подпись строки матрицы. */
export const RESOURCES = {
  "dashboard.queue": {
    module: "dashboard",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "Dashboard · Моя очередь",
      uz: "Dashboard · Mening navbatim",
      en: "Dashboard · My queue",
    },
  },
  "dashboard.summary": {
    module: "dashboard",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Dashboard · Сводка по компании",
      uz: "Dashboard · Kompaniya bo'yicha xulosa",
      en: "Dashboard · Company summary",
    },
  },
  "crm.leads": {
    module: "crm",
    levels: ["read", "full"],
    backends: ["crm"],
    label: {
      ru: "CRM · Все сообщения, Все лиды, Каналы связи, База знаний",
      uz: "CRM · Xabarlar, lidlar, aloqa kanallari, bilimlar bazasi",
      en: "CRM · Messages, leads, channels, knowledge base",
    },
  },
  "crm.clients": {
    module: "crm",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "CRM · Все клиенты, Все заявки, Создать заявку",
      uz: "CRM · Mijozlar, arizalar, ariza yaratish",
      en: "CRM · Clients, requests, create request",
    },
  },
  "eds.inbox": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "EDS · Входящие · резолюция",
      uz: "EDS · Kiruvchi · rezolyutsiya",
      en: "EDS · Inbox · resolution",
    },
  },
  "eds.drafts": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "EDS · Черновик КП · одобрение и отправка",
      uz: "EDS · TT qoralamasi · tasdiqlash va yuborish",
      en: "EDS · Draft quote · approval and sending",
    },
  },
  "eds.projects": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "EDS · Все проекты · договор, счёт, акт, сканы",
      uz: "EDS · Loyihalar · shartnoma, hisob, dalolatnoma, skanlar",
      en: "EDS · Projects · contract, invoice, act, scans",
    },
  },
  "eds.payments": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "EDS · Счета и оплаты · подтвердить оплату, запросить платёжку",
      uz: "EDS · Hisoblar va to'lovlar",
      en: "EDS · Invoices and payments",
    },
  },
  "eds.memo.create": {
    module: "eds",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "EDS · Служебная записка · создать",
      uz: "EDS · Xizmat xati · yaratish",
      en: "EDS · Memo · create",
    },
  },
  "eds.memo.approve": {
    module: "eds",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "EDS · Служебная записка · согласовать",
      uz: "EDS · Xizmat xati · kelishish",
      en: "EDS · Memo · approve",
    },
  },
  "erp.calc": {
    module: "erp",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "ERP · Все запросы, Расчёт",
      uz: "ERP · So'rovlar, hisob-kitob",
      en: "ERP · Requests, calculation",
    },
  },
  "erp.calc.goods": {
    module: "erp",
    levels: ["full"],
    backends: ["erp"],
    label: {
      ru: "ERP · Расчёт · виза по товарам и складу",
      uz: "ERP · Hisob-kitob · tovarlar va ombor vizasi",
      en: "ERP · Calculation · goods and stock sign-off",
    },
  },
  "erp.calc.services": {
    module: "erp",
    levels: ["full"],
    backends: ["erp"],
    label: {
      ru: "ERP · Расчёт · виза по услугам",
      uz: "ERP · Hisob-kitob · xizmatlar vizasi",
      en: "ERP · Calculation · services sign-off",
    },
  },
  "erp.stock": {
    module: "erp",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "ERP · Склад, Справочники, Документация",
      uz: "ERP · Ombor, ma'lumotnomalar, hujjatlar",
      en: "ERP · Stock, catalogs, documentation",
    },
  },
  "chats.internal": {
    module: "chats",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "Chats · Внутренний (проекты, команда)",
      uz: "Chats · Ichki (loyihalar, jamoa)",
      en: "Chats · Internal (projects, team)",
    },
  },
  "chats.external": {
    module: "chats",
    levels: ["read", "full"],
    backends: ["crm"],
    label: {
      ru: "Chats · Внешний (клиент: Telegram-бот, почта)",
      uz: "Chats · Tashqi (mijoz: Telegram-bot, pochta)",
      en: "Chats · External (client: Telegram bot, email)",
    },
  },
  admin: {
    module: "admin",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Admin · Роли, Оргструктура, Интеграции, Тикеты",
      uz: "Admin · Rollar, tuzilma, integratsiyalar, tiketlar",
      en: "Admin · Roles, org chart, integrations, tickets",
    },
  },
  "company.settings": {
    module: "admin",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Компания: реквизиты, шаблоны документов, нумерация, условия оплаты",
      uz: "Kompaniya: rekvizitlar, hujjat shablonlari, raqamlash, to'lov shartlari",
      en: "Company: details, document templates, numbering, payment terms",
    },
  },
} as const satisfies Record<string, ResourceDef>;

export type ResourceKey = keyof typeof RESOURCES;
export const RESOURCE_KEYS = Object.keys(RESOURCES) as ResourceKey[];

/** Меню: модуль -> пункт -> разделы каталога (виден любой из них). */
export const MENU = {
  dashboard: {
    queue: ["dashboard.queue"],
    projects: ["eds.projects"],
    summary: ["dashboard.summary"],
  },
  crm: {
    messages: ["crm.leads"],
    leads: ["crm.leads"],
    clients: ["crm.clients"],
    requests: ["crm.clients"],
    channels: ["crm.leads"],
    kb: ["crm.leads"],
  },
  eds: {
    documents: [
      "eds.inbox",
      "eds.drafts",
      "eds.projects",
      "eds.payments",
      "eds.memo.create",
      "eds.memo.approve",
    ],
    inbox: ["eds.inbox"],
    outbox: ["eds.drafts"],
    projects: ["eds.projects"],
    drafts: ["eds.drafts"],
    approvals: ["eds.memo.approve", "eds.memo.create"],
    payments: ["eds.payments"],
  },
  erp: {
    requests: ["erp.calc"],
    calc: ["erp.calc"],
    stock: ["erp.stock"],
    catalog: ["erp.stock"],
    docs: ["erp.stock"],
  },
  chats: {
    all: ["chats.internal", "chats.external"],
    internal: ["chats.internal"],
    external: ["chats.external"],
    contacts: ["chats.internal"],
  },
  admin: {
    roles: ["admin"],
    org: ["admin"],
    integrations: ["admin"],
    bus: ["admin"],
    tickets: ["admin"],
    company: ["company.settings"],
    audit: ["admin"],
  },
} as const satisfies Record<ModuleCode, Record<string, readonly ResourceKey[]>>;

/** Поля с ограничением: подпись флажка в редакторе роли. */
export const RESTRICTED_FIELDS = {
  cost_margin: {
    ru: "Себестоимость и маржа",
    uz: "Tannarx va marja",
    en: "Cost and margin",
  },
  supplier_prices: {
    ru: "Цены поставщиков",
    uz: "Yetkazib beruvchi narxlari",
    en: "Supplier prices",
  },
  totals_only: {
    ru: "Только итоговые суммы расчёта (без себестоимости по строкам)",
    uz: "Faqat jami summalar",
    en: "Totals only",
  },
} as const satisfies Record<string, I18n>;

export type RestrictedField = keyof typeof RESTRICTED_FIELDS;

/** Вид работы «Моей очереди» -> раздел и уровень не ниже. */
export const QUEUE = {
  answer_lead: {
    resource: "crm.leads",
    level: "full",
  },
  take_lead: {
    resource: "crm.leads",
    level: "full",
  },
  create_request: {
    resource: "crm.clients",
    level: "full",
  },
  service_request: {
    resource: "crm.clients",
    level: "full",
  },
  resolve_letter: {
    resource: "eds.inbox",
    level: "full",
  },
  approve_quote: {
    resource: "eds.drafts",
    level: "full",
  },
  approve_memo: {
    resource: "eds.memo.approve",
    level: "full",
  },
  problem_project: {
    resource: "eds.projects",
    level: "full",
  },
  calc_task: {
    resource: "erp.calc",
    level: "full",
  },
  supplier_overdue: {
    resource: "erp.stock",
    level: "full",
  },
  confirm_payment: {
    resource: "eds.payments",
    level: "full",
  },
  issue_invoice: {
    resource: "eds.payments",
    level: "full",
  },
  issue_contract: {
    resource: "eds.projects",
    level: "full",
  },
  attach_scan: {
    resource: "eds.projects",
    level: "full",
  },
  pay_memo: {
    resource: "eds.payments",
    level: "full",
  },
  overdue_invoice: {
    resource: "eds.payments",
    level: "full",
  },
  ticket: {
    resource: "admin",
    level: "full",
  },
  integration_issue: {
    resource: "admin",
    level: "full",
  },
} as const satisfies Record<string, { resource: ResourceKey; level: AccessLevel }>;

/** Роль каталога: название, матрица и поля с ограничением. */
export interface CatalogRole {
  name: I18n;
  access: Partial<Record<ResourceKey, AccessLevel>>;
  restricted_fields: readonly RestrictedField[];
}

/** Системные роли (неизменны, в интерфейсе — только чтение). */
export const SYSTEM_ROLES = {
  ADMIN: {
    name: {
      ru: "Администратор",
      uz: "Administrator",
      en: "Administrator",
    },
    access: {
      "dashboard.queue": "full",
      "eds.memo.create": "full",
      "chats.internal": "full",
      admin: "full",
      "company.settings": "full",
    },
    restricted_fields: [],
  },
  DIRECTOR: {
    name: {
      ru: "Директор",
      uz: "Direktor",
      en: "Director",
    },
    access: {
      "dashboard.queue": "full",
      "dashboard.summary": "full",
      "crm.leads": "read",
      "crm.clients": "full",
      "eds.inbox": "full",
      "eds.drafts": "full",
      "eds.projects": "full",
      "eds.payments": "full",
      "eds.memo.create": "full",
      "eds.memo.approve": "full",
      "erp.calc": "full",
      "erp.calc.goods": "full",
      "erp.calc.services": "full",
      "erp.stock": "full",
      "chats.internal": "full",
      "chats.external": "read",
      admin: "read",
      "company.settings": "full",
    },
    restricted_fields: ["cost_margin", "supplier_prices"],
  },
} satisfies Record<string, CatalogRole>;

/** Шаблоны ролей для «Создать роль из шаблона». */
export const TEMPLATES = {
  MANAGER: {
    name: {
      ru: "Менеджер",
      uz: "Menejer",
      en: "Manager",
    },
    access: {
      "dashboard.queue": "full",
      "crm.leads": "full",
      "crm.clients": "full",
      "eds.inbox": "read",
      "eds.drafts": "read",
      "eds.projects": "read",
      "eds.payments": "read",
      "eds.memo.create": "full",
      "erp.stock": "read",
      "chats.internal": "full",
      "chats.external": "full",
    },
    restricted_fields: [],
  },
  SUPPLY: {
    name: {
      ru: "Снабженец",
      uz: "Ta'minotchi",
      en: "Supply specialist",
    },
    access: {
      "dashboard.queue": "full",
      "crm.clients": "read",
      "eds.projects": "read",
      "eds.memo.create": "full",
      "erp.calc": "full",
      "erp.calc.goods": "full",
      "erp.stock": "full",
      "chats.internal": "full",
    },
    restricted_fields: ["cost_margin", "supplier_prices"],
  },
  ENGINEER: {
    name: {
      ru: "Гл. инженер",
      uz: "Bosh muhandis",
      en: "Chief engineer",
    },
    access: {
      "dashboard.queue": "full",
      "crm.clients": "read",
      "eds.projects": "read",
      "eds.memo.create": "full",
      "erp.calc": "full",
      "erp.calc.services": "full",
      "erp.stock": "full",
      "chats.internal": "full",
    },
    restricted_fields: [],
  },
  ACCOUNTANT: {
    name: {
      ru: "Бухгалтер",
      uz: "Buxgalter",
      en: "Accountant",
    },
    access: {
      "dashboard.queue": "full",
      "dashboard.summary": "read",
      "crm.clients": "read",
      "eds.inbox": "read",
      "eds.projects": "full",
      "eds.payments": "full",
      "eds.memo.create": "full",
      "erp.calc": "read",
      "erp.stock": "read",
      "chats.internal": "full",
      "chats.external": "full",
    },
    restricted_fields: ["supplier_prices", "totals_only"],
  },
} satisfies Record<string, CatalogRole>;

const RANK: Record<AccessLevel, number> = { read: 1, full: 2 };

/** Матрица доступа: раздел каталога -> уровень; скрытые разделы не перечисляются. */
export type Access = Partial<Record<string, AccessLevel>>;

type Merged = Partial<Record<ResourceKey, AccessLevel>>;

/** Объединение матриц ролей: максимум по разделу (full > read), порядок каталога. */
export function mergeAccess(matrices: readonly Access[]): Merged {
  const merged: Merged = {};
  for (const key of RESOURCE_KEYS) {
    for (const access of matrices) {
      const level = access[key];
      const best = merged[key];
      if (level && (best === undefined || RANK[level] > RANK[best])) merged[key] = level;
    }
  }
  return merged;
}

/** Уровень раздела в матрице не ниже `need` (`read` — чтение, `full` — изменение). */
export function allows(access: Access, resource: ResourceKey, need: AccessLevel = "read"): boolean {
  const level = access[resource];
  return level !== undefined && RANK[level] >= RANK[need];
}

/** Пункт меню виден, если виден хотя бы один из его разделов (`any_of`). */
export function menuItemVisible(access: Access, module: ModuleCode, item: string): boolean {
  const sections = (MENU[module] as Record<string, readonly ResourceKey[]>)[item];
  return sections?.some((key) => access[key] !== undefined) ?? false;
}

/** Видимые пункты меню модуля в порядке контракта. */
export function visibleMenuItems(access: Access, module: ModuleCode): string[] {
  return Object.keys(MENU[module]).filter((item) => menuItemVisible(access, module, item));
}

/** Модули рейла по порядку: виден хотя бы один пункт меню (виза без пункта модуль не открывает). */
export function modulesOf(access: Access): ModuleCode[] {
  return MODULES.filter((module) => visibleMenuItems(access, module).length > 0);
}

/** Разделы, права в которых даёт бэкенд (`crm` или `erp`), видимые в матрице. */
export function sectionsWithBackend(access: Access, backend: "crm" | "erp"): ResourceKey[] {
  const gives = (key: ResourceKey) =>
    (RESOURCES[key].backends as readonly string[]).includes(backend);
  return RESOURCE_KEYS.filter((key) => access[key] !== undefined && gives(key));
}
