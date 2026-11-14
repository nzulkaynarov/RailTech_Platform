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
      ru: "Главная · Задачи",
      uz: "Asosiy · Vazifalar",
      en: "Home · Tasks",
    },
  },
  "dashboard.summary": {
    module: "dashboard",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Главная · Сводка",
      uz: "Asosiy · Xulosa",
      en: "Home · Summary",
    },
  },
  "crm.leads": {
    module: "crm",
    levels: ["read", "full"],
    backends: ["crm"],
    label: {
      ru: "Контакты · Лиды, Ждут ответа, База знаний",
      uz: "Kontaktlar · Lidlar, javob kutmoqda, bilimlar bazasi",
      en: "Contacts · Leads, awaiting reply, knowledge base",
    },
  },
  "crm.leads.triage": {
    module: "crm",
    levels: ["full"],
    backends: ["crm"],
    label: {
      ru: "Контакты · Лиды и Почта · разбор и передача менеджеру",
      uz: "Kontaktlar · Lidlar va pochta · saralash va menejerga topshirish",
      en: "Contacts · Leads and mail · triage and hand over to a manager",
    },
  },
  "crm.mail": {
    module: "crm",
    levels: ["read"],
    backends: ["crm"],
    label: {
      ru: "Контакты · Почта · вся очередь, чтение",
      uz: "Kontaktlar · Pochta · butun navbat, o‘qish",
      en: "Contacts · Mail · whole queue, read",
    },
  },
  "crm.clients": {
    module: "crm",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Контакты · Контрагенты, создать заявку",
      uz: "Kontaktlar · Kontragentlar, ariza yaratish",
      en: "Contacts · Counterparties, new request",
    },
  },
  "eds.inbox": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Документы · Входящие · резолюция",
      uz: "Hujjatlar · Kiruvchi · rezolyutsiya",
      en: "Documents · Incoming · resolution",
    },
  },
  "eds.inbox.register": {
    module: "eds",
    levels: ["full"],
    backends: [],
    label: {
      ru: "Документы · Входящие · регистрация",
      uz: "Hujjatlar · Kiruvchi · ro‘yxatga olish",
      en: "Documents · Incoming · registration",
    },
  },
  "eds.drafts": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Документы · Исходящие · одобрение и отправка КП",
      uz: "Hujjatlar · Chiquvchi · TTni tasdiqlash va yuborish",
      en: "Documents · Outgoing · quote approval and sending",
    },
  },
  "eds.projects": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Главная · Проекты: договор, счёт, акт, сканы",
      uz: "Asosiy · Loyihalar: shartnoma, hisob, dalolatnoma, skanlar",
      en: "Home · Projects: contract, invoice, act, scans",
    },
  },
  "eds.payments": {
    module: "eds",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Операции · Финансы · подтвердить оплату, запросить платёжку",
      uz: "Amallar · Moliya · to‘lovni tasdiqlash, to‘lov topshiriqnomasini so‘rash",
      en: "Operations · Finance · confirm payment, request a payment order",
    },
  },
  "eds.memo.create": {
    module: "eds",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "Документы · Внутренние · создать",
      uz: "Hujjatlar · Ichki · yaratish",
      en: "Documents · Internal · create",
    },
  },
  "eds.memo.approve": {
    module: "eds",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "Документы · Внутренние · согласовать",
      uz: "Hujjatlar · Ichki · kelishish",
      en: "Documents · Internal · approve",
    },
  },
  "eds.signing.manage": {
    module: "eds",
    levels: ["full"],
    backends: [],
    label: {
      ru: "Настройки · Права подписи",
      uz: "Sozlamalar · Imzo huquqlari",
      en: "Settings · Signing authority",
    },
  },
  "eds.visa.finance": {
    module: "eds",
    levels: ["full"],
    backends: [],
    label: {
      ru: "Документы · Виза бухгалтера: договор, счёт, акт",
      uz: "Hujjatlar · Buxgalter vizasi: shartnoma, hisob, dalolatnoma",
      en: "Documents · Accountant visa: contract, invoice, act",
    },
  },
  "eds.visa.legal": {
    module: "eds",
    levels: ["full"],
    backends: [],
    label: {
      ru: "Документы · Виза юриста: договор",
      uz: "Hujjatlar · Yurist vizasi: shartnoma",
      en: "Documents · Lawyer visa: contract",
    },
  },
  "erp.calc": {
    module: "erp",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Операции · Заявки · расчёт",
      uz: "Amallar · Arizalar · hisob-kitob",
      en: "Operations · Requests · costing",
    },
  },
  "erp.calc.goods": {
    module: "erp",
    levels: ["full"],
    backends: ["erp"],
    label: {
      ru: "Операции · Заявки · виза: товары и склад",
      uz: "Amallar · Arizalar · viza: tovarlar va ombor",
      en: "Operations · Requests · sign-off: goods and stock",
    },
  },
  "erp.calc.services": {
    module: "erp",
    levels: ["full"],
    backends: ["erp"],
    label: {
      ru: "Операции · Заявки · виза: услуги",
      uz: "Amallar · Arizalar · viza: xizmatlar",
      en: "Operations · Requests · sign-off: services",
    },
  },
  "erp.stock": {
    module: "erp",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Операции · Каталог и Закупки",
      uz: "Amallar · Katalog va xaridlar",
      en: "Operations · Catalog and purchases",
    },
  },
  "chats.internal": {
    module: "chats",
    levels: ["read", "full"],
    backends: [],
    label: {
      ru: "Органайзер · Чаты и Люди",
      uz: "Organayzer · Chatlar va odamlar",
      en: "Organizer · Chats and people",
    },
  },
  "chats.external": {
    module: "chats",
    levels: ["read", "full"],
    backends: ["crm"],
    label: {
      ru: "Контакты · Переписка с клиентами",
      uz: "Kontaktlar · Mijozlar bilan yozishma",
      en: "Contacts · Client conversations",
    },
  },
  admin: {
    module: "admin",
    levels: ["read", "full"],
    backends: ["crm", "erp"],
    label: {
      ru: "Настройки · Сотрудники, Подключения, Журнал, Статьи компании, Обращения сотрудников",
      uz: "Sozlamalar · Xodimlar, ulanishlar, jurnal, kompaniya maqolalari, xodimlar murojaatlari",
      en: "Settings · Employees, connections, log, company articles, staff requests",
    },
  },
  "company.settings": {
    module: "admin",
    levels: ["read", "full"],
    backends: ["erp"],
    label: {
      ru: "Настройки · Компания и Документы · Шаблоны",
      uz: "Sozlamalar · Kompaniya va hujjatlar · shablonlar",
      en: "Settings · Company and documents · templates",
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
    messages: ["crm.leads", "crm.leads.triage"],
    leads: ["crm.leads", "crm.leads.triage"],
    clients: ["crm.clients", "erp.stock"],
    requests: ["crm.clients"],
    channels: ["crm.leads"],
    kb: ["crm.leads"],
  },
  eds: {
    documents: [
      "eds.inbox",
      "eds.inbox.register",
      "eds.drafts",
      "eds.projects",
      "eds.payments",
      "eds.memo.create",
      "eds.memo.approve",
    ],
    inbox: ["eds.inbox", "eds.inbox.register"],
    mail: ["crm.leads.triage", "crm.leads", "crm.mail"],
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
    overview: ["admin"],
    org: ["admin"],
    roles: ["admin"],
    signing: ["eds.signing.manage"],
    company: ["company.settings"],
    numbering: ["company.settings"],
    taxes: ["company.settings"],
    articles: ["admin"],
    telegram: ["admin"],
    mail: ["admin"],
    forms: ["admin"],
    dictionaries: ["admin", "company.settings"],
    resolutions: ["admin"],
    templates: ["company.settings"],
    timing: ["admin"],
    notifications: ["admin"],
    integrations: ["admin"],
    spend: ["admin"],
    audit: ["admin"],
    exports: ["admin"],
    bus: ["admin"],
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
    ru: "Цены партнёров",
    uz: "Hamkor narxlari",
    en: "Partner prices",
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
  triage_lead: {
    resource: "crm.leads.triage",
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
  rework_document: {
    resource: "eds.memo.create",
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
  send_supplier_order: {
    resource: "erp.stock",
    level: "full",
  },
  partner_date_change: {
    resource: "erp.stock",
    level: "full",
  },
  receive_goods: {
    resource: "erp.stock",
    level: "full",
  },
  partner_application: {
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
  issue_act: {
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
  instruction: {
    resource: "dashboard.queue",
    level: "full",
  },
  instruction_extension: {
    resource: "eds.inbox",
    level: "full",
  },
  acquaint: {
    resource: "dashboard.queue",
    level: "full",
  },
  inbound_mail: {
    resource: "crm.leads.triage",
    level: "full",
  },
  inbound_mail_mine: {
    resource: "dashboard.queue",
    level: "full",
  },
  register_reply: {
    resource: "eds.inbox.register",
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
      "eds.signing.manage": "full",
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
      "crm.mail": "read",
      "crm.clients": "full",
      "eds.inbox": "full",
      "eds.inbox.register": "full",
      "eds.drafts": "full",
      "eds.projects": "full",
      "eds.payments": "read",
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
      "erp.calc": "full",
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
      "eds.visa.finance": "full",
      "erp.calc": "read",
      "erp.stock": "read",
      "chats.internal": "full",
      "chats.external": "full",
    },
    restricted_fields: ["totals_only"],
  },
  REGISTRAR: {
    name: {
      ru: "Делопроизводитель",
      uz: "Ish yurituvchi",
      en: "Office clerk",
    },
    access: {
      "dashboard.queue": "full",
      "crm.leads": "read",
      "crm.leads.triage": "full",
      "crm.clients": "read",
      "eds.inbox": "read",
      "eds.inbox.register": "full",
      "eds.projects": "read",
      "eds.memo.create": "full",
      "chats.internal": "full",
      "chats.external": "read",
    },
    restricted_fields: [],
  },
  MANAGER_ALL: {
    name: {
      ru: "Менеджер-универсал",
      uz: "Universal menejer",
      en: "All-round manager",
    },
    access: {
      "dashboard.queue": "full",
      "crm.leads": "full",
      "crm.clients": "full",
      "eds.inbox": "read",
      "eds.drafts": "read",
      "eds.projects": "full",
      "eds.payments": "full",
      "eds.memo.create": "full",
      "eds.visa.finance": "full",
      "erp.calc": "full",
      "erp.calc.goods": "full",
      "erp.calc.services": "full",
      "erp.stock": "full",
      "chats.internal": "full",
      "chats.external": "full",
    },
    restricted_fields: ["cost_margin", "supplier_prices"],
  },
  LAWYER: {
    name: {
      ru: "Юрист",
      uz: "Yurist",
      en: "Lawyer",
    },
    access: {
      "dashboard.queue": "full",
      "crm.clients": "read",
      "eds.inbox": "read",
      "eds.projects": "read",
      "eds.memo.create": "full",
      "eds.visa.legal": "full",
      "chats.internal": "full",
    },
    restricted_fields: ["totals_only"],
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
